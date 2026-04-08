"""
멀티에이전트 구성 요약 — 모니터링 대시보드용 (역할·협업 메커니즘을 한 화면에서 읽기 쉽게).
registry / teams 정의와 문장만 맞추면 된다.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .agent_domain_registry import AGENT_FACTORY_COVERAGE
from .multi_agent_teams import MULTI_AGENT_TEAMS


def build_mas_overview_payload() -> Dict[str, Any]:
    """대시보드 `mas_overview` 섹션."""
    roles: List[Dict[str, str]] = []
    for a in AGENT_FACTORY_COVERAGE:
        subs = MULTI_AGENT_TEAMS.get(a["id"], [])
        roles.append(
            {
                "id": a["id"],
                "name": a["name"],
                "one_liner": _one_liner(a),
                "collab": a.get("coordination") or "",
                "sub_count": len(subs),
            }
        )

    return {
        "headline": "6개 상위 에이전트 + 내부 전문 역할",
        "lead": (
            "같은 공장 스냅샷과 메시지 브로커 위에서 동작합니다. "
            "계획(PA)이 전역 조율·CNP 협상을 맡고, "
            "설비·품질·자재·수요·재고(EA·QA·SA·DA·IA)가 각각 도메인 신호를 올린 뒤 "
            "PA와 브로커 메시지로 맞춥니다. "
            "각 상위 에이전트는 내부 전문 역할(서브)로 쪼개어 확장할 수 있게 정의되어 있습니다."
        ),
        "roles": roles,
        "collaboration": {
            "title": "협업이 도는 방식",
            "points": [
                {
                    "t": "메시지",
                    "d": "에이전트 간 통신은 브로커(Pub/Sub)로 전달되며, 대시보드의 메시지 스트림·협업 맵이 같은 흐름을 보여 줍니다.",
                },
                {
                    "t": "허브",
                    "d": "대부분의 ‘보고·제안’은 주변 역할 → PA, ‘지시·조정’은 PA → 주변 역할 방향으로 모델링되어 있습니다.",
                },
                {
                    "t": "CNP",
                    "d": "계획(PA)이 Contract Net Protocol로 CFP·제안·평가를 열어 속도·납기 등 전략을 합의합니다.",
                },
                {
                    "t": "교차",
                    "d": "설비↔품질, 수요↔재고, 자재↔재고 등은 도메인끼리 직접 연계되는 협업으로 따로 표시합니다.",
                },
            ],
        },
        "implementation_note": (
            "구현은 상위 에이전트당 주로 하나의 Python 클래스 안에서 이루어지며, "
            "위 서브 역할은 책임 분리·추후 마이크로서비스 분리를 위한 논리적 팀 단위입니다."
        ),
    }


def _one_liner(a: Dict[str, Any]) -> str:
    """담당 영역 + 지능 계층 한 줄."""
    areas = a.get("areas") or []
    short_areas = " · ".join(areas[:2]) if areas else ""
    intel = (a.get("intelligence") or "").strip()
    if len(intel) > 72:
        intel = intel[:69] + "…"
    if short_areas and intel:
        return f"담당 {short_areas} — {intel}"
    return intel or short_areas or ((a.get("primary_data") or "")[:80])
