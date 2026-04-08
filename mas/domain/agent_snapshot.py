"""
에이전트 입력용 스냅샷 보강 — 1급 제조 컨텍스트 + 이벤트 테일.

런타임·프로토콜에서 `sense()` 직전에 호출하여 raw `get_snapshot()` 에
`manufacturing_context`, (선택) 수집 시각을 붙인다.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict


def enrich_snapshot_for_agents(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    얕은 복사 후 `manufacturing_context` 키를 채운다.

    기존 키는 유지하며, 에이전트는 `manufacturing_context` 를 우선 참조할 수 있다.
    """
    out = copy.copy(snapshot)
    if not isinstance(out, dict):
        return out

    from .manufacturing_context import from_factory_snapshot, validate_context_dict

    ingest = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        mctx = from_factory_snapshot(snapshot, ingest_time_utc_iso=ingest)
        mctx_dict = mctx.to_dict()
        out["manufacturing_context"] = mctx_dict
        out["manufacturing_context_validation"] = validate_context_dict(mctx_dict)
    except Exception:
        out["manufacturing_context"] = {"contract_version": "error", "error": "adapter_failed"}
        out["manufacturing_context_validation"] = ["adapter_failed"]

    if isinstance(snapshot.get("business_events"), list):
        out["business_events"] = list(snapshot.get("business_events") or [])
    if isinstance(snapshot.get("external_inputs"), dict):
        out["external_inputs"] = dict(snapshot.get("external_inputs") or {})

    return out
