"""시험 공용 준비 (docs/spec/S7 §1).

pytest가 Python 바인딩(host/btcore.py)으로 코어 라이브러리를 직접 부른다 — 기기·로버 프로그램이 쓰는 바로 그 파일이다.
코어를 먼저 빌드해야 한다:  .venv/bin/cmake --preset native && .venv/bin/cmake --build --preset native

    .venv/bin/python -m pytest -q                 # 실제 번들이 없어도 도는 것 전부 (시간 재기는 빼고)
    .venv/bin/python -m pytest -q -m perf         # 시간 재기 (실제 번들 필요)
    BT_BUNDLE=data/bundles/jezero_west_v1 .venv/bin/python -m pytest -q    # 실제 번들을 다른 곳에서 읽을 때

마커: real = 실제 번들이 있어야 한다(없으면 건너뛴다), perf = 시간을 잰다(기본으로는 돌지 않는다), scenario = 시뮬레이터 시나리오.
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from host import btcore as bt
from host import bundle as hb
from host import config as hc
from tests.fixtures import mini_bundle

TIERS, PARAMS = str(ROOT / "config/tiers.yaml"), str(ROOT / "config/params.yaml")
REAL_BUNDLE = Path(os.environ.get("BT_BUNDLE", ROOT / "data/bundles/jezero_west_v1"))


def pytest_collection_modifyitems(config, items):
    """perf 시험은 -m perf 로 부를 때만 돈다."""
    if "perf" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="시간 재기 — `-m perf`로 돌린다")
    for item in items:
        if "perf" in item.keywords:
            item.add_marker(skip)


def default_env(t_sunset_s: float = 12 * 3600.0, shadow_bin: int = 0) -> bt.BtEnv:
    """시험용 환경: 해가 떠 있고 먼지·방사선은 평상시. 일몰은 넉넉히 뒤(출발 한계는 EVA 최대 시간에 묶인다)."""
    e = bt.BtEnv()
    e.sun_elev_deg, e.sun_az_deg, e.t_sunset_s = 40.0, 120.0, t_sunset_s
    e.tau_dust, e.dose_rate_uSv_h, e.shadow_bin, e.spe = 0.2, 27.9, shadow_bin, 0
    return e


def state_at(xy, t: float = 3600.0, node: str = "suit-A", rover=mini_bundle.PARK) -> bt.BtState:
    s = bt.BtState()
    s.t, s.pos, s.node, s.link_mode = t, bt.BtXY(float(xy[0]), float(xy[1])), bt.NODE[node], bt.LINK_FULL
    s.rover_pos = bt.BtXY(float(rover[0]), float(rover[1]))
    return s


def make_core(tier: str, bundle: hb.Bundle | None = None, *, park: str = "park1", env: bt.BtEnv | None = None, field: bool = True, **cfg_over):
    """코어 인스턴스 하나: 설정을 읽고, 레이어를 붙이고, 코스트맵을 만들고, (field면) 주차점 기준 귀환 지도까지 계산한다.

    tier = "device"(5 m, 선택지를 만들지 않는다) 또는 "rover"(2 m를 4 m로 먼저 풀고 선택지를 만든다).
    cfg_over로 bt_config의 값을 덮을 수 있다(예: max_expansions=2000).
    돌려주는 것: (core, bundle). bundle이 레이어 배열을 들고 있으므로 core를 쓰는 동안 같이 들고 있어야 한다.
    """
    b = bundle or mini_bundle.make("field" if tier == "device" else "rover")
    cfg = hc.load_config(TIERS, PARAMS, tier, b.meta)
    for k, v in cfg_over.items():
        setattr(cfg, k, v)
    core = bt.Core.create(cfg)
    b.attach(core, park)
    core.set_env(env or default_env())
    core.costmap_build()
    if field:
        core.cost_to_go(b.park_xy(park))
    return core, b


@pytest.fixture
def seeded() -> random.Random:
    """시험 입력을 뽑는 난수(시드 17). 코어 안에는 난수가 없다."""
    return random.Random(17)


@pytest.fixture(params=["device", "rover"])
def tier(request) -> str:
    return request.param


@pytest.fixture
def real_bundle_root() -> Path:
    if not (REAL_BUNDLE / "meta.json").exists():
        pytest.skip(f"실제 번들이 없다: {REAL_BUNDLE}")
    return REAL_BUNDLE
