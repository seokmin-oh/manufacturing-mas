"""
도메인 소형 모델 자리 — 불량 위험·RUL(잔여 수명) 대역.

현재는 스냅샷 기반 규칙 엔진. 동일 인터페이스로 ONNX/API/엣지 추론을 붙일 수 있다.
"""

from __future__ import annotations

from typing import Any, Dict

from .snapshot_enrichment import enrich_snapshot_for_router


def infer_domain_signals(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    불량 위험·RUL 밴드를 규칙으로 산출.

    Returns:
        defect_risk_band, rul_band, notes, inference_backend
    """
    e = enrich_snapshot_for_router(dict(snapshot))
    vib = float(e.get("vibration") or 0)
    oil = float(e.get("oil_temp") or 0)

    stations = snapshot.get("stations") or {}
    wc = stations.get("WC-01") or {}
    sens = wc.get("sensors") or {}
    vib_d = sens.get("vibration") if isinstance(sens.get("vibration"), dict) else {}
    vib_ma = float(vib_d.get("ma", vib) or 0)

    defect_risk = "LOW"
    if vib >= 4.5 or vib_ma >= 4.2:
        defect_risk = "HIGH"
    elif vib >= 3.5 or vib_ma >= 3.3:
        defect_risk = "MEDIUM"

    rul_band = "GREEN"
    if oil >= 75 or vib >= 5.0:
        rul_band = "RED"
    elif oil >= 60 or vib >= 4.0:
        rul_band = "YELLOW"

    return {
        "defect_risk_band": defect_risk,
        "rul_band": rul_band,
        "vibration_peak": round(vib, 3),
        "vibration_ma": round(vib_ma, 3),
        "inference_backend": "rules_v1",
    }
