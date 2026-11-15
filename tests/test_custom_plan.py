"""사람이 직접 짠 계획 (화면의 "경로 재설정" — wire.CmdPlan, 선택지 이름 custom_plan).

사람이 지도에서 정지점을 차례로 눌러 순서를 짜면, 로버가 그 순서를 선택지 하나로 계산해 다른 카드 옆에 띄운다.
짠다고 계획이 바뀌지 않는다 — 그 카드를 골라야 바뀐다. 출발 한계 안에 끝나지 않는 순서는 카드로 내지 않고 알림을 준다
(넘기는 옵션은 만들지 않는다는 규칙은 사람이 짠 계획에도 그대로다). 선택지는 로버가 계산하므로 연결돼 있을 때만 받는다.
"""
from __future__ import annotations

import pytest

from host import btcore as bt
from host import convert as cv
from host import templates as tp
from host import wire as w
from tests.fixtures import mini_bundle as mb
from tests.scene import Scene, labels


def _custom(s: Scene, d) -> bt.BtOption | None:
    return next((o for o in s.options(d) if bt.LABEL_KEYS[o.label_key] == "custom_plan"), None)


def test_custom_plan_is_offered_next_to_the_others():
    s = Scene()
    d = s.decide(xy=mb.PARK, plan=("P2", "P3"), prev_plan=("P3", "P2"), cause="plan", kind=bt.TRIG_USER_REQUEST)
    mine = _custom(s, d)
    assert mine is not None and d.notices == 0 and d.forced == 0
    assert [(mine.stops[k].xy.x, mine.stops[k].xy.y) for k in range(mine.n_stops)] == [mb.POIS["P3"], mb.POIS["P2"]]   # 짠 순서 그대로
    names = labels(s.options(d))
    assert "continue_plan" in names and names == sorted(names, key=bt.LABEL_KEYS.index)      # 다른 카드와 나란히, 만들어진 순서대로
    assert mine.nlt_margin_min >= 0 and mine.time_min > 0
    dp = cv.decision_from_bt(s.core, d, ["P1", "P2", "P3"])
    assert dp.trigger == "user_request" and dp.cause == "plan" and tp.render_dp_header(dp) == tp.CAUSE["plan"]
    assert [x.poi_id for x in next(o for o in dp.options if o.label_key == "custom_plan").stops] == ["P3", "P2"]


def test_custom_plan_same_as_current_is_just_keep_plan():
    s = Scene()
    d = s.decide(xy=mb.PARK, plan=("P2", "P3"), prev_plan=("P2", "P3"), cause="plan", kind=bt.TRIG_USER_REQUEST)
    assert _custom(s, d) is None and d.notices == 0 and "continue_plan" in labels(s.options(d))


def test_custom_plan_beyond_departure_limit_is_not_offered():
    s = Scene()
    late = s.core.cfg.eva_max_h * 3600.0 - 15 * 60.0          # 15분 남았다 — 두 지점을 다 돌 수 없다
    d = s.decide(xy=mb.PARK, plan=("P2",), prev_plan=("P3", "P2"), cause="plan", kind=bt.TRIG_USER_REQUEST, t=late)
    assert _custom(s, d) is None and d.notices & bt.NOTICE_CUSTOM_UNREACHABLE
    assert all(o.nlt_margin_min >= 0 for o in s.core.decision_candidates(d) if not o.flags & bt.OPTF_LATE)
    dp = cv.decision_from_bt(s.core, d, ["P1", "P2", "P3"])
    assert "custom_plan_unreachable" in dp.notices and tp.NOTICE["custom_plan_unreachable"] in tp.dp_text(dp)


def test_return_request_is_still_return_only():
    s = Scene()
    d = s.decide(xy=mb.PARK, plan=("P2", "P3"), cause="return", kind=bt.TRIG_USER_REQUEST)
    assert labels(s.options(d)) == ["return_rover"]


@pytest.mark.real
def test_custom_plan_end_to_end(real_bundle_root):
    """화면 명령 → 기기 → 로버 → 카드 → 선택 → 계획. 끊겨 있을 때는 받지 않고 알림만 뜬다."""
    from sim.scenario import load_scenario
    from sim.sim import Sim
    sim = Sim(load_scenario("sim/scenarios/D1_demo.yaml"), str(real_bundle_root))
    sim.auto_choose, sim.manual_types = False, {"hyp", "obs", "link"}
    while "P2" not in sim.arrivals:
        sim.step()
    p3 = next(st for st in sim.dev.plan if st.poi_id == "P3")
    p1 = w.Stop(xy=sim.pois["P1"], poi_id="P1", dwell_min=5.0, purpose="poi")
    before = list(sim.dev.plan)
    sim.dev.on_command(w.CmdPlan(stops=[p1, p3]))            # P1에 다시 들렀다가 P3로
    for _ in range(3):
        sim.step()
    dp = sim.dev.snapshot().dp
    assert dp is not None and dp.cause == "plan" and sim.dev.plan == before      # 카드만 떴고 계획은 그대로다
    mine = next(o for o in dp.options if o.label_key == "custom_plan")
    assert [x.poi_id for x in mine.stops] == ["P1", "P3"]
    sim.dev.on_command(w.CmdChoose(dp_id=dp.dp_id, option_id=mine.id))
    for _ in range(3):
        sim.step()
    assert [x.poi_id for x in sim.dev.plan] == ["P1", "P3"] == [x.poi_id for x in sim.rover.plan]   # 골라야 바뀐다. 로버도 같은 계획

    sim.manual["uhf"] = sim.manual["wifi"] = "LOST"         # 끊긴 뒤에는 받지 않는다
    while sim.dev.snapshot().state.link_mode != "LOCAL":
        sim.step()
    sim.dev.outbox()
    sim.dev.on_command(w.CmdPlan(stops=[p3]))
    assert not any(m.type == "plan_request" for m in sim.dev.outbox())
    sim.step()
    assert tp.NOTICE["plan_needs_link"] in sim.dev.snapshot().notices
