"""V-1 경사·경로 타당성 (docs/spec/S7 §2 V-1).

코어가 낸 경로가 걸을 수 없는 곳을 지나지 않는지, 귀환 경로와 귀환 지도가 서로 맞는지 본다.
경로는 "그 설정의 원본 레이어 격자"(기기 5 m, 로버 2 m)에 다시 얹어 검사한다 — 코어의 코스트맵을 믿지 않고 레이어에서 바로 본다.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from host import btcore as bt
from host import bundle as hb
from tests.conftest import default_env, make_core, state_at
from tests.fixtures import mini_bundle as mb
from tests.helpers import base_passable, path_violations, random_passable_xy


def test_v1_no_impassable_cells_mini(tier, seeded):
    core, b = make_core(tier)
    ok = base_passable(b, core.cfg.theta_max_deg)
    solved = unreachable = 0
    for _ in range(50):
        a, g = random_passable_xy(seeded, ok, b.res_m), random_passable_xy(seeded, ok, b.res_m)
        p = core.plan(a, g)
        if p.status == bt.ERR_UNREACHABLE:
            unreachable += 1
            continue
        assert p.status in (bt.OK, bt.PARTIAL) and p.n >= 1
        assert path_violations(p, ok, b.res_m) == (0, 0), f"{a} → {g}"
        solved += 1
    assert solved >= 30                              # 대부분은 풀려야 한다(벽 위·갇힌 방처럼 고립된 칸이 뽑히면 도달 불가)
    assert core.plan(mb.PARK, mb.ROOM).status == bt.ERR_UNREACHABLE   # 갇힌 방은 "길 없음"으로만 나온다


@pytest.mark.real
def test_v1_no_impassable_cells_real(tier, real_bundle_root):
    b = hb.load(str(real_bundle_root), "field" if tier == "device" else "rover")
    park = b.meta["rover_parks"][0]
    core, _ = make_core(tier, b, park=park["id"], env=b.env_at(3600.0))
    ok = base_passable(b, core.cfg.theta_max_deg)
    pts = [tuple(park["xy"])] + [tuple(p["xy"]) for p in b.meta["pois"]]
    n = 0
    for i, a in enumerate(pts):
        for g in pts[i + 1:]:
            for s, e in ((a, g), (g, a)):
                p = core.plan(s, e)
                assert p.status in (bt.OK, bt.PARTIAL, bt.ERR_UNREACHABLE)
                if p.status != bt.ERR_UNREACHABLE:
                    assert path_violations(p, ok, b.res_m) == (0, 0), f"{s} → {e}"
                    m = core.path_measure(p, state_at(s))
                    assert m.max_slope_deg <= core.cfg.theta_max_deg + 1e-3
                    n += 1
    assert n >= 6


def test_v1_return_path_matches_field(tier, seeded):
    """귀환 경로 ↔ 귀환 지도.

    지도에 적힌 값은 8방향 계단 길의 시간이고(귀환 경로의 cost로 그대로 나온다), 재는 시간은 그 길을 곧게 편 선의 시간이다
    (2026-11-14 결정, REFERENCE §4.5). 곧게 편 선은 계단 길보다 길 수 없고, 시간은 8방향 격자의 기하학적 한도(1/cos 22.5° ≈ 1.082) 안에서 맞는다.
    출발 한계는 재는 시간과 같은 값을 써야 한다.
    """
    core, b = make_core(tier)
    time_s, _next, fres = core.field_copy()
    ok = base_passable(b, core.cfg.theta_max_deg)
    tried = 0
    for _ in range(100):
        xy = random_passable_xy(seeded, ok, b.res_m)
        r, c = int(-xy[1] // fres), int(xy[0] // fres)
        p = core.return_path(xy)
        if not math.isfinite(time_s[r, c]):
            # 선 칸이 귀환 지도에서 막힌 칸: 가까이(snap_max_m 안)에 갈 수 있는 칸이 있으면 거기서 시작한 경로가 나오고, 없으면 길 없음
            assert p.status in (bt.OK, bt.ERR_UNREACHABLE)
            if p.status == bt.OK:
                assert 0 < p.c.snapped_m <= core.cfg.snap_max_m + 1e-6 and math.dist(p.xy()[0], xy) <= core.cfg.snap_max_m + fres
                assert core.depart_limit(state_at(xy)).degraded == 1      # 출발 한계도 같은 식으로 물러난 값이다
            continue
        assert p.status == bt.OK
        assert p.cost == pytest.approx(float(time_s[r, c]), rel=1e-6)            # 지도에 적힌 값 그대로
        end = p.xy()[-1]
        assert math.dist(end, mb.PARK) <= fres                                    # 로버가 선 칸에서 끝난다
        assert path_violations(p, ok, b.res_m)[0] == 0
        st = state_at(xy)
        m = core.path_measure(p, st, bt.WALK_RETURN)
        assert m.length_m <= p.length_m * (1 + 1e-6) + 1e-3                       # 곧게 편 선 ≤ 계단 길
        if time_s[r, c] > 0:
            assert time_s[r, c] / 1.0824 * 0.97 - 1.0 <= m.time_min * 60.0 <= time_s[r, c] * 1.02 + 1.0
        n = core.depart_limit(st)                                                 # 출발 한계 = 마감 − 귀환 시간(k_return = 1)
        assert n.t_depart == pytest.approx(core.cfg.eva_max_h * 3600.0 - core.cfg.k_return * m.time_min * 60.0, abs=0.1)
        tried += 1
    assert tried >= 60


def test_v1_field_handover_gives_same_limit():
    """로버가 계산한 귀환 지도를 기기에 넘기면 두 쪽의 출발 한계가 같다(격자가 달라도)."""
    rover, _rb = make_core("rover")
    dev, _db = make_core("device", field=False)
    t, nx, res = rover.field_copy()
    dev.set_field(t, nx, res)
    for name in ("P1", "P2", "P3"):
        st = state_at(mb.POIS[name])
        a, d = rover.depart_limit(st), dev.depart_limit(st)
        # 같은 지도, 같은 방향을 따라가지만 곧게 펼 때 보는 통과 가능 칸의 격자가 다르다(로버 4 m, 기기 5 m 원본) → 몇 초 안에서 맞는다
        assert d.t_depart == pytest.approx(a.t_depart, abs=20.0), name
        assert d.binding == a.binding and d.degraded == a.degraded == 0


def test_v1_shadow_bin_changes_costmap_not_passability():
    """그림자 시간 구간이 바뀌면 비용 바탕은 달라지지만 통과 가능 여부는 그대로다."""
    c0, _ = make_core("device", env=default_env(shadow_bin=0))
    c1, _ = make_core("device", env=default_env(shadow_bin=1))
    cost0, pass0, _ = c0.costmap_view()
    cost1, pass1, _ = c1.costmap_view()
    assert np.array_equal(pass0, pass1)
    assert not np.array_equal(cost0, cost1)


@pytest.mark.real
def test_v1_slope_distribution_report(real_bundle_root):
    pytest.skip("번들에 선행 로버의 실제 주행 경로가 없다 — 견줄 대상이 없어 리포트를 만들지 않는다")


def test_v1_return_path_from_blocked_cell_snaps():
    """귀환 지도에서 막힌 칸에 서 있어도(기기의 격자로는 걸을 수 있는 좁은 길) 귀환 경로와 출발 한계가 함께 나온다.
    둘 중 하나만 비면 화면에 "귀환 지도 없음"이 잠깐 뜬다 — 팀원이 걷는 도중에 본 증상이다."""
    rover, rb = make_core("rover")
    t, nx, fres = rover.field_copy()
    dev, _db = make_core("device", field=False)
    dev.set_field(t, nx, fres)
    blocked = ~np.isfinite(t)
    near = np.zeros_like(blocked)                      # 막힌 칸 가운데 바로 옆에 갈 수 있는 칸이 있는 것
    fin = np.isfinite(t)
    near[1:-1, 1:-1] = blocked[1:-1, 1:-1] & (fin[:-2, 1:-1] | fin[2:, 1:-1] | fin[1:-1, :-2] | fin[1:-1, 2:])
    rows, cols = np.nonzero(near)
    assert len(rows) > 10
    for i in range(0, len(rows), max(1, len(rows) // 25)):
        xy = ((cols[i] + 0.5) * fres, -(rows[i] + 0.5) * fres)
        p = dev.return_path(xy)
        assert p.status == bt.OK and 0 < p.c.snapped_m <= dev.cfg.snap_max_m
        n = dev.depart_limit(state_at(xy))
        assert n.degraded == 1 and math.isfinite(n.t_depart)
    assert dev.return_path(mb.ROOM).status == bt.ERR_UNREACHABLE      # 갇힌 방의 한가운데는 여전히 길 없음
    assert rb is not None
