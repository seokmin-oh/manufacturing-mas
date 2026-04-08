"""SPC·관리도 관점 요약 — QA sense 결과를 가볍게 정리."""

from __future__ import annotations

from typing import Any, Dict


def summarize_spc(observations: Dict[str, Any]) -> Dict[str, Any]:
    cpk = observations.get("cpk_status") or {}
    keys = list(cpk.keys())[:12]
    worst = min((v for v in cpk.values()), default=None)
    return {
        "role": "QA-SPC",
        "tracked_keys_n": len(cpk),
        "sample_keys": keys,
        "worst_cpk": worst,
    }
