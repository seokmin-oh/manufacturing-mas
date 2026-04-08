"""센서 기반 이상도(원시) 계산 — 트렌드 히스토리는 호출 측에서 유지."""

from __future__ import annotations

from typing import Dict, List


def trim_history(store: Dict[str, List[float]], key: str, val: float, maxlen: int = 200) -> None:
    if key not in store:
        store[key] = []
    store[key].append(val)
    if len(store[key]) > maxlen:
        store[key] = store[key][-maxlen:]


def compute_raw_anomaly(
    value: float,
    ma: float,
    std: float,
    history: List[float],
) -> float:
    """
    Z-score + 단기 상승 트렌드 가중. 반환 0~1.
    EquipmentAgent._detect_anomaly 와 동일 수식.
    """
    if std < 0.001:
        return 0.0
    z_score = abs(value - ma) / max(std, 0.001)

    trend_score = 0.0
    if len(history) >= 10:
        recent = history[-10:]
        increasing = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
        if increasing >= 8:
            trend_score = 0.4
        elif increasing >= 6:
            trend_score = 0.2

    anomaly = min(1.0, (z_score / 3) * 0.6 + trend_score)
    return anomaly
