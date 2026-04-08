"""설비 서브 모듈 단위."""

from mas.agents.equipment_sub import compute_raw_anomaly, trim_history, estimate_rul_hours


def test_trim_history():
    d = {}
    trim_history(d, "a", 1.0, maxlen=5)
    trim_history(d, "a", 2.0, maxlen=5)
    assert d["a"] == [1.0, 2.0]


def test_compute_raw_anomaly_flat():
    h = [1.0] * 15
    a = compute_raw_anomaly(2.0, 1.0, 0.5, h)
    assert 0.0 <= a <= 1.0


def test_estimate_rul_hours_inf_mtbf():
    r = estimate_rul_hours("WC-01", 90.0, float("inf"), "PRESS")
    assert r > 0
