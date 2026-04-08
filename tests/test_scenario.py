"""시나리오 YAML 로드."""

from pathlib import Path

import pytest

from mas.scenario import ScenarioConfig, list_scenarios


@pytest.fixture
def normal_yaml():
    p = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
    if not p.exists():
        pytest.skip("scenarios/normal.yaml 없음")
    return str(p)


def test_load_normal(normal_yaml):
    sc = ScenarioConfig.load(normal_yaml)
    assert sc.name
    assert sc.max_cycles > 0 or "execution" in normal_yaml


def test_list_scenarios():
    root = Path(__file__).resolve().parents[1]
    lst = list_scenarios(str(root / "scenarios"))
    assert isinstance(lst, list)
