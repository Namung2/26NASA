"""경로 갈림길 (S3a §6.1 ①, §6.2).

갈림길 카드는 "어느 길로 갈지"를 묻는다: 계획 유지(지금 성향의 길)와 나란히, 다음 정지점까지를 다른 성향으로 가는 길
(route_fastest, route_gentle)이 선택지로 나온다. 정지점은 같고 가는 길만 다르다 — 고른 성향은 정지점의 profile에 실려 계획이 기억한다.

"다른 길"의 기준: 두 길이 관측 반경(science.r_obs_m)보다 멀리 벌어져야 한다. 8방향 격자에서는 비용이 같은 길이 칸만 다르게 여러 개
나오는데 곧게 펴면 같은 선이다 — 그런 것은 갈림길로 치지 않고, 고를 다른 길이 없으면 갈림길 카드를 내지 않는다.

이름값: route_fastest는 화면에 적히는 시간이 계획 유지보다 짧을 때만, route_gentle은 화면에 적히는 최대 경사가 계획 유지보다 낮을 때만 나온다.
길은 격자 위의 비용으로 찾고 시간은 곧게 편 선으로 다시 재므로 "빠른 성향"의 길이 다시 잰 뒤에 더 느릴 수 있다(2026-11-15, Inlet 지도의 D2 첫
카드에서 계획 165분 / "Fastest route" 166분 20초로 나온 것을 보고 정한 규칙).
"""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

from host import btcore as bt
from host import bundle as hb
from host import convert as cv
from host import templates as tp
from host import wire as w
from tests.conftest import make_core, state_at
from tests.fixtures import mini_bundle as mb
from tests.helpers import base_passable, random_passable_xy
from tests.scene import Scene, labels, trigger


def test_no_real_alternative_means_no_fork_card():
    """작은 시험 지형에는 벽의 틈이 하나뿐이라 성향이 달라도 같은 길이다 → 갈림길 카드를 내지 않는다(다른 까닭의 카드는 그대로 나온다)."""
    s = Scene()
    d = s.decide(xy=mb.PARK, plan=("P2", "P3"), cause="route")
    assert d.n_options == 0 and d.notices == 0
    assert not any(k in labels(s.core.decision_candidates(d)) for k in ("route_fastest", "route_gentle"))
    s.core.decision_close(d.seq)
    d2 = s.decide(xy=mb.PARK, plan=("P2", "P3"), cause="shadow", kind=bt.TRIG_ENV)
    assert d2.n_options >= 2 and "continue_plan" in labels(s.options(d2))


def test_stop_profile_round_trip_and_labels():
    stop = w.Stop(xy=(10.0, -20.0), poi_id="P2", dwell_min=5.0, purpose="poi", profile="fastest")
    b = cv.to_bt_stop(stop, {"P2": 2})
    assert b.profile == bt.PROFILES.index("fastest") and cv.from_bt_stop(b, ["P1", "P2"]) == stop
    assert w.Stop(xy=(0.0, 0.0), purpose="poi").profile == "balanced"            # 기본은 균형
    assert bt.LABEL_KEYS.index("continue_plan") < bt.LABEL_KEYS.index("route_fastest") < bt.LABEL_KEYS.index("route_gentle") < bt.LABEL_KEYS.index("hyp_target")
    assert set(bt.LABEL_KEYS) == set(tp.LABEL)                                    # 모든 선택지 이름에 화면 글이 있다


def _separation(p: bt.Path_, q: bt.Path_) -> float:
    a, b = p.xy()[::3], q.xy()[::3]
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    return float(max(d.min(1).max(), d.min(0).max()))


