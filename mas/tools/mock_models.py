"""
Mock AI 모델 및 측정값 생성 함수.
실제 환경에서는 ML 서빙 API(TF Serving, TorchServe)와 비전 카메라 SDK로 대체된다.
"""

import random
import math
from typing import Dict, List

from ..domain.production import Measurement, MEASUREMENT_SPECS


def generate_measurements(vibration_level: float, weld_deviation: float = 0.0) -> Dict[str, Measurement]:
    """
    프레스 진동 + 용접 편차에 따른 제품 측정값 생성.
    진동이 높을수록 치수 산포 증가, 용접 편차가 크면 평탄도/버 악화.
    """
    vib_factor = max(0.0, (vibration_level - 3.0) / 2.5)
    weld_factor = max(0.0, weld_deviation * 3.0)

    specs = MEASUREMENT_SPECS

    s = specs["thickness"]
    thickness_val = random.gauss(
        s["nominal"] + vib_factor * 0.018,
        0.006 + vib_factor * 0.012,
    )

    s = specs["burr_height"]
    burr_val = abs(random.gauss(
        0.020 + vib_factor * 0.10 + weld_factor * 0.03,
        0.010 + vib_factor * 0.025 + weld_factor * 0.01,
    ))

    s = specs["flatness"]
    flat_val = abs(random.gauss(
        0.012 + vib_factor * 0.06 + weld_factor * 0.02,
        0.006 + vib_factor * 0.018 + weld_factor * 0.008,
    ))

    result = {}
    for key, spec in specs.items():
        if key == "thickness":
            val = thickness_val
        elif key == "burr_height":
            val = burr_val
        else:
            val = flat_val
        result[key] = Measurement(
            name=spec["name"],
            value=round(val, 3),
            unit=spec["unit"],
            nominal=spec["nominal"],
            usl=spec["usl"],
            lsl=spec["lsl"],
        )
    return result


CPK_INSUFFICIENT_DATA = 99.0  # 표본 부족 시 반환하는 sentinel 값

def calculate_cpk(values: List[float], usl: float, lsl: float) -> float:
    """SPC 공정능력지수 Cpk 계산."""
    n = len(values)
    if n < 5:
        return CPK_INSUFFICIENT_DATA
    mean = sum(values) / n
    sigma = math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))
    if sigma < 1e-9:
        return CPK_INSUFFICIENT_DATA
    cpu = (usl - mean) / (3 * sigma)
    cpl = (mean - lsl) / (3 * sigma)
    return round(min(cpu, cpl), 2)


def predict_defect_probability(
    vibration: float,
    oil_temp: float,
    vibration_trend_slope: float,
    recent_burr_mean: float,
) -> dict:
    """
    AI 불량 예측 모델 Mock (실제: XGBoost / LSTM).
    센서 데이터와 최근 품질 추세를 입력으로 불량 확률을 반환.
    """
    vib_score = max(0, (vibration - 2.5) / 3.5)
    temp_score = max(0, (oil_temp - 50) / 35)
    trend_score = max(0, vibration_trend_slope * 5)
    burr_score = max(0, (recent_burr_mean - 0.05) / 0.10)

    prob = 0.05 + vib_score * 0.40 + temp_score * 0.10 + trend_score * 0.20 + burr_score * 0.25
    prob = min(max(prob, 0.0), 0.99)

    confidence = min(0.95, 0.60 + vib_score * 0.20 + burr_score * 0.15)

    return {
        "defect_probability": round(prob, 3),
        "confidence": round(confidence, 3),
        "risk_level": "HIGH" if prob > 0.30 else ("MEDIUM" if prob > 0.15 else "LOW"),
        "factors": {
            "vibration": round(vib_score, 3),
            "temperature": round(temp_score, 3),
            "trend": round(trend_score, 3),
            "burr": round(burr_score, 3),
        },
    }


def calculate_oee(
    produced: int,
    good: int,
    planned: int,
    downtime_min: float,
    shift_min: float = 480.0,
) -> dict:
    availability = max(0, (shift_min - downtime_min) / shift_min)
    performance = min(1.0, produced / max(planned, 1))
    quality = good / max(produced, 1)
    oee = availability * performance * quality

    return {
        "availability": round(availability, 4),
        "performance": round(performance, 4),
        "quality_rate": round(quality, 4),
        "oee": round(oee, 4),
    }


def estimate_maintenance(vibration: float, trend_slope: float) -> dict:
    if vibration > 5.0 or trend_slope > 0.15:
        return {"minutes": 45, "urgency": "CRITICAL", "action": "즉시 정지"}
    if vibration > 4.0 or trend_slope > 0.10:
        return {"minutes": 30, "urgency": "HIGH", "action": "계획 정비 권고"}
    if vibration > 3.5:
        return {"minutes": 20, "urgency": "MEDIUM", "action": "다음 교대 시 점검"}
    return {"minutes": 0, "urgency": "LOW", "action": "정상"}


# ── 안전재고 관련 모델 ───────────────────────────────────────────────

def predict_capacity_factor(vibration: float, vib_slope: float, speed_pct: int) -> dict:
    """설비 상태 기반 생산능력 계수 예측 (EA가 사용)."""
    base = speed_pct / 100.0
    degradation = max(0.0, (vibration - 2.5) / 5.0) * 0.15
    trend_penalty = max(0.0, vib_slope * 0.8)
    capacity = max(0.3, base - degradation - trend_penalty)
    reliability = max(0.5, 1.0 - degradation * 2 - trend_penalty)
    return {
        "capacity_factor": round(capacity, 3),
        "reliability": round(reliability, 3),
        "degradation": round(degradation, 3),
        "trend_penalty": round(trend_penalty, 3),
    }


def predict_yield_factor(cpk_worst: float, defect_prob: float) -> dict:
    """품질 기반 수율 계수 예측 (QA가 사용)."""
    if cpk_worst >= 50:
        cpk_yield = 0.95
    elif cpk_worst >= 1.33:
        cpk_yield = 0.98
    elif cpk_worst >= 1.0:
        cpk_yield = 0.92
    else:
        cpk_yield = max(0.70, 0.85 - (1.0 - cpk_worst) * 0.3)

    predicted_yield = cpk_yield * (1.0 - defect_prob * 0.5)
    yield_std = max(0.01, (1.0 - predicted_yield) * 0.3 + defect_prob * 0.1)

    return {
        "predicted_yield": round(predicted_yield, 3),
        "yield_std": round(yield_std, 4),
        "cpk_yield": round(cpk_yield, 3),
    }


def compute_leadtime_params(
    capacity_factor: float,
    yield_factor: float,
    base_takt_sec: float = 45.0,
) -> dict:
    """실효 리드타임 및 변동성 계산."""
    effective_takt = base_takt_sec / max(capacity_factor, 0.3)
    effective_rate = yield_factor * capacity_factor
    lt_mean = max(1.0, 1.0 / max(effective_rate, 0.1))
    lt_std = max(0.1, lt_mean * (1.0 - min(capacity_factor, yield_factor)) * 0.8)

    return {
        "leadtime_mean": round(lt_mean, 3),
        "leadtime_std": round(lt_std, 4),
        "effective_takt_sec": round(effective_takt, 1),
        "effective_rate": round(effective_rate, 3),
    }
