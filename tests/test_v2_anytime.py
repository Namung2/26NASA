"""V-2 응답 (docs/spec/S7 §2 V-2).

코어는 시계를 보지 않는다. 대신 탐색이 펼치는 칸의 수(max_expansions)에 상한이 있고, 상한에 닿으면 그때까지의 가장 나은 길을 낸다.
여기서는 그 상한이 지켜지는지, 상한이 작아도 죽지 않고 답을 내는지 본다. 실제 걸리는 시간은 perf 시험이 잰다(-m perf).
"""
from __future__ import annotations

import math
import platform
import time

import numpy as np
import pytest

from host import btcore as bt
from host import bundle as hb
from tests.conftest import make_core
from tests.fixtures import mini_bundle as mb
from tests.helpers import base_passable, path_violations, random_passable_xy


def test_v2_first_solution_within_budget(tier, seeded):
    core, b = make_core(tier)
    ok = base_passable(b, core.cfg.theta_max_deg)
    for budget in (50, 200, 1000):
        for name in ("P1", "P2", "P3"):
            p = core.plan(mb.PARK, mb.POIS[name], max_expansions=budget)
            assert p.status in (bt.OK, bt.PARTIAL), f"{name} 예산 {budget}"       # 닿을 수 있는 쌍이면 길 없음이 아니다
            assert p.n >= 1 and path_violations(p, ok, b.res_m) == (0, 0)
            assert math.dist(p.xy()[0], mb.PARK) <= p.res_m                       # 부분 해도 출발점에서 시작한다
            if p.status == bt.PARTIAL:
                assert not p.complete


def test_v2_expansions_never_exceed_budget(tier, seeded):
    core, b = make_core(tier)
    ok = base_passable(b, core.cfg.theta_max_deg)
    n_partial = 0
    for _ in range(200):
        a, g = random_passable_xy(seeded, ok, b.res_m), random_passable_xy(seeded, ok, b.res_m)
        budget = seeded.choice((1, 10, 100, 1000, 0))                             # 0 = 설정의 상한을 쓴다
        p = core.plan(a, g, max_expansions=budget)
        assert p.status in (bt.OK, bt.PARTIAL, bt.ERR_UNREACHABLE)
        assert p.expansions <= (budget or core.cfg.max_expansions)
        n_partial += p.status == bt.PARTIAL
    assert n_partial > 0                                                          # 작은 예산에서 실제로 상한에 닿았다


@pytest.mark.real
@pytest.mark.perf
def test_v2_replan_p95(tier, seeded, real_bundle_root, capsys):
    """실제 번들에서 경로 하나가 나올 때까지의 시간(바인딩 호출 포함). 100쌍, 직선거리 0.5~5 km. 95번째 백분위 ≤ 2.0 s."""
    b = hb.load(str(real_bundle_root), "field" if tier == "device" else "rover")
    core, _ = make_core(tier, b, park=b.meta["rover_parks"][0]["id"], env=b.env_at(3600.0), field=False)
    ok = base_passable(b, core.cfg.theta_max_deg)
    times, used = [], []
    while len(times) < 100:
        a, g = random_passable_xy(seeded, ok, b.res_m), random_passable_xy(seeded, ok, b.res_m)
        if not 500.0 <= math.dist(a, g) <= 5000.0:
            continue
        t0 = time.perf_counter()
        p = core.plan(a, g)
        times.append(time.perf_counter() - t0)
        used.append(p.expansions)
        if p.status != bt.ERR_UNREACHABLE:
            assert p.expansions <= core.cfg.max_expansions
    p50, p95, worst = (float(np.percentile(times, q)) for q in (50, 95, 100))
    with capsys.disabled():
        print(f"\n  V-2 {tier}: 격자 {ok.shape} @ {b.res_m} m, 경로 100개 — 중앙 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms, 최대 {worst * 1000:.0f} ms, "
              f"펼친 칸 최대 {max(used)} / 상한 {core.cfg.max_expansions} · {platform.system()} {platform.machine()}, Python {platform.python_version()}")
    assert p95 <= 2.0