@pytest.mark.real
def test_real_fork_offers_the_other_route(real_bundle_root):
    """실제 지형에서 성향별 길이 정말로 갈리는 곳을 찾아, 거기서 갈림길 카드에 다른 길이 선택지로 나오는지 본다."""
    b = hb.load(str(real_bundle_root), "rover")
    park = b.meta["rover_parks"][0]
    core, _ = make_core("rover", b, park=park["id"], env=b.env_at(3600.0))
    core.science_update(3600.0)
    ok = base_passable(b, core.cfg.theta_max_deg)
    rng = random.Random(5)
    found = 0
    for _ in range(600):
        a, g = random_passable_xy(rng, ok, b.res_m), random_passable_xy(rng, ok, b.res_m)
        if not 300 <= math.dist(a, g) <= 1200 or math.dist(a, park["xy"]) > 1500:
            continue
        paths = [core.plan(a, g, profile=i) for i in range(3)]
        if any(p.status != bt.OK for p in paths):
            continue
        apart = [i for i in (1, 2) if _separation(paths[0], paths[i]) > 2 * core.cfg.r_obs_m]
        if not apart:
            continue
        stop = bt.BtStop()
        stop.xy, stop.dwell_min, stop.purpose, stop.poi = bt.BtXY(*g), 10.0, 0, bt.POI_NONE
        d = core.decide(state_at(a, 3600.0, rover=park["xy"]), [stop], trigger(bt.TRIG_FORK, "route"))
        opts = [d.options[k] for k in range(d.n_options)]
        alts = [o for o in opts if bt.LABEL_KEYS[o.label_key] in ("route_fastest", "route_gentle")]
        if alts:
            keep = next(o for o in opts if bt.LABEL_KEYS[o.label_key] == "continue_plan")
            assert opts[0].label_key == keep.label_key                              # 계획 유지가 먼저, 다른 길이 그 옆
            for o in alts:
                assert o.stops[0].profile in (1, 2) and (o.stops[0].xy.x, o.stops[0].xy.y) == (keep.stops[0].xy.x, keep.stops[0].xy.y)
                assert o.nlt_margin_min >= 0
                if bt.LABEL_KEYS[o.label_key] == "route_fastest":                   # 이름값: 더 빠를 때만 "가장 빠른 길"
                    assert o.time_min < keep.time_min
                else:                                                               # 더 완만할 때만 "완만한 길"
                    assert o.max_slope_deg < keep.max_slope_deg
            dp = cv.decision_from_bt(core, d, [p["id"] for p in b.meta["pois"]])
            assert any(o.stops[0].profile != "balanced" for o in dp.options)        # 고르면 그 성향이 계획에 실린다
            assert all(not any(x in line.lower() for x in tp.BANNED) for line in tp.dp_text(dp))
            found += 1
        core.decision_close(d.seq)
        if found >= 3:
            break
    assert found >= 1, "성향별 길이 갈리는 곳을 찾지 못했다"


@pytest.mark.real
def test_named_route_is_better_in_its_own_number(real_bundle_root):
    """갈림길 카드의 후보 전부를 본다(선택지로 뽑히기 전의 것까지): 이름이 붙은 길은 그 이름의 수치에서 계획 유지보다 낫다."""
    b = hb.load(str(real_bundle_root), "rover")
    park = b.meta["rover_parks"][0]
    core, _ = make_core("rover", b, park=park["id"], env=b.env_at(3600.0))
    core.science_update(3600.0)
    ok = base_passable(b, core.cfg.theta_max_deg)
    rng = random.Random(11)
    looked = 0
    for _ in range(400):
        a, g = random_passable_xy(rng, ok, b.res_m), random_passable_xy(rng, ok, b.res_m)
        if not 300 <= math.dist(a, g) <= 1500 or math.dist(a, park["xy"]) > 1500:
            continue
        stop = bt.BtStop()
        stop.xy, stop.dwell_min, stop.purpose, stop.poi = bt.BtXY(*g), 10.0, 0, bt.POI_NONE
        d = core.decide(state_at(a, 3600.0, rover=park["xy"]), [stop], trigger(bt.TRIG_FORK, "route"))
        cands = core.decision_candidates(d)
        keep = next((o for o in cands if bt.LABEL_KEYS[o.label_key] == "continue_plan"), None)
        for o in cands:
            if bt.LABEL_KEYS[o.label_key] == "route_fastest":
                assert o.time_min < keep.time_min
            if bt.LABEL_KEYS[o.label_key] == "route_gentle":
                assert o.max_slope_deg < keep.max_slope_deg
        core.decision_close(d.seq)
        looked += 1
        if looked >= 40:
            break
    assert looked >= 10
