"""V-4 가설 루프 (docs/spec/S7 §2 V-4).

가설이 지도와 선택지에 어떻게 들어가고 빠지는지 본다. 코어의 가설 모델을 한 줄로 줄이면 이렇다:
"기준점(관측한 자리)의 값을, 규칙이 정한 모양으로 주변에 옮긴다. 옮겨지는 몫은 확신만큼만 기대값에 들어간다."
그래서 기준점의 값이 주변보다 높지 않으면(예: 관측 없이 가설만 넣으면) 가설이 더하는 것이 없고, 가설 옵션도 나오지 않는다.

시험의 가설은 전부 메뉴 입력과 같은 구조(HypPayload)로 만든다 — tests/scene.py.
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from host import btcore as bt
from host import convert as cv
from tests.fixtures import mini_bundle as mb
from tests.scene import ANCHOR, Scene, hyp_options, labels, stops

SOUTH_40 = (ANCHOR[0], ANCHOR[1] - 40.0)          # 가설(남쪽 100 m)의 범위 안


def at(arr: np.ndarray, res: float, xy) -> float:
    return float(arr[int(-xy[1] // res), int(xy[0] // res)])


def test_v4_hypothesis_option_present():
    a = Scene()
    oa = a.obs()
    da = a.decide(cause="obs", event=oa)
    assert len(hyp_options(a.options(da))) == 0 and "hyp_target" not in labels(a.options(da))     # (a) 관측만: 가설 옵션 0

    b = Scene()
    b.obs()
    h = b.hyp()
    db = b.decide(cause="hyp", event=h)
    hy = hyp_options(b.options(db))
    assert len(hy) == 1 and labels(hy) == ["hyp_target"]                                          # (b) 관측 + 승인된 가설: 정확히 1
    assert bt.STOP_PURPOSES[hy[0].stops[0].purpose] == "hyp_target"
    assert hy[0].hyp_seq[0] == bt.hyp_key(bt.NODE[b.node], 1)
    assert db.notices == 0


def test_v4_hypothesis_without_observation_adds_nothing():
    """관측 없이 가설만 넣으면 기준점의 값이 주변과 같아 옮길 것이 없다 → 가설 옵션이 없고, 까닭을 알리는 비트가 선다.
    "출발 한계 안에 못 간다"(HYP_UNREACHABLE)와는 다른 알림이다."""
    s = Scene()
    h = s.hyp()
    v = s.update()
    assert float(v["add_full"].max()) == 0.0
    d = s.decide(cause="hyp", event=h)
    assert len(hyp_options(s.options(d))) == 0
    assert d.notices & bt.NOTICE_HYP_NO_EFFECT and not d.notices & bt.NOTICE_HYP_UNREACHABLE


def test_v4_info_gain_increases():
    a = Scene()
    a.obs()
    da = a.decide()
    b = Scene()
    b.obs()
    h = b.hyp()
    db = b.decide(cause="hyp", event=h)
    idx = next(i for i in range(db.n_options) if db.options[i].flags & bt.OPTF_FROM_HYPOTHESIS)
    path, stop_list = b.core.decision_path(db, idx), [db.options[idx].stops[k] for k in range(db.options[idx].n_stops)]
    va, vb = a.evaluate(path, stop_list), b.evaluate(path, stop_list)             # 같은 길을 두 지도로 평가
    assert vb.info_gain > va.info_gain
    assert max(o.info_gain for o in b.options(db)) >= max(o.info_gain for o in a.options(da))


def test_v4_value_range_ordering():
    s = Scene()
    s.obs()
    h = s.hyp()
    d = s.decide(cause="hyp", event=h)
    for o in s.options(d):
        if o.flags & bt.OPTF_FROM_HYPOTHESIS:
            assert o.value_lo <= o.value_mean <= o.value_hi and o.value_hi > o.value_lo
        else:
            assert o.value_lo == o.value_hi == o.value_mean and o.hyp_seq[0] == 0      # 범위는 가설 옵션에만 준다


def _delta(rule: str, direction_deg: float = 180.0, extent_m: float = 100.0, anchor=ANCHOR):
    s = Scene()
    s.obs(anchor)
    s.hyp(rule, direction_deg, extent_m, xy=anchor)
    v = s.update()
    return s.core.hyp_delta(0, v["mu"].shape), float(v["res_m"])


def test_v4_four_rules_shape():
    # 층서 연속: 방향 축을 따라(앞뒤 모두) 가중이 크고, 그 축에 수직인 쪽은 작다
    d, res = _delta("strata_continuity", 180.0)
    along, across = at(d, res, (ANCHOR[0], ANCHOR[1] - 50)), at(d, res, (ANCHOR[0] + 50, ANCHOR[1]))
    assert along > 0 and along > 3 * across

    # 근접 군집: 방향을 쓰지 않는다
    d0, _ = _delta("proximity", 0.0)
    d90, _ = _delta("proximity", 90.0)
    assert np.array_equal(d0, d90) and d0.max() > 0

    # 단위 경계: 기준점과 다른 지질 단위의 칸에는 더하지 않는다. (동쪽 단위에 기준점을 두면 서쪽은 다른 단위다 — 근접 규칙은 서쪽에도 더한다)
    n = d0.shape[0]
    west = np.broadcast_to((np.arange(n) + 0.5) * res < mb.WALL_X, (n, n))
    du, _ = _delta("unit_boundary", 270.0, anchor=mb.POIS["P2"])
    dp, _ = _delta("proximity", 270.0, anchor=mb.POIS["P2"])
    assert dp[west].max() > 0 and du[west].max() == 0.0 and du[~west].max() > 0

    # 침식 노출: 평탄한 칸에는 거의 더하지 않고, 경사가 클수록 많이 더한다
    de, _ = _delta("erosion_exposure")
    c = (np.arange(n) + 0.5) * res
    x, y = np.meshgrid(c, -c)
    gy, gx = np.gradient(mb.elevation(x, y), res)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    inside = de > 0
    assert de[slope < 0.5].max() <= 0.05 * de.max()
    assert np.corrcoef(slope[inside], de[inside])[0, 1] > 0.5


def test_v4_unapproved_ignored():
    a = Scene()
    oa = a.obs()
    a.update()
    b = Scene()
    ob = b.obs()
    b.hyp(approved=False)                              # 승인하지 않은 가설
    b.update()
    assert b.core.science_digest() == a.core.science_digest()
    da, db = a.decide(cause="obs", event=oa), b.decide(cause="obs", event=ob)
    assert [o.digest for o in a.options(da)] == [o.digest for o in b.options(db)]
    assert len(hyp_options(b.options(db))) == 0 and db.notices == 0


def test_v4_withdraw_restores_map():
    a = Scene()                                        # 관측 → 가설 → 관측 → 그 가설 철회
    a.obs(ts=3500.0)
    h = a.hyp(ts=3590.0)
    a.obs(SOUTH_40, confirmed=True, ts=3650.0)
    a.update(3660.0)
    with_hyp = a.core.science_digest()
    wd = a.withdraw(h, ts=3700.0)
    a.update(3710.0)

    b = Scene()                                        # 같은 관측들만 있고 가설은 없던 경우
    b.obs(ts=3500.0)
    b.obs(SOUTH_40, confirmed=True, ts=3650.0)
    b.update(3710.0)
    assert a.core.science_digest() == b.core.science_digest() != with_hyp

    tin = bt.BtTriggerIn()                             # 철회 이벤트가 결정 지점의 원인이 된다
    tin.n_changed = 1
    tin.changed[0].lts, tin.changed[0].node = wd.lts, bt.NODE[wd.node]
    from tests.conftest import state_at
    trs = a.core.triggers(state_at(ANCHOR, 3710.0), tin)
    assert len(trs) == 1 and trs[0].kind == bt.TRIG_FORK and bt.CAUSES[trs[0].cause_kind] == "hyp" and trs[0].cause_lts == wd.lts
    d = a.core.decide(state_at(ANCHOR, 3710.0), stops("P2", "P3"), trs[0])
    assert d.n_options >= 1 and len(hyp_options(a.options(d))) == 0 and d.notices == 0
    kinds = [e.type for e in a.core.log_view()]
    assert kinds.count(bt.EV_HYP) == 2                 # 이전 가설 이벤트는 지워지지 않는다(철회도 이벤트 하나다)


def test_v4_withdraw_offers_restore():
    s = Scene()
    s.obs()
    h = s.hyp()
    wd = s.withdraw(h)
    # 가설 옵션을 골라 계획이 [P2]로 줄었던 경우: 고르기 직전의 계획 [P2, P3]을 넘기면 "이전 계획으로"가 나란히 나온다
    d = s.decide(plan=("P2",), prev_plan=("P2", "P3"), cause="hyp", event=wd, t=3710.0)
    restore = [o for o in s.options(d) if bt.LABEL_KEYS[o.label_key] == "restore_plan"]
    cand = [o for o in s.core.decision_candidates(d) if bt.LABEL_KEYS[o.label_key] == "restore_plan"]
    assert len(cand) == 1 and cand[0].n_stops == 2
    assert [(cand[0].stops[k].xy.x, cand[0].stops[k].xy.y) for k in range(2)] == [mb.POIS["P2"], mb.POIS["P3"]]
    assert len(restore) <= 1                           # 카드는 최대 3장이라 뽑히지 않을 수도 있다 — 후보에는 반드시 있다
    s.core.decision_close(d.seq)

    # 이전 계획을 넘기지 않으면(가설 옵션을 고른 적이 없으면) 되돌리기는 없다. 시스템이 계획을 저절로 되돌리지 않는다
    d2 = s.decide(plan=("P2",), cause="hyp", event=wd, t=3710.0)
    assert "restore_plan" not in labels(s.core.decision_candidates(d2))
    s.core.decision_close(d2.seq)

    # 출발 한계가 빡빡하면 되돌리기는 후보에도 없다(넘기는 옵션은 만들지 않는다)
    late = s.core.cfg.eva_max_h * 3600.0 - 20 * 60.0
    d3 = s.decide(plan=("P2",), prev_plan=("P2", "P3"), cause="hyp", event=wd, t=late)
    assert "restore_plan" not in labels(s.core.decision_candidates(d3))
    assert all(o.nlt_margin_min >= 0 for o in s.core.decision_candidates(d3))


def test_v4_confidence_scales():
    views = {}
    for conf in (0.17, 0.83):
        s = Scene()
        s.obs()
        s.hyp(confidence=conf)
        views[conf] = s.update()
    lo, hi = views[0.17], views[0.83]
    assert np.allclose(lo["add_full"], hi["add_full"], atol=1e-7) and hi["add_full"].max() > 0      # 가설이 전부 맞았을 때의 값은 확신과 무관
    m = hi["add_full"] > 1e-4
    assert np.allclose(lo["add_expected"][m] / hi["add_expected"][m], 0.17 / 0.83, rtol=1e-3)         # 기대값에 들어가는 몫은 확신에 비례
    assert np.allclose(hi["add_expected"][m], 0.83 * hi["add_full"][m], rtol=1e-3)


def _confidence_after(extra) -> tuple[float, int, float, float]:
    """관측 → 가설(반반) → extra(scene)로 관측을 더 넣은 뒤의 (지금 확신, 쓰인 관측 수, 그 칸의 바탕값, 가설이 맞을 때 더해지는 값)."""
    s = Scene()
    s.obs(ts=3500.0)
    s.hyp(confidence=0.5, ts=3590.0)
    v = s.update(3600.0)
    res = float(v["res_m"])
    mu, full = at(v["mu"], res, SOUTH_40), at(v["add_full"], res, SOUTH_40)
    extra(s)
    hv = s.update(3700.0)["hyps"][0]
    assert hv["conf_chosen"] == pytest.approx(0.5)     # 고른 값은 바뀌지 않는다
    return hv["conf_now"], hv["n_used"], mu, full


def test_v4_confidence_updates():
    # 확인된 "발견": 가설이 맞을 때 그 칸의 값(mu + full)과 틀릴 때의 값(mu)으로 베이즈 갱신한 값이어야 한다
    c, n, mu, full = _confidence_after(lambda s: s.obs(SOUTH_40, found=True, confirmed=True, ts=3650.0))
    assert full > 0 and n == 1
    assert c == pytest.approx(0.5 * (mu + full) / (0.5 * (mu + full) + 0.5 * mu), abs=1e-4) and c > 0.5
    # 확인된 "없음": 확신이 내려간다
    c, n, mu, full = _confidence_after(lambda s: s.obs(SOUTH_40, found=False, confirmed=True, ts=3650.0))
    assert c == pytest.approx(0.5 * (1 - mu - full) / (0.5 * (1 - mu - full) + 0.5 * (1 - mu)), abs=1e-4) and c < 0.5
    # 확인 안 된 관측은 확신을 바꾸지 않는다
    c, n, _, _ = _confidence_after(lambda s: s.obs(SOUTH_40, found=True, confirmed=False, ts=3650.0))
    assert c == pytest.approx(0.5) and n == 0
    # 가설이 더하는 것이 없는 칸(동쪽 단위 — 바탕값이 기준점보다 높다)의 관측은 확신을 바꾸지 않는다
    c, _, _, _ = _confidence_after(lambda s: s.obs(mb.POIS["P2"], found=True, confirmed=True, ts=3650.0))
    assert c == pytest.approx(0.5, abs=1e-6)

    # 가설보다 앞선 관측은 그 가설의 확신을 바꾸지 않는다
    s = Scene()
    s.obs(ts=3500.0)
    s.obs(SOUTH_40, found=True, confirmed=True, ts=3550.0)
    s.hyp(confidence=0.5, ts=3590.0)
    hv = s.update(3700.0)["hyps"][0]
    assert hv["conf_now"] == pytest.approx(0.5) and hv["n_used"] == 0

    # 같은 로그를 섞어서 다른 인스턴스에 넣어도 같은 확신이 나온다
    src = Scene()
    src.obs(ts=3500.0)
    src.hyp(confidence=0.5, ts=3590.0)
    src.obs(SOUTH_40, found=True, confirmed=True, ts=3650.0)
    src.obs((ANCHOR[0], ANCHOR[1] - 70.0), found=False, confirmed=True, ts=3660.0)
    want = src.update(3700.0)["hyps"][0]["conf_now"]
    events = [cv.to_bt_event(e) for e in src.table.ordered()]
    rng = random.Random(17)
    for _ in range(5):
        rng.shuffle(events)
        other = Scene()
        other.core.log_merge(events)
        assert other.update(3700.0)["hyps"][0]["conf_now"] == want


def test_v4_hypothesis_never_breaks_nlt():
    s = Scene()
    s.obs()
    h = s.hyp(extent_m=100.0)
    # 넉넉할 때의 가설 옵션이 걸리는 시간보다 조금 모자라게 남긴다 → 줄인 변형으로 나오거나, 아예 없고 알림 비트가 선다
    d0 = s.decide(plan=(), cause="hyp", event=h)
    full = hyp_options(s.options(d0))
    assert len(full) == 1
    s.core.decision_close(d0.seq)
    need_min = full[0].time_min + full[0].return_time_min
    for spare in (need_min * 0.8, need_min * 0.4, 1.0):
        t = s.core.cfg.eva_max_h * 3600.0 - spare * 60.0
        d = s.decide(plan=(), cause="hyp", event=h, t=t)
        cands = s.core.decision_candidates(d)
        assert all(o.nlt_margin_min >= 0 for o in cands if not o.flags & bt.OPTF_LATE)     # 출발 한계를 넘기는 옵션은 없다
        hy = hyp_options(cands)
        if hy:
            assert hy[0].time_min < full[0].time_min                                          # 범위를 줄인 변형
        else:
            assert d.notices & bt.NOTICE_HYP_UNREACHABLE
        s.core.decision_close(d.seq)


def _hyp_target_xy(s: Scene, d) -> tuple[float, float] | None:
    hy = hyp_options(s.core.decision_candidates(d))
    return None if not hy else (hy[0].stops[0].xy.x, hy[0].stops[0].xy.y)


@pytest.mark.parametrize(("found", "confirmed"), [(False, False), (False, True), (True, False), (True, True)])
def test_v4_observed_target_is_not_offered_again(found, confirmed):
    """가설 목표는 거기서 관측을 남겨야 끝난다(2026-11-14 결정).
    관측을 남긴 자리의 관측 반경(r_obs) 안은 다시 목표로 나오지 않는다 — "없음"을 남겼는데 바로 옆 칸이 또 목표가 되는 일이 없다."""
    s = Scene()
    s.obs(ts=3500.0)
    h = s.hyp(ts=3590.0)
    d = s.decide(plan=("P2",), cause="hyp", event=h, t=3600.0)
    first = _hyp_target_xy(s, d)
    assert first is not None
    s.core.decision_close(d.seq)
    o = s.obs(first, found=found, confirmed=confirmed, ts=4000.0)        # 가설 목표에 가서 본 것을 남긴다
    d2 = s.decide(xy=ANCHOR, plan=("P2",), cause="obs", event=o, t=4300.0)   # 다른 곳으로 옮긴 뒤 다시 묻는다
    again = _hyp_target_xy(s, d2)
    r_obs = s.core.cfg.r_obs_m
    if again is not None:
        assert ((again[0] - first[0]) ** 2 + (again[1] - first[1]) ** 2) ** 0.5 > r_obs       # 본 자리에서 관측 반경 밖
    assert not d2.notices & bt.NOTICE_HYP_NO_EFFECT or again is None


def test_v4_visited_without_observation_is_offered_again():
    """다녀오기만 하고 관측을 남기지 않으면 지도도 로그도 그대로다 → 같은 목표가 다시 나온다. 기록이 있어야 본 것이다."""
    s = Scene()
    s.obs(ts=3500.0)
    h = s.hyp(ts=3590.0)
    d = s.decide(plan=("P2",), cause="hyp", event=h, t=3600.0)
    first = _hyp_target_xy(s, d)
    s.core.decision_close(d.seq)
    d2 = s.decide(xy=ANCHOR, plan=("P2",), cause="hyp", event=h, t=4300.0)
    assert _hyp_target_xy(s, d2) == first


def test_v4_observation_before_hypothesis_does_not_hide_target():
    """가설보다 앞선 관측은 "그 가설을 보러 간 것"이 아니다 → 그 자리도 목표가 될 수 있다."""
    a = Scene()
    a.obs(ts=3500.0)
    h = a.hyp(ts=3590.0)
    first = _hyp_target_xy(a, a.decide(plan=("P2",), cause="hyp", event=h, t=3600.0))
    b = Scene()
    b.obs(ts=3500.0)
    b.obs(first, found=False, confirmed=False, ts=3550.0)                # 같은 자리를 가설보다 먼저 봤다
    hb = b.hyp(ts=3590.0)
    again = _hyp_target_xy(b, b.decide(plan=("P2",), cause="hyp", event=hb, t=3600.0))
    assert again is not None                                             # 먼저 본 자리라는 이유로 목표가 사라지지는 않는다
