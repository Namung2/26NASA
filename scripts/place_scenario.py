"""시나리오 배치 — 번들 위에 로버 주차점, 지점 셋(P1·P2·P3), 가설 방향을 규칙으로 놓는다 (docs/spec/S5 §8).

    python scripts/place_scenario.py data/bundles/jezero_west_v1        →  config/placement.yaml 을 쓴다
    python -m pipeline.build --site config/site.yaml --out data/bundles/jezero_west_v1     (그 배치로 번들을 다시 만든다)

같은 번들이면 언제나 같은 배치가 나온다(난수 없음, 동률은 칸 번호 순). 손으로 고르고 싶으면 placement.yaml을 고치면 된다.

규칙 (S5 §8에서 2026-11-14에 바뀐 곳은 ★)
  1 P2 (발견 지점) : 바탕 지도 값이 가장 높은 칸들 가운데, 주변 placement.p2_clear_radius_m 안의 통과 가능 비율이 가장 높은 곳
  2 로버 주차점   ★ P2와 UHF 링크가 되는 완만한 칸 가운데 P2에서 "링크 여유 거리"에 가장 가까운 곳.
                    링크 여유 거리 = 가리는 것이 없을 때 링크가 닿는 한계 거리의 절반. 거리가 절반이면 손실이 12 dB 줄어서
                    (거리의 4제곱 법칙), 중간에 능선 하나가 가려도(칼날 회절 약 14 dB) 링크가 버틴다. 값은 params.yaml의
                    link.radio에서 그때 계산한다. placement.rover_standoff_m(2 km)보다 크면 그 값으로 자른다.
                    → 로버가 작업 구역을 따라다니는 대신, 처음부터 작업 구역 가까이에 선다(로버 경로 계산이 필요 없다).
  3 P1            : P2에서 placement.poi_min_sep_m 이상, 작업 반경 안, 로버에서 max_from_rover_m 안이면서 ★ 링크가 되는 칸 중 값이 가장 높은 곳
    P3            ★ 같은 조건이되 링크가 "안 되는" 칸 중 값이 가장 높은 곳 — 한 구간은 일부러 통신 범위 밖으로 나가 끊김 장면을 만든다.
                    그런 칸이 없으면 링크 되는 칸에서 고른다
  4 가설 방향     : P2에서 8방위 중, placement.hyp_probe_m 떨어진 자리가 통과 가능하고 바탕 지도의 불확실성(분산)이 가장 큰 방향
                    ★ 그 자리가 P1·P3에서 poi_min_sep_m 안이면 그 방위는 뺀다
  값이 같으면 P2에 가까운 칸, 그것도 같으면 칸 번호가 작은 쪽.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import terrain


def flat_link_limit_m(radio: dict) -> float:
    """가리는 것이 없는 평지에서 링크가 닿는 한계 거리: 40·log10(d) − 20·log10(h1·h2) + 여유 = 허용 손실 을 d에 대해 푼 것."""
    h = float(radio["antenna_rover_h_m"]["value"]) * float(radio["antenna_suit_h_m"]["value"])
    spare = float(radio["loss_allow_db"]["value"]) - float(radio["fade_margin_db"]["value"]) + 20.0 * math.log10(h)
    return 10.0 ** (spare / 40.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--params", default="config/params.yaml")
    ap.add_argument("--out", default="config/placement.yaml")
    args = ap.parse_args()
    root = Path(args.bundle)
    meta = json.loads((root / "meta.json").read_text())
    params = yaml.safe_load(Path(args.params).read_text())
    pl, radio = params["placement"], params["link"]["radio"]
    lay = {(x["name"], x["res_m"]): x for x in meta["layers"]}
    res = float(meta["levels_m"][0])
    sl = lay[("slope", res)]
    h, w = sl["shape"]
    slope = np.fromfile(root / sl["file"], dtype="<f2").astype(np.float32).reshape(h, w)
    ev = lay[("elev", res)]
    raw = np.fromfile(root / ev["file"], dtype="<u2").reshape(h, w)
    elev = np.where(raw == 65535, np.nan, raw * ev["scale"] + ev["offset"]).astype(np.float32)
    passable = np.isfinite(slope) & (slope <= float(params["mobility"]["theta_max_deg"]["value"]))
    sres = float(meta["science_res_m"])
    sh = lay[("mu0", sres)]["shape"]
    mu0 = np.fromfile(root / lay[("mu0", sres)]["file"], dtype="<f2").astype(np.float32).reshape(sh)
    var0 = np.fromfile(root / lay[("var0", sres)]["file"], dtype="<f2").astype(np.float32).reshape(sh)
    # 과학 격자의 값을 5 m 격자로 (가장 가까운 칸)
    ridx = np.minimum((np.arange(h) * res / sres).astype(int), sh[0] - 1)
    cidx = np.minimum((np.arange(w) * res / sres).astype(int), sh[1] - 1)
    mu, var = mu0[np.ix_(ridx, cidx)], var0[np.ix_(ridx, cidx)]
    rows, cols = np.mgrid[0:h, 0:w]
    X, Y = (cols + 0.5) * res, -(rows + 0.5) * res

    def dist_from(xy):
        return np.hypot(X - xy[0], Y - xy[1])

    def pick(mask: np.ndarray, near_xy) -> tuple[float, float] | None:
        """mask 안에서 값(mu)이 가장 높은 칸. 같으면 near_xy에 가까운 칸, 그것도 같으면 칸 번호가 작은 쪽."""
        if not mask.any():
            return None
        top = mask & (mu >= np.nanmax(np.where(mask, mu, -np.inf)) - 1e-6)
        d = np.where(top, dist_from(near_xy), np.inf)
        i = int(np.argmin(d))                                   # argmin은 같은 값이면 앞 번호를 준다
        return float(X.flat[i]), float(Y.flat[i])

    extent = w * res
    edge = float(pl["hyp_probe_m"]["value"]) + 100.0            # 가장자리에서 이만큼은 띄운다(가설 방향을 살필 자리)
    inner = (X > edge) & (X < extent - edge) & (Y < -edge) & (Y > -extent + edge)

    # 1. P2: 값이 가장 높은 칸들 중 주변이 가장 트인 곳
    clear_r = float(pl["p2_clear_radius_m"]["value"])
    k = int(round(clear_r / res))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    disk = (xx * xx + yy * yy <= k * k).astype(np.float32)
    from scipy.ndimage import convolve
    open_frac = convolve(passable.astype(np.float32), disk / disk.sum(), mode="constant", cval=0.0)
    cand = passable & inner & np.isfinite(mu)
    top = cand & (mu >= np.nanmax(np.where(cand, mu, -np.inf)) - 1e-6)
    i2 = int(np.argmax(np.where(top, open_frac, -1.0)))
    p2 = (float(X.flat[i2]), float(Y.flat[i2]))

    # 2. 로버 주차점: P2와 링크가 되는 완만한 칸 중 "링크 여유 거리"에 가장 가까운 곳
    limit = flat_link_limit_m(radio)
    standoff = min(float(pl["rover_standoff_m"]["value"]), 0.5 * limit)
    swapped = json.loads(json.dumps(radio))                     # P2에서 내다본다: 안테나 높이를 서로 바꿔 한 번에 계산
    swapped["antenna_rover_h_m"]["value"], swapped["antenna_suit_h_m"]["value"] = radio["antenna_suit_h_m"]["value"], radio["antenna_rover_h_m"]["value"]
    link_from_p2, _sight = terrain.link_mask(elev, res, p2, swapped)
    gentle = passable & inner & (slope <= float(np.nanmedian(slope)))          # 완만한 칸 = 구역 경사의 중앙값 이하
    d2 = dist_from(p2)
    ok = gentle & link_from_p2
    if not ok.any():
        raise SystemExit("P2와 링크가 되는 주차점 후보가 없다")
    # P2에서 내다본 계산은 후보를 한 번에 추리는 용도다. 능선을 하나로 보는 근사라 방향을 바꾸면 결과가 조금 다를 수 있어서,
    # 여유 거리에 가까운 후보부터 "로버 자리에서 본 링크 지도"(번들에 구워질 것과 같은 계산)로 P2가 정말 링크 되는지 확인한다.
    order = np.argsort(np.where(ok, np.abs(d2 - standoff), np.inf), axis=None, kind="stable")
    r2, c2 = int(-p2[1] // res), int(p2[0] // res)
    ip, link = -1, None
    for t in range(40):                                         # 후보 40곳까지 (약 100 m 간격으로 건너뛰며)
        cand_i = int(order[min(t * 400, int(ok.sum()) - 1)])
        cand_xy = (float(X.flat[cand_i]), float(Y.flat[cand_i]))
        cand_link, _sight = terrain.link_mask(elev, res, cand_xy, radio)
        if cand_link[r2, c2]:
            ip, link = cand_i, cand_link
            break
    if ip < 0:
        raise SystemExit("로버 자리에서 P2로 링크가 되는 주차점을 찾지 못했다")
    park = (float(X.flat[ip]), float(Y.flat[ip]))
    dr = dist_from(park)
    sep, work = float(pl["poi_min_sep_m"]["value"]), float(pl["work_radius_m"]["value"])
    base = passable & inner & np.isfinite(mu) & (d2 >= sep) & (d2 <= work) & (dr <= float(pl["max_from_rover_m"]["value"])) & (dr >= sep)

    # 3. P1: 링크 되는 칸에서, P3: 링크 안 되는 칸에서
    p1 = pick(base & link, p2)
    if p1 is None:
        raise SystemExit("P1을 놓을 칸이 없다")
    far1 = dist_from(p1) >= sep
    p3 = pick(base & ~link & far1, p2)
    p3_out = p3 is not None
    if p3 is None:
        p3 = pick(base & link & far1, p2)
    if p3 is None:
        raise SystemExit("P3을 놓을 칸이 없다")

    # 4. 가설 방향
    probe, best = float(pl["hyp_probe_m"]["value"]), (-1.0, 0)
    for az in range(0, 360, 45):
        x, y = p2[0] + probe * math.sin(math.radians(az)), p2[1] + probe * math.cos(math.radians(az))
        r, c = int(-y // res), int(x // res)
        if min(math.hypot(x - q[0], y - q[1]) for q in (p1, p3)) < sep:
            continue                                            # 이미 지점이 있는 쪽은 뺀다 (가설 목표가 P1·P3와 겹치지 않게)
        if 0 <= r < h and 0 <= c < w and passable[r, c] and np.isfinite(var[r, c]) and var[r, c] > best[0]:
            best = (float(var[r, c]), az)

    def at(xy):
        r, c = int(-xy[1] // res), int(xy[0] // res)
        return float(mu[r, c]), bool(link[r, c]), float(dr[r, c])

    out = {
        "generated_by": "scripts/place_scenario.py — 규칙은 그 파일 머리말과 docs/spec/S5 §8",
        "bundle": meta["bundle_id"],
        "report": {"flat_link_limit_m": round(limit, 1), "standoff_used_m": round(standoff, 1), "park_to_P2_m": round(float(d2.flat[ip]), 1),
                   "link_cells_pct": round(float(link.mean()) * 100, 1), "P3_outside_link": p3_out},
        "rover_parks": [{"id": "park1", "xy": [round(park[0], 1), round(park[1], 1)], "note": "배치 규칙 2 — P2와 링크가 되는 완만한 칸"}],
        "pois": [],
        "scenario_hint": {"hyp_anchor": "P2", "hyp_direction_deg": best[1], "hyp_extent_m": probe},
    }
    for pid, xy, kind in (("P1", p1, "feature"), ("P2", p2, "sample"), ("P3", p3, "feature")):
        m, lk, d = at(xy)
        out["pois"].append({"id": pid, "name": pid, "xy": [round(xy[0], 1), round(xy[1], 1)], "kind": kind})
        print(f"  {pid}: ({xy[0]:.0f}, {xy[1]:.0f})  바탕 값 {m:.3f}  로버에서 {d:.0f} m  링크 {'됨' if lk else '안 됨'}")
    print(f"  로버 주차점: ({park[0]:.0f}, {park[1]:.0f})  P2까지 {d2.flat[ip]:.0f} m  (평지 링크 한계 {limit:.0f} m → 여유 거리 {standoff:.0f} m)")
    print(f"  가설 방향: P2에서 {best[1]}° (분산 {best[0]:.4f}) · 구역에서 링크 되는 칸 {out['report']['link_cells_pct']} %")
    Path(args.out).write_text("# 자동으로 만든 파일이다 (scripts/place_scenario.py). 손으로 고쳐도 된다 — 다시 만들면 덮어쓴다.\n"
                              + yaml.safe_dump(out, allow_unicode=True, sort_keys=False))
    print(f"  → {args.out}")


if __name__ == "__main__":
    main()
