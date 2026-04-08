"""
운영 의사결정 카드 — 알람이 아닌 추천·대응안 중심 출력 스키마.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ResponseOption:
    label: str
    expected_benefit: str
    risk: str


@dataclass
class OperationalDecisionCard:
    schema: str
    issue_title: str
    targets: Dict[str, str]
    severity: str
    impact_scope: str
    priority_rank: int
    responses: List[ResponseOption]
    constraints: List[str]
    immediate_checks: List[str]
    owner_role: str
    review_at: str
    evidence_refs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["responses"] = [asdict(r) for r in self.responses]
        return d


def empty_card(reason: str = "no_data") -> Dict[str, Any]:
    return {
        "schema": "operational_decision_card/v1",
        "issue_title": reason,
        "targets": {},
        "severity": "INFO",
        "impact_scope": "",
        "priority_rank": 0,
        "responses": [],
        "constraints": [],
        "immediate_checks": [],
        "owner_role": "PA",
        "review_at": "",
        "evidence_refs": {},
    }


def from_cnp_strategy(
    situation: str,
    proposals: List[Dict[str, Any]],
    strategy: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """CNP 최우선 제안·전략으로 운영 의사결정 카드 JSON 생성."""
    if not proposals:
        return empty_card("no_proposals")
    best = proposals[0]
    comp = best.get("comparison") or {}
    mctx = snapshot.get("manufacturing_context") if isinstance(snapshot, dict) else {}
    ids = (mctx.get("identifiers") if isinstance(mctx, dict) else {}) or {}
    targets = {
        "site_id": ids.get("site_id", ""),
        "line_id": ids.get("line_id", ""),
        "shift": str(snapshot.get("shift", "") if isinstance(snapshot, dict) else ""),
    }
    resp_opts = [
        {
            "label": f"{best.get('agent', '?')} 제안",
            "expected_benefit": f"효과지수 {comp.get('expected_effect', '-')}",
            "risk": f"품질리스크 {comp.get('quality_risk', '-')}",
        }
    ]
    for i, p in enumerate(proposals[1:3], start=2):
        c2 = p.get("comparison") or {}
        resp_opts.append(
            {
                "label": f"대안{i}: {p.get('agent', '?')}",
                "expected_benefit": f"효과 {c2.get('expected_effect', '-')}",
                "risk": f"비용 {c2.get('expected_cost', '-')}",
            }
        )
    card = OperationalDecisionCard(
        schema="operational_decision_card/v1",
        issue_title=situation[:120] if situation else "CNP 협상",
        targets=targets,
        severity="HIGH",
        impact_scope=f"OEE·품질·납기 (제안 {len(proposals)}건)",
        priority_rank=1,
        responses=[ResponseOption(**r) for r in resp_opts],
        constraints=[
            f"속도 {strategy.get('target_speed_pct', '-')}%",
            f"검사 {strategy.get('inspection_mode', '-')}",
        ],
        immediate_checks=["최우선 제안 comparison 필드 확인", "라인 속도 한계"],
        owner_role="PA",
        review_at=f"cycle+10",
        evidence_refs={"cnp_id": strategy.get("cnp_id"), "best_agent": best.get("agent")},
    )
    return card.to_dict()
