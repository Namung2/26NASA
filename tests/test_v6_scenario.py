"""V-6 시나리오 (docs/spec/S7 §V-6, S5 §5).

sim/scenarios/V*.yaml을 화면 없이 끝까지 돌리고, 그 파일의 expect가 전부 성립하는지 본다. V1과 V2가 둘 다 통과해야 V-6 통과다.
번들(data/bundles/jezero_west_v1)과 코어 빌드(build/native)가 있어야 한다 — 없으면 건너뛴다.

    .venv/bin/python -m pytest tests/test_v6_scenario.py -q
"""
from pathlib import Path

import pytest

from sim.runner import run_scenario

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/bundles/jezero_west_v1"
SCENARIOS = sorted((ROOT / "sim/scenarios").glob("V*.yaml"))


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_v6_scenario(path, monkeypatch):
    if not (BUNDLE / "meta.json").exists():
        pytest.skip("번들이 없다 — pipeline.build를 먼저 돌린다")
    monkeypatch.chdir(ROOT)                      # 설정 파일을 저장소 루트 기준 경로로 읽는다
    r = run_scenario(path, bundle_root=str(BUNDLE))
    failed = [f"{c.name}: {c.detail}" for c in r.checks if not c.ok]
    assert r.passed, "\n".join(failed)
