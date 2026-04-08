"""시나리오 환경 스모크."""

from pathlib import Path

import pytest

from mas.scenario import ScenarioConfig
from mas.domain.manufacturing_env import ManufacturingEnvironment


def test_merged_snapshot():
    root = Path(__file__).resolve().parents[1]
    p = root / "scenarios" / "normal.yaml"
    if not p.exists():
        pytest.skip("scenarios/normal.yaml 없음")
    sc = ScenarioConfig.load(str(p))
    env = ManufacturingEnvironment(sc)
    snap = env.get_merged_snapshot()
    assert "stations" in snap
    assert "fg_stock" in snap
    assert snap["warehouse"]["stock"] == env.warehouse.stock
