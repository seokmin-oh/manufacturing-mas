"""
공정 유형별 예지보전(PdM) 프로파일
================================

## 이 파일이 하는 일
- `WorkCenter.station_type`(PRESS, WELD, …)마다 **model_id, 신호 목록, 이상 민감도, RUL 스케일** 등
  **설정 딕셔너리**를 제공한다. 별도 학습 가중치 파일은 없음.

## EA 와의 연결
`EquipmentAgent` 가 스냅샷을 만들 때 `profile_for_station_type` / `scale_anomaly_for_type` 등으로
이상 점수·RUL 을 유형에 맞게 스케일한다.

## 현장 이식 시
유형당 실제 ONNX/Torch 서빙 또는 MES 임계 테이블로 **이 프로파일 자리**를 교체하면 된다.
"""


from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

# WorkCenter.station_type 과 정합 (machines.create_*)
EQUIPMENT_PM_MODELS: Dict[str, Dict[str, Any]] = {
    "PRESS": {
        "model_id": "pm-press-vib-hyd-v1",
        "name_kr": "프레스 진동·유압 예지",
        "primary_signals": ("vibration", "oil_temp", "tonnage"),
        "secondary_signals": ("die_clearance", "noise_db", "springback", "stroke_position"),
        "anomaly_sensitivity": 1.05,
        "rul_scale": 1.0,
        "focus": "베어링·유압 펌프·금형 마모",
    },
    "WELD": {
        "model_id": "pm-weld-nugget-v2",
        "name_kr": "스팟용접 너겟·전극 예지",
        "primary_signals": ("weld_current", "weld_force", "nugget_dia"),
        "secondary_signals": ("electrode_tip", "spatter_rate"),
        "anomaly_sensitivity": 1.12,
        "rul_scale": 0.92,
        "focus": "전극 마모·전류 드리프트",
    },
    "HEAT": {
        "model_id": "pm-furnace-soak-v1",
        "name_kr": "열처리 노·경도 예지",
        "primary_signals": ("furnace_temp", "hardness", "quench_temp"),
        "secondary_signals": ("atmosphere", "energy_rate"),
        "anomaly_sensitivity": 0.98,
        "rul_scale": 1.08,
        "focus": "노체·냉각·분위기 가스",
    },
    "CNC": {
        "model_id": "pm-cnc-spindle-v1",
        "name_kr": "CNC 스핀들·진동 예지",
        "primary_signals": ("spindle_vib", "spindle_load", "surface_ra"),
        "secondary_signals": ("coolant_temp", "dimension_dev"),
        "anomaly_sensitivity": 1.08,
        "rul_scale": 0.95,
        "focus": "스핀들·공구·표면 거칠기",
    },
    "ASSY": {
        "model_id": "pm-assy-torque-vision-v1",
        "name_kr": "조립 토크·비전 예지",
        "primary_signals": ("torque", "vision_score", "force"),
        "secondary_signals": ("leak_rate", "final_weight"),
        "anomaly_sensitivity": 1.0,
        "rul_scale": 1.02,
        "focus": "체결·비전·기밀",
    },
}


def profile_for_station_type(station_type: str) -> Dict[str, Any]:
    st = (station_type or "PRESS").upper()
    if st not in EQUIPMENT_PM_MODELS:
        st = "PRESS"
    return dict(EQUIPMENT_PM_MODELS[st])


def scale_anomaly_for_type(
    station_type: str,
    sensor_name: str,
    base_score: float,
) -> float:
    """유형·주요 신호에 따라 이상 점수 스케일."""
    p = profile_for_station_type(station_type)
    pri: Sequence[str] = p.get("primary_signals") or ()
    sec: Sequence[str] = p.get("secondary_signals") or ()
    sens = float(p.get("anomaly_sensitivity", 1.0))
    if sensor_name in pri:
        boost = 1.12
    elif sensor_name in sec:
        boost = 1.0
    else:
        boost = 0.88
    return min(1.0, base_score * sens * boost)


def scale_rul_hours(station_type: str, base_hours: float) -> float:
    p = profile_for_station_type(station_type)
    return max(0.5, base_hours * float(p.get("rul_scale", 1.0)))


def model_catalog() -> List[Dict[str, Any]]:
    """대시보드·문서용 — 유형별 모델 한 줄 요약."""
    out = []
    for st, p in EQUIPMENT_PM_MODELS.items():
        out.append(
            {
                "station_type": st,
                "model_id": p["model_id"],
                "name_kr": p["name_kr"],
                "focus": p["focus"],
            }
        )
    return out
