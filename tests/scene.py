"""시험용 장면: 로버 쪽 코어 하나와 이벤트 표. 관측·가설을 프로그램과 같은 길(host/convert.py)로 넣는다.

가설은 전부 메뉴 입력과 같은 구조(HypPayload — 규칙·방향·범위·확신 네 칸)로 만든다. 가설을 넣는 길은 그 하나뿐이다(R-20).
"""
from __future__ import annotations

import ctypes as C

from host import btcore as bt
from host import convert as cv
from host import wire as w
from tests.conftest import make_core, state_at
from tests.fixtures import mini_bundle as mb

ANCHOR = mb.POIS["P1"]            # 서쪽(바탕값 0.2). 가설의 기준점으로 쓴다


class Scene:
    def __init__(self, tier: str = "rover", **cfg_over) -> None:
        self.core, self.bundle = make_core(tier, **cfg_over)
        self.node = "rover" if tier == "rover" else "suit-A"     # 코어는 자기가 만든 이벤트에 자기 노드 번호를 찍는다 → 글자 쪽 이름도 같아야 한다
        self.table = cv.EventTable()
        self.n_obs = self.n_hyp = 0

    # ── 이벤트 넣기 ──
    def obs(self, xy=ANCHOR, *, found: bool = True, confirmed: bool = False, ts: float = 3500.0):
        node = self.node
        self.n_obs += 1
        return cv.append_event(self.core, self.table, node, "obs", xy, ts,
                               w.ObsPayload(obs_id=f"{node}:o-{self.n_obs:03d}", kind="found" if found else "not_found", confirmed=confirmed))

    def hyp(self, rule: str = "strata_continuity", direction_deg: float = 180.0, extent_m: float = 100.0, confidence: float = 0.5, *,
            xy=ANCHOR, ts: float = 3590.0, approved: bool = True):
        node = self.node
        self.n_hyp += 1
        return cv.append_event(self.core, self.table, node, "hyp", xy, ts, w.HypPayload(
            hyp_id=f"{node}:h-{self.n_hyp:03d}", rule=rule, direction_deg=direction_deg, extent_m=extent_m, confidence=confidence, origin="script"),
            approved=approved)

    def withdraw(self, hyp_event, *, ts: float = 3700.0):
        """가설 철회: 이전 가설의 값을 그대로 싣고 승인 안 됨으로 넣는다(device/node.py와 같은 방식)."""
        self.n_hyp += 1
        p = hyp_event.payload.model_copy(update={"hyp_id": f"{hyp_event.node}:h-{self.n_hyp:03d}", "supersedes": hyp_event.payload.hyp_id})
        return cv.append_event(self.core, self.table, hyp_event.node, "hyp", hyp_event.geom.xy, ts, p, approved=False)

    def update(self, t: float = 3600.0) -> dict:
        self.core.science_update(t)
        return self.core.science_view()

    # ── 결정 지점 ──
    def decide(self, xy=ANCHOR, plan=("P2", "P3"), *, cause: str = "obs", event=None, t: float = 3600.0, prev_plan=None, kind: int = bt.TRIG_FORK):
        self.core.science_update(t)
        tr = trigger(kind, cause, event)
        d = self.core.decide(state_at(xy, t), stops(*plan), tr, stops(*prev_plan) if prev_plan else None)
        return d

    def options(self, d: bt.BtDecision) -> list[bt.BtOption]:
        return [d.options[i] for i in range(d.n_options)]

    def evaluate(self, path: bt.Path_, stop_list: list[bt.BtStop]) -> bt.BtPathValue:
        pv = bt.BtPathValue()
        arr = (bt.BtStop * max(1, len(stop_list)))(*stop_list)
        assert self.core.lib.bt_path_evaluate(self.core.ctx, C.byref(path.c), arr, len(stop_list), C.byref(pv)) == bt.OK
        return pv


def stops(*names: str, dwell_min: float = 10.0) -> list[bt.BtStop]:
    out = []
    for i, name in enumerate(names):
        s = bt.BtStop()
        s.xy, s.dwell_min, s.purpose, s.poi = bt.BtXY(*mb.POIS[name]), dwell_min, bt.STOP_PURPOSES.index("poi"), i + 1
        out.append(s)
    return out


def trigger(kind: int, cause: str, event=None) -> bt.BtTrigger:
    t = bt.BtTrigger()
    t.kind, t.cause_kind = kind, bt.CAUSES.index(cause)
    if event is not None:
        t.cause_lts, t.cause_node = event.lts, bt.NODE[event.node]
    return t


def labels(opts) -> list[str]:
    return [bt.LABEL_KEYS[o.label_key] for o in opts]


def hyp_options(opts) -> list[bt.BtOption]:
    return [o for o in opts if o.flags & bt.OPTF_FROM_HYPOTHESIS]
