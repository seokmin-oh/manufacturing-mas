from __future__ import annotations

from typing import Any, Dict, List

from ...protocol.cnp_comparison import merge_into_proposal, normalize_comparison_metrics


def rank_proposals_by_comparison(proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """comparison 블록을 채운 뒤 total_score 기준 내림차순."""
    enriched: List[Dict[str, Any]] = []
    for p in proposals:
        if not isinstance(p, dict):
            continue
        merge_into_proposal(p)
        comp = p.get("comparison") or normalize_comparison_metrics(p)
        eff = float(comp.get("expected_effect") or 0.5)
        cost = float(comp.get("expected_cost") or 0.5)
        qrisk = float(comp.get("quality_risk") or 0.3)
        viol = float(comp.get("constraint_violation") or 0.0)
        conf = float(comp.get("confidence") or 0.7)
        adj = eff * conf - 0.35 * cost - 0.25 * qrisk - 0.15 * viol
        p["comparison_score"] = round(adj, 4)
        enriched.append(p)
    enriched.sort(key=lambda x: (x.get("total_score", 0), x.get("comparison_score", 0)), reverse=True)
    return enriched
