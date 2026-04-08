"""
전 공장 에이전트 커버리지 — 예지보전(EA)만이 아니라 품질·자재·수요·재고·계획까지
역할·데이터 소스·판단 계층을 한 표로 고정 (모니터링·문서·API 공통).

실제 현장: OT 센서·MES·ERP·WMS와 연동 시에도 동일 6역할 매핑을 유지하기 쉽다.
"""

from __future__ import annotations

from typing import Any, Dict, List


# 공장 영역 태그 (스냅샷 키와 대응)
FACTORY_AREAS = {
    "line": "6공정 라인 (WC-01~06)",
    "materials": "원자재·소모품",
    "orders": "고객 주문·납기",
    "wip": "WIP 버퍼",
    "fg": "완제품·출하",
    "energy": "공정 에너지",
    "events": "랜덤 이벤트(고장·주문 등)",
}


AGENT_FACTORY_COVERAGE: List[Dict[str, Any]] = [
    {
        "id": "EA",
        "name": "설비",
        "areas": [FACTORY_AREAS["line"], FACTORY_AREAS["events"]],
        "primary_data": "stations[*].sensors, 상태·OEE·MTBF/MTTR·공구",
        "intelligence": "유형별 예지 패키지(PRESS/WELD/HEAT/CNC/ASSY) + 이상·RUL 휴리스틱",
        "coordination": "PA·CNP에 설비 제약·속도 제안",
    },
    {
        "id": "QA",
        "name": "품질",
        "areas": [FACTORY_AREAS["line"], FACTORY_AREAS["fg"]],
        "primary_data": "측정 이력·Cpk·관리도 한계·불량 로그",
        "intelligence": "SPC·런 규칙·공정 간 상관(시뮬)",
        "coordination": "불량·드리프트 시 PA 알림",
    },
    {
        "id": "SA",
        "name": "자재",
        "areas": [FACTORY_AREAS["materials"]],
        "primary_data": "materials[*] 재고·ROP·리드타임·공급자",
        "intelligence": "소모 예측·발주 필요 판단",
        "coordination": "부족 시 PA·생산 알림",
    },
    {
        "id": "DA",
        "name": "수요",
        "areas": [FACTORY_AREAS["orders"]],
        "primary_data": "orders[*] 수량·납기·우선순위",
        "intelligence": "수요 변동·긴급 주문 감지",
        "coordination": "납기 압력을 PA·IA에 반영",
    },
    {
        "id": "IA",
        "name": "재고",
        "areas": [FACTORY_AREAS["wip"], FACTORY_AREAS["fg"]],
        "primary_data": "WIP 버퍼·완제품 재고·병목 힌트",
        "intelligence": "흐름·재고 수준 평가",
        "coordination": "PA와 물량·속도 협의",
    },
    {
        "id": "PA",
        "name": "계획",
        "areas": [
            FACTORY_AREAS["line"],
            FACTORY_AREAS["orders"],
            FACTORY_AREAS["materials"],
            FACTORY_AREAS["fg"],
        ],
        "primary_data": "전역 스냅샷·에이전트 알림·CNP 제안",
        "intelligence": "규칙 기반 CNP + (선택) LLM 근거·상황 분석",
        "coordination": "CFP·전략·라인 속도 최종 조정",
    },
]


def build_factory_coverage_payload() -> Dict[str, Any]:
    return {
        "summary": (
            "공장은 단일 예지보전 모델이 아니라, 설비·품질·자재·수요·재고·계획 **6역할**로 분할되어 "
            "동일 스냅샷·브로커 위에서 협업한다. EA는 **라인 자산**, PA는 **전역 오케스트레이션**."
        ),
        "areas_reference": FACTORY_AREAS,
        "agents": AGENT_FACTORY_COVERAGE,
    }
