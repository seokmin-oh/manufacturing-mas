"""비전/외관 검사 채널 자리 — 추후 이미지·점수 연동."""

from __future__ import annotations

from typing import Any, Dict


def vision_channel_stub(stations: Dict[str, Any]) -> Dict[str, Any]:
    """스테이션 메타만 반환 (실제 비전 점수는 미연동)."""
    return {
        "role": "QA-VISION",
        "stations_with_vision_hint": [sid for sid, d in stations.items() if isinstance(d, dict) and d.get("sensors")],
    }
