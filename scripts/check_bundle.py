"""번들 하나를 코어에 전부 넣어 끝까지 돌려 보는 확인 스크립트.

    python scripts/check_bundle.py data/bundles/jezero_west_v1 [--png reports/check.png]

로버와 기기를 한 프로세스 안에 하나씩 만들고(같은 코어 라이브러리, 설정만 다름), 실제 프로그램이 할 일을 순서대로 흉내 낸다:
  ① 번들 연결 → 코스트맵   ② 로버가 귀환 필드를 계산해 기기에 넘김   ③ 계획 경로   ④ 출발 한계
  ⑤ 기기에서 관측·가설 입력 → 로그 동기화 → 로버가 지도를 다시 계산   ⑥ 로버가 결정 지점(카드)을 냄   ⑦ 기기의 귀환 카드
판단은 전부 코어가 한다. 이 스크립트는 부르는 순서를 보여 주는 것이고, 두 프로그램(device/, rover/)을 만들 때의 본보기다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from host import btcore as bt
from host import bundle as hb
from host import config as hc

TIERS, PARAMS = "config/tiers.yaml", "config/params.yaml"


def make_node(root: str, tier: str, level: str, park: str, t_eva_s: float):
    """노드 하나를 만든다: 번들 읽기 → 설정 → 코어 생성 → 레이어·환경 연결 → 코스트맵."""
    b = hb.load(root, level)
    b.dose_rate_uSv_h = hc.dose_rate_uSv_h(PARAMS)
    core = bt.Core.create(hc.load_config(TIERS, PARAMS, tier, b.meta))
    attached = b.attach(core, park)
    core.log_merge(b.initial_events())                      # 선행 임무의 시료 결과(있으면)
    core.set_env(b.env_at(t_eva_s))
    core.costmap_build()
    return b, core, attached


def stop(xy, dwell_min=0.0, purpose="poi", poi=bt.POI_NONE) -> bt.BtStop:
    s = bt.BtStop()
    s.xy, s.dwell_min, s.purpose, s.poi = bt.BtXY(*xy), dwell_min, bt.STOP_PURPOSES.index(purpose), poi
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--png", default="")
    args = ap.parse_args()

    t_arrive = 4 * 3600 + 49 * 60            # P2에 도착한 시각: EVA 경과 4 h 49 m (아폴로 17 Station 4 도착과 같은 경과)
    t0 = time.time()
    rb, rover, r_att = make_node(args.bundle, "rover", "rover", "park1", 0.0)
    db, dev, d_att = make_node(args.bundle, "device", "field", "park1", 0.0)
    meta = rb.meta
    print(f"번들 {meta['bundle_id']}  (빠진 것: {', '.join(meta['missing_layers'])})")
    print(f"노드 만들기 {time.time() - t0:.1f} s — 로버 {rover.arena_bytes / 1e6:.0f} MB {r_att} / 기기 {dev.arena_bytes / 1e6:.0f} MB {d_att}")
    _c, rp, rres = rover.costmap_view()
    _c, dp, dres = dev.costmap_view()
    print(f"코스트맵: 로버 전역 {rp.shape[0]}×{rp.shape[1]} @ {rres:.0f} m 통과 가능 {100 * rp.mean():.1f} % | 기기 {dp.shape[0]}×{dp.shape[1]} @ {dres:.0f} m 통과 가능 {100 * dp.mean():.1f} %")

    park = rb.park_xy("park1")
    pois = {p["id"]: tuple(p["xy"]) for p in meta["pois"]}
    order = ["P1", "P2", "P3"]

    # ② 로버가 선 자리에서 귀환 필드를 계산 → 기기에 넘긴다 (실제로는 Wi-Fi로, 승무원이 나가기 전에 한 번)
    t0 = time.time()
    rover.cost_to_go(park)
    ft, fn, fres = rover.field_copy()
    dev.set_field(ft, fn, fres)
    print(f"귀환 필드: {1000 * (time.time() - t0):.0f} ms, 칸 {fres:.0f} m, 로버까지 닿는 칸 {100 * np.isfinite(ft).mean():.1f} %")

    # ③ 계획 경로: 로버 → P1 → P2 → P3 → 로버
    st = bt.BtState()
    st.node, st.rover_pos = bt.NODE["suit-A"], bt.BtXY(*park)
    legs, here, names = [], park, ["로버→P1", "P1→P2", "P2→P3", "P3→로버"]
    print("\n구간별 경로 (로버: 2 m로 다시 푼 것 / 기기: 5 m)")
    for name, to in zip(names, [pois[k] for k in order] + [park]):
        row = [name]
        for label, core in (("로버", rover), ("기기", dev)):
            t0 = time.time()
            p = core.plan(here, to)
            ms = 1000 * (time.time() - t0)
            m = core.path_measure(p, st)
            row.append(f"{label}: {bt.STATUS_NAME[p.status]:<7} 칸 {p.res_m:.0f} m, {m.length_m:5.0f} m, {m.time_min:5.1f}분, 최대 경사 {m.max_slope_deg:4.1f}°, "
                       f"로버가 안 보이는 시간 {m.comm_loss_min:5.1f}분, {ms:3.0f} ms")
            if label == "로버":
                legs.append(core.path_polyline(p))          # 그릴 때는 꺾이는 점만 (계단 모양의 칸 경로를 직선 구간으로)
                row.append(f"칸 {p.n} → 꺾이는 점 {len(legs[-1])}")
        print("  " + " | ".join(row))
        here = to

    # 들를 지점과 순서 고르기 (S 항목): 3시간 안에 로버에서 나가 돌아오는 것 가운데 가치의 합이 가장 큰 것
    rover.science_update(0.0)
    cands_poi = [stop(pois[k], 20.0, "poi", i + 1) for i, k in enumerate(order)]
    t0 = time.time()
    picked = rover.select_pois(cands_poi, park, park, time_s=3 * 3600.0)
    print(f"  지점 순서 고르기(3시간 한도): {['P' + str(s_.poi) for s_ in picked]}  ({1000 * (time.time() - t0):.0f} ms)")

    # ④ P2에 섰다. 출발 한계
    st.pos, st.t = bt.BtXY(*pois["P2"]), float(t_arrive)
    for b_, core in ((rb, rover), (db, dev)):
        core.set_env(b_.env_at(st.t))            # 시각이 흘렀다: 그림자 구간이 바뀌었다
        core.costmap_build()
    back = dev.return_path(pois["P2"])
    bm = dev.path_measure(back, st, bt.WALK_RETURN)
    nd, nr = dev.depart_limit(st), rover.depart_limit(st)
    sun = db.sun_at(st.t)
    print(f"\nP2에서 (EVA {t_arrive // 3600} h {t_arrive % 3600 // 60} m, 지방시 {int(sun['lmst_min']) // 60:02d}:{int(sun['lmst_min']) % 60:02d}, 태양 고도 {sun['elev_deg']:.0f}°, 그림자 구간 {sun['shadow_bin']})")
    print(f"  귀환 경로 {bm.length_m:.0f} m, 걷는 시간 {bm.time_min:.1f}분 · 출발 한계까지 여유 {nd.slack_min:.0f}분 ({bt.BINDINGS[nd.binding]}) · 기기와 로버가 같은 값: {nd.t_depart == nr.t_depart}")

    # ⑤ 기기에서 입력: "발견"(확인됨) 관측 + 가설(층서연속, 배치가 고른 방향, 300 m, 반반)
    ob = bt.BtEvent()
    ob.type, ob.ts, ob.x, ob.y, ob.flags, ob.seq = bt.EV_OBS, st.t - 60, pois["P2"][0], pois["P2"][1], bt.EVF_FOUND | bt.EVF_CONFIRMED, 1
    hy = bt.BtEvent()
    hy.type, hy.ts, hy.x, hy.y, hy.flags, hy.seq = bt.EV_HYP, st.t - 30, pois["P2"][0], pois["P2"][1], bt.EVF_APPROVED, 1
    hint = meta.get("scenario_hint") or {}                    # 배치 스크립트가 고른 가설 방향(없으면 북서)
    hy.rule, hy.a, hy.b, hy.c = bt.RULES.index("strata_continuity"), float(hint.get("hyp_direction_deg", 315.0)), float(hint.get("hyp_extent_m", 300.0)), 0.5
    dev.log_append(ob)
    dev.log_append(hy)
    events, _more = dev.log_since(rover.log_have())          # 동기화: 로버가 아직 안 가진 것만 (실제로는 UHF의 sync_up)
    fresh = rover.log_merge(events)
    t0 = time.time()
    rover.science_update(st.t)
    dev.science_update(st.t)
    # 과학 지도의 격자는 로버(5 m)와 기기(번들 격자)가 다르다 → 지도 다이제스트는 서로 견주지 않는다. 로그가 같으면 같은 입력이다
    print(f"\n동기화 {fresh}건 · 로그 다이제스트 같음: {rover.log_digest() == dev.log_digest()} · 지도 재계산(로버 + 기기) {1000 * (time.time() - t0):.0f} ms")
    view = rover.science_view()
    print(f"  바탕 지도: 값 있는 칸의 평균 {np.nanmean(np.where(view['mu'] > 0, view['mu'], np.nan)):.3f}, P2 칸의 값 {view['mu'][int(-pois['P2'][1] // view['res_m']), int(pois['P2'][0] // view['res_m'])]:.3f}, 가설 {len(view['hyps'])}개")

    # ⑥ 로버가 결정 지점을 낸다: 트리거 → 결정
    tin = bt.BtTriggerIn()
    tin.changed[0].lts, tin.changed[0].node, tin.n_changed = events[-1].lts, events[-1].node, 1
    trig = rover.triggers(st, tin)
    plan = [stop(pois["P3"], 20.0, "poi", 3)]
    t0 = time.time()
    d = rover.decide(st, plan, trig[0])
    ms = 1000 * (time.time() - t0)
    cands = rover.decision_candidates(d)
    print(f"결정 지점: 트리거 {[bt.TRIGGERS[t.kind] + '/' + bt.CAUSES[t.cause_kind] for t in trig]}, {ms:.0f} ms, 후보 {len(cands)}개 중 {d.n_options}장")
    names_ko = {"continue_plan": "계획 유지", "hyp_target": "가설 목표", "restore_plan": "되돌리기", "drop_last": "마지막 포기", "stay": "머물기", "return_rover": "로버 귀환"}
    opt_paths = []
    for i in range(d.n_options):
        o = d.options[i]
        rng = f"({o.value_lo:.1f}~{o.value_hi:.1f})" if o.flags & bt.OPTF_FROM_HYPOTHESIS else ""
        print(f"  {'ABC'[o.label]} {names_ko[bt.LABEL_KEYS[o.label_key]]:<6} {o.time_min:3.0f}분, 최대 경사 {o.max_slope_deg:2.0f}°, 선량 {o.dose_uSv:4.1f} µSv, 가치 {o.value_mean:.1f} {rng} {bt.GRADES[o.value_grade]}, "
              f"정보 이득 {o.info_gain:.1f}, 로버가 안 보이는 시간 {o.comm_loss_min:.0f}분, 출발까지 {o.nlt_margin_min:.0f}분")
        opt_paths.append((bt.LABEL_KEYS[o.label_key], rover.path_polyline(rover.decision_path(d, i)), o))
    d2 = rover.decide(st, plan, trig[0])
    print(f"  같은 입력으로 다시 → 다이제스트 같음: {d.digest == d2.digest}")

    # 기상 리플레이: 시각을 5분씩 흘리며 환경을 넣어 본다 — 먼지가 임계를 넘는 순간과 그림자 구간이 바뀌는 순간에 환경 트리거가 난다
    if rb.weather:
        probe, _b2 = bt.Core.create(hc.load_config(TIERS, PARAMS, "rover", rb.meta)), None
        fired, quiet = [], bt.BtTriggerIn()
        for t in range(0, 8 * 3600 + 1, 300):
            st2 = bt.BtState()
            st2.t, st2.node = float(t), bt.NODE["suit-A"]
            probe.set_env(rb.env_at(float(t)))
            for tr in probe.triggers(st2, quiet):
                w = rb.weather_at(float(t))
                fired.append(f"{t // 3600} h {t % 3600 // 60:02d} m {bt.CAUSES[tr.cause_kind]}(tau {w['tau']:.2f})")
        w0, w1 = rb.weather_at(0.0), rb.weather_at(st.t)
        print(f"\n기상 리플레이 sol {meta['env'].get('sol')}: 출발 때 tau {w0['tau']:.2f}, P2에 섰을 때 {w1['tau']:.2f}" + (f", 기온 {w1['t_air_c']:.0f} °C" if w1['t_air_c'] is not None else "")
              + f" · 경고 임계 {probe.cfg.dust_tau_warn:.3f}\n  환경 트리거: {', '.join(fired) if fired else '없음'}")

    # ⑦ 기기: "귀환" 버튼 → 귀환 카드 하나 (링크와 무관하게 기기가 직접 낸다)
    ur = bt.BtTrigger()
    ur.kind, ur.cause_kind = bt.TRIG_USER_REQUEST, bt.CAUSES.index("return")
    dr = dev.decide(st, plan, ur)
    print(f"기기의 귀환 카드: {dr.n_options}장, {dr.options[0].time_min:.0f}분, 출발까지 {dr.options[0].nlt_margin_min:.0f}분")

    if args.png:
        draw(args.png, db, dp, legs, dev.path_polyline(back), opt_paths, park, pois, view)
        print(f"\n그림: {args.png}")


def draw(png: str, db, passable, legs, back, opt_paths, park, pois, view) -> None:
    """확인용 그림: 음영 지형 + 통과불가 + 과학 가치 바탕 지도(색) + 경로."""
    from PIL import Image, ImageDraw, ImageFont
    elev, lay = db.layers["elev"]
    z = elev.astype(np.float32) * lay["scale"] + lay["offset"]
    res, n, S = lay["res_m"], z.shape[0], 1.5
    gy, gx = np.gradient(z, res)
    slope, aspect = np.arctan(np.hypot(gx, gy) * 2.0), np.arctan2(-gx, gy)
    hs = np.sin(np.radians(45)) * np.cos(slope) + np.cos(np.radians(45)) * np.sin(slope) * np.cos(np.radians(315) - aspect)
    g = np.clip(60 + 170 * (hs - hs.min()) / (hs.max() - hs.min()), 0, 255)
    rgb = np.stack([g, g, g], -1)
    # 과학 가치(가설이 맞았을 때의 값)를 색으로 얹는다: 낮음 = 파랑, 높음 = 노랑
    mu = view["mu"] + view["add_full"]
    k = int(np.ceil(n * res / view["res_m"]))
    idx = (np.arange(n) * res / view["res_m"]).astype(int).clip(0, k - 1)
    m5 = mu[np.ix_(idx, idx)]
    has = m5 > 0
    t = np.clip(m5, 0, 1)[..., None]
    tint = (1 - t) * np.array([40, 90, 200]) + t * np.array([255, 220, 40])
    rgb = np.where(has[..., None], rgb * 0.62 + tint * 0.38, rgb * 0.8)
    blocked = passable == 0
    rgb[blocked] = rgb[blocked] * 0.4 + np.array([210, 40, 40]) * 0.6
    # 로버와 UHF 링크가 안 되는 칸은 어둡게
    if "los_park1" in db.layers:
        bits, _lay = db.layers["los_park1"]
        link = np.unpackbits(bits)[: n * n].reshape(n, n).astype(bool)
        rgb[~link] = rgb[~link] * 0.55
    img = Image.fromarray(rgb.astype(np.uint8)).resize((int(n * S), int(n * S)), Image.BILINEAR)
    W = img.width
    canvas = Image.new("RGB", (W + 470, W), (24, 26, 30))
    canvas.paste(img, (0, 0))
    dr = ImageDraw.Draw(canvas)

    def font(sz):
        for f in ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"):
            try:
                return ImageFont.truetype(f, sz)
            except OSError:
                pass
        return ImageFont.load_default()

    F, FB = font(18), font(28)
    px = lambda xy: [(x / res * S, -y / res * S) for x, y in xy]
    for pts in legs:
        dr.line(px(pts), fill=(255, 255, 255), width=3)
    dr.line(px(back), fill=(255, 140, 40), width=4)
    colors = {"continue_plan": (90, 230, 120), "hyp_target": (200, 120, 255), "stay": (120, 200, 255), "return_rover": (255, 140, 40),
              "drop_last": (240, 240, 120), "restore_plan": (240, 160, 200)}
    for key, p, _o in opt_paths:
        if len(p) > 1:
            dr.line(px(p), fill=colors[key], width=4)

    def mark(xy, label, col):
        x, y = px([xy])[0]
        dr.ellipse((x - 11, y - 11, x + 11, y + 11), fill=col, outline=(0, 0, 0), width=3)
        dr.text((x + 15, y - 30), label, font=FB, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))

    mark(park, "로버", (255, 255, 255))
    for k_, xy in pois.items():
        mark(xy, k_, (255, 225, 60))
    for key, _p, o in opt_paths:
        if key == "hyp_target":
            mark((o.stops[0].xy.x, o.stops[0].xy.y), "가설 목표", (200, 120, 255))
    L = 500 / res * S
    dr.line((40, W - 50, 40 + L, W - 50), fill=(255, 255, 255), width=6)
    dr.text((40, W - 84), "500 m", font=F, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    lx, ly = W + 24, 28
    dr.text((lx, ly), db.meta["bundle_id"], font=FB, fill=(255, 255, 255))
    ly += 50
    legend = [((70, 70, 70), "어두운 곳 = 로버와 링크가 안 되는 곳"), ((210, 60, 60), "통과불가 (경사 20° 초과)"), ((255, 255, 255), "계획 경로 (로버 계산, 2 m)"), ((255, 140, 40), "P2에서 로버로 귀환"),
              ((90, 230, 120), "선택지: 계획 유지"), ((200, 120, 255), "선택지: 가설 목표를 거쳐"), ((120, 200, 255), "선택지: 머물기")]
    for col, text in legend:
        dr.rectangle((lx, ly + 4, lx + 34, ly + 20), fill=col)
        dr.text((lx + 46, ly), text, font=F, fill=(235, 235, 235))
        ly += 34
    ly += 10
    for i in range(200):
        t = i / 199
        dr.line((lx + i * 2, ly, lx + i * 2, ly + 18), fill=tuple(int((1 - t) * a + t * b) for a, b in zip((40, 90, 200), (255, 220, 40))), width=2)
    dr.text((lx, ly + 24), "과학 가치 0 (낮음) → 1 (높음)", font=F, fill=(235, 235, 235))
    ly += 60
    for text in ("바탕 지도: 지질 단위 × 광물 표", "(전문가 검토 전 예시값)", "색이 없는 곳 = 근거 문헌 없음", "가설의 영향 범위를 더해 그렸다"):
        dr.text((lx, ly), text, font=F, fill=(190, 195, 205))
        ly += 26
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(png)


if __name__ == "__main__":
    main()
