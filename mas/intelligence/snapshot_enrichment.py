"""
공장 스냅샷 → HybridDecisionRouter 가 기대하는 평면 필드로 변환.
"""

from __future__ import annotations

from typing import Any, Dict


def enrich_snapshot_for_router(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """stations.WC-01 센서 등에서 vibration, oil_temp, material_buffer_hours 추출."""
    out: Dict[str, Any] = dict(snapshot)
    stations = snapshot.get("stations") or {}
    wc01 = stations.get("WC-01") or {}
    sensors = wc01.get("sensors") or {}

    def _num(d: Any, key: str, default: float = 0.0) -> float:
        if not isinstance(d, dict):
            return default
        v = d.get(key, d.get("value", d.get("ma")))
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    vib_s = sensors.get("vibration")
    out["vibration"] = _num(vib_s, "value") if isinstance(vib_s, dict) else float(vib_s or 0)

    oil_s = sensors.get("oil_temp")
    out["oil_temp"] = _num(oil_s, "value") if isinstance(oil_s, dict) else float(oil_s or 0)

    mats = snapshot.get("materials") or {}
    min_h = 999.0
    for m in mats.values():
        if isinstance(m, dict):
            ds = m.get("days_supply")
            if ds is not None:
                try:
                    min_h = min(min_h, float(ds) * 24.0)
                except (TypeError, ValueError):
                    pass
    out["material_buffer_hours"] = min_h if min_h < 999.0 else 99.0

    return out
