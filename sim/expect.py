"""시나리오의 expect 판정 (docs/spec/S5 §5).

판정은 전부 시뮬레이터의 기록(SimLog)만 본다. 프로그램 안을 들여다보지 않는다 — 화면이 받는 것과 같은 것만으로 맞고 틀림을 가린다.

■ 독립 계산기 (Independent)
  옵션의 시간과 "출발 한계를 넘지 않는다"는 주장을 코어를 부르지 않고 다시 계산한다. 같은 버그를 나눠 갖지 않기 위해서다.
  - 걷는 시간: 옵션의 경로(꺾이는 점)를 2.5 m 간격으로 짚어 번들의 5 m 고도 레이어에서 높이를 읽고, 진행 방향 경사로 속도를 낸다.
  - 로버 귀환 시간: 5 m 격자에서 scipy의 최단 경로(Dijkstra)를 로버 주차점 기준으로 한 번 푼다. 코어의 탐색 코드와 무관한 구현이다.
  - 마감: min(EVA 최대, 일몰 − 여유). 값은 config/params.yaml과 번들의 태양 표에서 읽는다.
  속도 식은 코어와 같은 출처(REFERENCE §4)를 따로 옮겨 적은 것이다. 식이 같아도 격자·경로·탐색이 다르므로 결과가 조금 다르고,
  그 차이가 metrics_match_independent의 허용 오차(tol) 안인지를 본다.

■ 새 판정을 더하려면: 함수를 쓰고 REGISTRY에 이름을 올린다. 인자는 (ctx, arg), 돌려주는 것은 CheckResult.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from host import bundle as hb

from .scenario import Scenario

FORBIDDEN_FIELD_PARTS = ("recommend", "default", "selected", "score", "rank", "best", "priority")     # S7 V-5


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    measured: float | None = None


# ── 독립 계산기 ───────────────────────────────────────────────────────────
def _slope_factor(th_deg):
    """평지 속도에 곱하는 배율 (REFERENCE §4: NASA ICES-2025-129 식 (2), 급한 내리막은 SEXTANT 속도 표의 기울기)."""
    th = np.asarray(th_deg, dtype=np.float64)
    f = np.where(th >= -10.0, 1.0 - th / 75.0, (1.0 + 10.0 / 75.0) * (1.0 - 0.095 * (-10.0 - th)))
    return np.maximum(f, 0.05)


class Independent:
    """코어 없이 시간과 출발 한계를 다시 계산한다. 번들의 5 m(현장 수준) 레이어만 쓴다."""

    def __init__(self, bundle_root: str | Path, params_path: str | Path = "config/params.yaml", park_id: str = "park1") -> None:
        p = yaml.safe_load(Path(params_path).read_text())
        b = hb.load(str(bundle_root), "field")
        self.res = b.res_m
        e, lay = b.layers["elev"]
        h, wd = lay["shape"]
        raw = np.asarray(e).reshape(h, wd)
        self.elev = np.where(raw == lay.get("nodata", 65535), np.nan, raw.astype(np.float64) * float(lay.get("scale", 1.0)) + float(lay.get("offset", 0.0)))
        s, slay = b.layers["slope"]
        self.slope = np.asarray(s, dtype=np.float64).reshape(slay["shape"])
        mv, sf = p["mobility"], p["safety"]
        self.v_plan = float(mv["v_plan_kmh"]["value"]) / 3.6
        self.v_return = float(mv["v_return_kmh"]["value"]) / 3.6
        self.theta_max = float(mv["theta_max_deg"]["value"])
        self.k_return = float(sf["k_return"]["value"])
        t_eva = float(p["suit"]["eva_max_h"]["value"]) * 3600.0
        t_sun = float(b.sun["t_sunset_s"]) - float(sf["sunset_margin_min"]["value"]) * 60.0
        self.deadline = min(t_eva, t_sun)
        self.park_xy = b.park_xy(park_id)
        self._back: np.ndarray | None = None

    # 좌표 → 높이 (칸 중심 사이를 두 방향으로 보간)
    def _elev_at(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        h, wd = self.elev.shape
        fc, fr = x / self.res - 0.5, -y / self.res - 0.5
        c0 = np.clip(np.floor(fc).astype(int), 0, wd - 2)
        r0 = np.clip(np.floor(fr).astype(int), 0, h - 2)
        a, bb = np.clip(fc - c0, 0, 1), np.clip(fr - r0, 0, 1)
        e = self.elev
        return (e[r0, c0] * (1 - a) * (1 - bb) + e[r0, c0 + 1] * a * (1 - bb) + e[r0 + 1, c0] * (1 - a) * bb + e[r0 + 1, c0 + 1] * a * bb)

    def walk_min(self, path: list, v: float | None = None, step_m: float = 2.5) -> float:
        """경로(꺾이는 점)를 걷는 시간(분). 머무는 시간은 넣지 않는다."""
        v = self.v_plan if v is None else v
        total = 0.0
        for (x0, y0), (x1, y1) in itertools.pairwise(path):
            d = math.dist((x0, y0), (x1, y1))
            if d < 1e-9:
                continue
            n = max(1, math.ceil(d / step_m))
            t = np.linspace(0.0, 1.0, n + 1)
            z = self._elev_at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            ds = d / n
            th = np.degrees(np.arctan(np.nan_to_num(np.diff(z)) / ds))
            total += float(np.sum(ds / (v * _slope_factor(th))))
        return total / 60.0

    def back_field(self) -> np.ndarray:
        """모든 칸에서 로버 주차점까지 걷는 시간(초). 갈 수 없는 칸은 inf. 한 번만 계산한다."""
        if self._back is not None:
            return self._back
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import dijkstra
        h, wd = self.elev.shape
        ok = np.isfinite(self.elev) & np.isfinite(self.slope) & (self.slope <= self.theta_max)
        idx = np.arange(h * wd).reshape(h, wd)
        rows, cols, wts = [], [], []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            src = (slice(max(0, -dr), h - max(0, dr)), slice(max(0, -dc), wd - max(0, dc)))      # 출발 칸 i
            dst = (slice(max(0, dr), h - max(0, -dr)), slice(max(0, dc), wd - max(0, -dc)))      # 도착 칸 j = i + (dr, dc)
            m = ok[src] & ok[dst]
            dist = self.res * (math.sqrt(2.0) if dr and dc else 1.0)
            th = np.degrees(np.arctan((self.elev[dst][m] - self.elev[src][m]) / dist))
            wts.append(dist / (self.v_return * _slope_factor(th)))
            rows.append(idx[dst][m])               # 그래프를 뒤집어 싣는다(j → i). 주차점에서 한 번 풀면 "각 칸 → 주차점" 시간이 된다
            cols.append(idx[src][m])
        g = csr_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(h * wd, h * wd))
        pr, pc = int(-self.park_xy[1] // self.res), int(self.park_xy[0] // self.res)
        self._back = dijkstra(g, directed=True, indices=idx[pr, pc]).reshape(h, wd)
        return self._back

    def back_min(self, xy) -> float:
        """그 자리에서 로버까지 걷는 시간(분). 갈 수 없는 칸이면 가까운 갈 수 있는 칸의 값(20 m 안)."""
        f = self.back_field()
        r, c = int(-xy[1] // self.res), int(xy[0] // self.res)
        if not (0 <= r < f.shape[0] and 0 <= c < f.shape[1]):
            return math.inf
        if np.isfinite(f[r, c]):
            return float(f[r, c]) / 60.0
        win = f[max(0, r - 4): r + 5, max(0, c - 4): c + 5]
        return float(np.min(win)) / 60.0

    def option(self, opt: dict, t_dp: float) -> dict:
        """옵션 하나를 다시 계산한다 → {time_min, back_min, margin_min}. margin_min < 0이면 출발 한계를 넘는다."""
        path = [tuple(q) for q in opt["path"]]
        returning = opt["kind"] == "return"
        walk = self.walk_min(path, self.v_return if returning else self.v_plan) if len(path) > 1 else 0.0
        dwell = sum(float(s["dwell_min"]) for s in opt["stops"])
        time_min = walk + dwell
        back = 0.0 if returning else self.back_min(path[-1])
        margin = (self.deadline - t_dp) / 60.0 - time_min - self.k_return * back
        return {"time_min": time_min, "back_min": back, "margin_min": margin}


# ── 판정에 넘기는 것 ──────────────────────────────────────────────────────
@dataclass
class Ctx:
    log: object                           # sim.sim.SimLog
    scenario: Scenario
    bundle_root: str
    params: dict
    rerun_digest: str | None = None       # 같은 시나리오를 한 번 더 돌린 기록의 다이제스트
    _ind: Independent | None = field(default=None, repr=False)

    @property
    def ind(self) -> Independent:
        if self._ind is None:
            self._ind = Independent(self.bundle_root, park_id=self.scenario.start.rover_park)
        return self._ind

    def inject(self, i: int) -> dict | None:
        return next((r for r in self.log.of("inject") if r["event"] == int(i)), None)

    def dps(self) -> list[dict]:
        return self.log.of("dp")

    def options(self):
        for r in self.dps():
            for o in r["dp"]["options"]:
                yield r, o


def _fail(name: str, why: str) -> CheckResult:
    return CheckResult(name, False, why)


# ── 판정 ──────────────────────────────────────────────────────────────────
def decision_point_within_min_of_event(c: Ctx, arg: dict) -> CheckResult:
    name, inj = "decision_point_within_min_of_event", c.inject(arg["event"])
    if inj is None or not inj.get("event_id"):
        return _fail(name, f"이벤트 {arg['event']}가 일어나지 않았다")
    hit = next((r for r in c.dps() if r["dp"]["cause"] == inj["event_id"] and r["t"] >= inj["t"]), None)
    if hit is None:
        return _fail(name, f"{inj['event_id']}를 원인으로 한 결정 지점이 없다")
    dt = (hit["t"] - inj["t"]) / 60.0
    return CheckResult(name, dt <= float(arg["max_min"]), f"이벤트 {arg['event']} 뒤 {dt * 60:.0f}초에 {hit['dp']['dp_id']} (한도 {arg['max_min']}분)", round(dt, 3))


def option_from_hypothesis_present(c: Ctx, arg) -> CheckResult:
    name = "option_from_hypothesis_present"
    hyps = [r for r in c.log.of("inject") if r["type"] == "hyp" and r.get("event_id")]
    if not hyps:
        return _fail(name, "가설 이벤트가 없다")
    for inj in hyps:
        hit = next((r for r in c.dps() if r["dp"]["cause"] == inj["event_id"]), None)
        if hit is None:
            return _fail(name, f"가설 {inj['event_id']} 뒤 결정 지점이 없다")
        n = sum(1 for o in hit["dp"]["options"] if o["from_hypothesis"])
        if (n >= 1) != bool(arg):
            return _fail(name, f"{hit['dp']['dp_id']}: 가설에서 나온 옵션 {n}개")
    return CheckResult(name, True, f"가설 {len(hyps)}건 모두, 그 뒤 첫 결정 지점에 가설 옵션이 있다")


def no_option_violates_return_limit(c: Ctx, arg) -> CheckResult:
    name, worst, n, bad = "no_option_violates_return_limit", math.inf, 0, []
    for r, o in c.options():
        if o.get("late"):
            continue                      # "늦은 귀환"은 넘은 것을 알리며 내는 유일한 옵션이다(S3a §6) — 넘지 않는다는 주장이 없다
        m = c.ind.option(o, r["t"])["margin_min"]
        n += 1
        worst = min(worst, m)
        if m < 0:
            bad.append(f"{r['dp']['dp_id']}/{o['id']}({m:.1f}분)")
    if n == 0:
        return _fail(name, "검사할 옵션이 없다")
    return CheckResult(name, not bad, f"옵션 {n}개를 다시 계산, 가장 작은 여유 {worst:.1f}분" + (f", 위반 {', '.join(bad)}" if bad else ", 위반 0"), round(worst, 2))


def options_same_format(c: Ctx, arg) -> CheckResult:
    name, keys, n = "options_same_format", None, 0
    for r, o in c.options():
        n += 1
        k = tuple(o.keys())
        if keys is None:
            keys = k
        if k != keys:
            return _fail(name, f"{r['dp']['dp_id']}/{o['id']}: 필드 집합이나 순서가 다르다")
        banned = [f for f in list(o.keys()) + list(r["dp"].keys()) if any(p in f for p in FORBIDDEN_FIELD_PARTS)]
        if banned:
            return _fail(name, f"금지 필드 {banned}")
    if n == 0:
        return _fail(name, "옵션이 없다")
    return CheckResult(name, True, f"옵션 {n}개가 같은 필드 {len(keys)}개를 같은 순서로 가진다. 금지 필드 0")


def metrics_match_independent(c: Ctx, arg: dict) -> CheckResult:
    name, tol, worst, n, where = "metrics_match_independent", float(arg.get("tol", 0.05)), 0.0, 0, ""
    for r, o in c.options():
        if o["time_min"] <= 0:
            continue
        ind = c.ind.option(o, r["t"])["time_min"]
        err = abs(o["time_min"] - ind) / max(ind, 1e-9)
        n += 1
        if err > worst:
            worst, where = err, f"{r['dp']['dp_id']}/{o['id']} 코어 {o['time_min']:.1f}분, 독립 계산 {ind:.1f}분"
    if n == 0:
        return _fail(name, "검사할 옵션이 없다")
    return CheckResult(name, worst <= tol, f"옵션 {n}개, 가장 큰 상대 오차 {worst * 100:.1f} % ({where}), 허용 {tol * 100:.0f} %", round(worst, 4))


def _loss_window(c: Ctx) -> tuple[float, float] | None:
    """기기가 로컬 모드였던 첫 구간 (들어간 시각, 나온 시각). 나오지 않았으면 끝은 기록의 마지막 시각."""
    modes = c.log.of("mode")
    t0 = next((r["t"] for r in modes if r["mode"] == "LOCAL"), None)
    if t0 is None:
        return None
    t1 = next((r["t"] for r in modes if r["mode"] == "FULL" and r["t"] > t0), c.log.rows[-1]["t"])
    return t0, t1


def local_mode_entered_within_s(c: Ctx, arg: dict) -> CheckResult:
    name, inj = "local_mode_entered_within_s", c.inject(arg["event"])
    if inj is None:
        return _fail(name, f"이벤트 {arg['event']}가 일어나지 않았다")
    t = next((r["t"] for r in c.log.of("mode") if r["mode"] == "LOCAL" and r["t"] >= inj["t"]), None)
    if t is None:
        return _fail(name, "로컬 모드로 바뀌지 않았다")
    dt = t - inj["t"]
    return CheckResult(name, dt <= float(arg["max_s"]), f"끊은 뒤 {dt:.1f}초에 로컬 모드 (한도 {arg['max_s']}초)", round(dt, 2))


def options_paused_while_lost(c: Ctx, arg) -> CheckResult:
    name, win = "options_paused_while_lost", _loss_window(c)
    if win is None:
        return _fail(name, "끊긴 구간이 없다")
    t0, t1 = win
    hold = float(c.params["link"]["lost_dp_s"]["value"])
    snaps = [r for r in c.log.of("snap") if t0 <= r["t"] < t1]
    before = [r for r in c.log.of("snap") if r["t"] < t0]
    had_dp = bool(before) and before[-1]["has_dp"]
    if not snaps:
        return _fail(name, "끊긴 구간의 화면 기록이 없다")
    for r in snaps:
        age = r["t"] - t0
        if not (r["has_route"] and r["has_return"] and r["has_nlt"]):
            return _fail(name, f"끊긴 뒤 {age:.0f}초: 경로·귀환 경로·출발 한계 가운데 빈 것이 있다")
        if age < hold - 2 and had_dp and not (r["has_dp"] and r["dp_source"] == "cache"):
            return _fail(name, f"끊긴 뒤 {age:.0f}초: 떠 있던 카드가 계산 시각 표시 없이 바뀌었거나 사라졌다 (source={r['dp_source']})")
        if age > hold + 2 and (not r["paused"] or (r["has_dp"] and r["dp_source"] != "local")):
            return _fail(name, f"끊긴 뒤 {age:.0f}초: 선택지 정지가 아니다 (paused={r['paused']}, dp={r['has_dp']})")
    inj_lost = [r for r in c.log.of("inject") if t0 <= r["t"] < t1 and r["type"] in ("obs", "hyp")]
    if inj_lost and max(r["pending"] for r in snaps) < 1:
        return _fail(name, "끊긴 채로 넣은 이벤트가 대기 건수에 잡히지 않았다")
    return CheckResult(name, True, f"끊긴 {t1 - t0:.0f}초 동안 {len(snaps)}틱 모두 경로·귀환 경로·출발 한계가 있다. {hold:.0f}초까지 카드 유지(cache), 그 뒤 선택지 정지. "
                                   f"대기 건수 최대 {max(r['pending'] for r in snaps)}", float(len(snaps)))


def queue_merged_after_reconnect(c: Ctx, arg: dict) -> CheckResult:
    name, win = "queue_merged_after_reconnect", _loss_window(c)
    fin = c.log.of("final")
    if win is None or not fin:
        return _fail(name, "끊긴 구간이나 마지막 기록이 없다")
    t0, t1 = win
    node = arg.get("node", "suit-A")
    made = [e for e in fin[-1]["dev_events"] if e[0].startswith(node + ":") and t0 <= e[1] < t1]
    rover = set(fin[-1]["rover_ids"])
    missing = [e[0] for e in made if e[0] not in rover]
    if not made:
        return _fail(name, "끊긴 동안 만든 이벤트가 없다")
    return CheckResult(name, not missing, f"끊긴 동안 {node}가 만든 이벤트 {len(made)}건 가운데 로버 로그에 없는 것 {len(missing)}건", float(len(missing)))


def decision_point_after_reconnect_within_min(c: Ctx, arg: dict) -> CheckResult:
    name, win, inj = "decision_point_after_reconnect_within_min", _loss_window(c), c.inject(arg["cause_event"])
    if win is None or inj is None or not inj.get("event_id"):
        return _fail(name, "끊긴 구간이나 그 이벤트가 없다")
    t1 = win[1]
    hit = next((r for r in c.dps() if r["dp"]["cause"] == inj["event_id"] and r["source"] == "rover" and r["t"] >= t1), None)
    if hit is None:
        return _fail(name, f"다시 이어진 뒤 {inj['event_id']}를 원인으로 한 로버의 결정 지점이 오지 않았다")
    dt = (hit["t"] - t1) / 60.0
    return CheckResult(name, dt <= float(arg["max_min"]), f"다시 이어진 뒤 {dt * 60:.0f}초에 {hit['dp']['dp_id']} (한도 {arg['max_min']}분)", round(dt, 3))


def rerun_identical(c: Ctx, arg) -> CheckResult:
    name = "rerun_identical"
    if c.rerun_digest is None:
        return _fail(name, "다시 돌린 기록이 없다")
    same = c.rerun_digest == c.log.digest()
    return CheckResult(name, same, f"두 번 돌린 기록의 다이제스트가 {'같다' if same else '다르다'} ({c.log.digest()[:16]} / {c.rerun_digest[:16]})")


REGISTRY = {f.__name__: f for f in (
    decision_point_within_min_of_event, option_from_hypothesis_present, no_option_violates_return_limit, options_same_format,
    metrics_match_independent, local_mode_entered_within_s, options_paused_while_lost, queue_merged_after_reconnect,
    decision_point_after_reconnect_within_min, rerun_identical)}


# ── D 시나리오의 응답 시간 (timing) ───────────────────────────────────────
def timing(c: Ctx, item: dict) -> CheckResult:
    """{step, event, kind, max_s} — 그 이벤트 뒤 무엇이 나올 때까지 걸린 시간(시뮬 시간, 초).

    kind: mode_local(로컬 모드 배지) | dp(그 이벤트를 원인으로 한 결정 지점) | dp_after_reconnect(다시 이어진 뒤 그 이벤트의 결정 지점)
    """
    step, inj = item.get("step", item.get("kind", "")), c.inject(item["event"])
    if inj is None:
        return _fail(step, f"이벤트 {item['event']}가 일어나지 않았다")
    kind, t = item.get("kind", "dp"), None
    t_from = inj["t"]
    if kind == "mode_local":
        t = next((r["t"] for r in c.log.of("mode") if r["mode"] == "LOCAL" and r["t"] >= inj["t"]), None)
    elif kind == "dp":
        t = next((r["t"] for r in c.dps() if r["dp"]["cause"] == inj.get("event_id") and r["t"] >= inj["t"]), None)
    elif kind == "dp_after_reconnect":
        win = _loss_window(c)
        if win is not None:
            t_from = win[1]
            t = next((r["t"] for r in c.dps() if r["dp"]["cause"] == inj.get("event_id") and r["t"] >= t_from), None)
    if t is None:
        return _fail(step, "나오지 않았다")
    dt = t - t_from
    return CheckResult(step, dt <= float(item["max_s"]), f"{dt:.1f}초 (한도 {item['max_s']}초)", round(dt, 2))
