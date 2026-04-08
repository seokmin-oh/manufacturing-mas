"""
CNP 대안 비교 스키마 — 전략 문장이 아니라 운영 의사결정용 수치 축.

LLM은 이 필드를 **채우지 않고** 해석·설명만 담당 (수치는 솔버·에이전트).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

CNP_COMPARISON_SCHEMA_VERSION = "1.0"

# 제안 dict에 권장 키 (누락 시 폴백 0 또는 None)
COMPARISON_KEYS = (
    "candidate_action",  # str: 추천 후보 액션 요약
    "expected_effect",  # float 0~1: 기대 효과 정규화
    "expected_cost",  # float 0~1: 예상 비용(정규화, 낮을수록 유리)
    "quality_risk",  # float 0~1: 품질 리스크
    "delivery_impact",  # float -1~1: 납기 영향 (음수=유리)
    "material_impact",  # float 0~1: 자재 영향 부담
    "constraint_violation",  # float 0~1: 제약 위반량
    "confidence",  # float 0~1: 추천 신뢰도
)


def normalize_comparison_metrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    """proposal_metrics / comparison 블록을 표준 키로 정규화."""
    pm = raw.get("proposal_metrics") if isinstance(raw, dict) else {}
    if not isinstance(pm, dict):
        pm = {}
    comp = raw.get("comparison") if isinstance(raw.get("comparison"), dict) else {}
    merged = {**pm, **comp}

    def _f(x: Any, default: float = 0.0) -> float:
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    out = {
        "candidate_action": str(
            merged.get("candidate_action")
            or raw.get("proposal")
            or merged.get("action")
            or "unspecified"
        ),
        "expected_effect": _f(merged.get("expected_effect") or merged.get("expected_benefit"), 0.5),
        "expected_cost": _f(
            merged.get("expected_cost") or merged.get("cost_estimate") or merged.get("cost_estimate_norm"),
            0.5,
        ),
        "quality_risk": _f(merged.get("quality_risk"), 0.3),
        "delivery_impact": _f(merged.get("delivery_impact"), 0.0),
        "material_impact": _f(merged.get("material_impact"), 0.2),
        "constraint_violation": _f(
            merged.get("constraint_violation") or merged.get("constraint_violation_total"),
            0.0,
        ),
        "confidence": _f(merged.get("confidence") or merged.get("recommendation_confidence"), 0.7),
        "schema_version": CNP_COMPARISON_SCHEMA_VERSION,
    }
    return out


def merge_into_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """제안 dict에 `comparison` 표준 블록을 병합 (원본 변경)."""
    if not isinstance(proposal, dict):
        return proposal
    comp = normalize_comparison_metrics(proposal)
    proposal["comparison"] = comp
    return proposal
