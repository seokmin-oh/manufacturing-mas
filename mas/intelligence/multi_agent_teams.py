"""
상위 에이전트(EA~PA) 각각을 **내부 멀티 에이전트(전문 역할)** 로 분해한 정의.

실제 구현은 단일 Python 클래스 안에서 메서드/모듈로 나뉠 수 있으나,
운영·문서·모니터링에서는 “한 역할 = 여러 전문가 팀”으로 보는 것이 설계·확장에 유리하다.

런타임에서 별도 프로세스로 쪼개지 않아도, 책임 경계와 추후 마이크로서비스 분리의 기준선이 된다.
"""

from __future__ import annotations

from typing import Any, Dict, List

# 각 키: 상위 에이전트 ID — 값: 하위 전문 역할 목록
MULTI_AGENT_TEAMS: Dict[str, List[Dict[str, Any]]] = {
    "EA": [
        {"id": "EA-PdM-VIB", "name": "진동·베어링", "focus": "스펙트럼·이상점수·트렌드"},
        {"id": "EA-PdM-HYD", "name": "유압·윤활", "focus": "유온·압력·누유 패턴"},
        {"id": "EA-PdM-TOOL", "name": "공구·금형", "focus": "마모 구간·교체 타이밍"},
        {"id": "EA-LINE", "name": "라인 조율", "focus": "WC 간 우선순위·감속 연계"},
    ],
    "QA": [
        {"id": "QA-SPC", "name": "SPC·관리도", "focus": "Cpk·한계 이탈"},
        {"id": "QA-RULE", "name": "런 규칙", "focus": "Western Electric류 패턴"},
        {"id": "QA-CORR", "name": "공정 상관", "focus": "WC 간 품질 전파"},
        {"id": "QA-ALERT", "name": "경보 라우팅", "focus": "PA·EA 알림 조건"},
    ],
    "SA": [
        {"id": "SA-ROP", "name": "ROP·안전재고", "focus": "재주문점·일수분"},
        {"id": "SA-SUP", "name": "공급사", "focus": "리드타임·신뢰도"},
        {"id": "SA-SHOR", "name": "부족 예측", "focus": "소모율·입고 이벤트"},
    ],
    "DA": [
        {"id": "DA-ORD", "name": "주문·납기", "focus": "잔량·우선순위"},
        {"id": "DA-SURGE", "name": "수요 변동", "focus": "긴급·배치 변화"},
        {"id": "DA-FCS", "name": "예측 보정", "focus": "단기 수요 힌트(시뮬)"},
    ],
    "IA": [
        {"id": "IA-WIP", "name": "WIP·버퍼", "focus": "구간별 적체"},
        {"id": "IA-FG", "name": "완제품", "focus": "FG·출하 압력"},
        {"id": "IA-BN", "name": "병목 힌트", "focus": "OEE·흐름 연계"},
    ],
    "PA": [
        {"id": "PA-ORCH", "name": "오케스트레이션", "focus": "전역 KPI·속도 레버"},
        {"id": "PA-CNP", "name": "CNP 사무국", "focus": "CFP·제안·솔버"},
        {"id": "PA-LLM", "name": "서술·상황", "focus": "근거 문장·복합경보(선택)"},
        {"id": "PA-POL", "name": "정책·한계", "focus": "규칙·안전 상한"},
    ],
}


def build_multi_agent_teams_payload() -> Dict[str, Any]:
    return {
        "summary": (
            "각 상위 에이전트(EA~PA)는 단일 if문이 아니라, **내부 전문 역할(서브 에이전트)** 의 합으로 본다. "
            "현재 코드는 대부분 한 클래스·모듈에 구현되어 있으나, 책임은 아래와 같이 분리해 확장한다."
        ),
        "teams": {k: list(v) for k, v in MULTI_AGENT_TEAMS.items()},
    }
