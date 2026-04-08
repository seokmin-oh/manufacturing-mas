"""잔존수명(RUL) 시간 추정 — 공정 유형별 스케일은 equipment_predictive_models 에 위임."""

from __future__ import annotations

from ...intelligence.equipment_predictive_models import scale_rul_hours


def estimate_rul_hours(
    station_id: str,
    health_score: float,
    mtbf_sec: float,
    station_type: str,
) -> float:
    """
    health_score: 0~100, mtbf_sec: 평균 고장 간격(초), inf 이면 기본 RUL 모델.
    """
    _ = station_id  # 향후 스테이션별 이력 반영 시 사용
    if mtbf_sec == float("inf") or mtbf_sec <= 0:
        base = 100.0
    else:
        base_rul = mtbf_sec / 3600.0
        health_factor = health_score / 100.0
        base = base_rul * health_factor
    return scale_rul_hours(station_type, base)
