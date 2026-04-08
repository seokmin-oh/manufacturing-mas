"""
제조 MAS 제어·판단 스택 — 문서/모니터링/API 공통 표.

실제 현장에 가깝게: OT(센서·인터록) → 규칙·수치 → 에이전트 → 오케스트레이터 →
(선택) LLM 서술·상황분석. LLM은 직접 설비를 움직이지 않고 로그/권고 중심.
"""

from __future__ import annotations

from typing import Any, Dict, List

# 계층 (IEC 62264 / 스마트팩토리에서 흔히 쓰는 개념과 유사)
CONTROL_LAYERS: List[Dict[str, str]] = [
    {
        "layer": "L0",
        "name": "필드 · 센서/액추에이터(시뮬)",
        "mechanism": "Factory.run_cycle, Station 센서·상태 머신",
        "latency": "< 100ms급(시뮬 택트)",
        "llm_role": "없음",
    },
    {
        "layer": "L1",
        "name": "안전 · 인터록",
        "mechanism": "HybridDecisionRouter 안전 규칙(진동·유온 비상)",
        "latency": "즉시",
        "llm_role": "없음 (지연 불가)",
    },
    {
        "layer": "L2",
        "name": "임계·SPC·ROP",
        "mechanism": "에이전트별 임계 규칙(EA·SA 등), 도메인 점수",
        "latency": "즉시~수백ms",
        "llm_role": "없음",
    },
    {
        "layer": "L3",
        "name": "멀티 에이전트 협업",
        "mechanism": "브로커 Pub/Sub, CNP(제안·솔버 점수)",
        "latency": "택트 단위",
        "llm_role": "CNP 후 근거 서술(선택, PA·솔버 고정)",
    },
    {
        "layer": "L4",
        "name": "관측 · 감사",
        "mechanism": "REST/SSE, 대시보드, KPI",
        "latency": "비동기",
        "llm_role": "없음",
    },
]

# 에이전트별 역할 (LLM은 ‘보조’ 열로 고정)
AGENT_ROLES: List[Dict[str, str]] = [
    {
        "id": "EA",
        "name": "설비",
        "primary": "예지·진동/유온 임계, 설비 상태",
        "llm_aux": "라우터 범위가 all_gated 이고 보조 활성 시 복합 경보 상황분석 후보",
    },
    {
        "id": "QA",
        "name": "품질",
        "primary": "SPC·불량·관리도",
        "llm_aux": "동일 (고심각도+복합 경보 시)",
    },
    {
        "id": "SA",
        "name": "자재",
        "primary": "버퍼·ROP·보충",
        "llm_aux": "동일",
    },
    {
        "id": "DA",
        "name": "수요",
        "primary": "수요·납기",
        "llm_aux": "동일",
    },
    {
        "id": "IA",
        "name": "재고",
        "primary": "WIP·병목",
        "llm_aux": "동일",
    },
    {
        "id": "PA",
        "name": "계획",
        "primary": "OEE·CNP 주관·전역 조율",
        "llm_aux": "① CNP 근거 서술 ② 복합경보 시 analyze_situation (라우터)",
    },
]

LLM_PATHS: List[Dict[str, str]] = [
    {
        "path": "A",
        "entry": "PlanningAgent._build_strategy_llm",
        "api": "LLMClient.evaluate_proposals / rationalize_cnp_decision",
        "when": "CNP 제안 수집 후 솔버가 수치 확정",
        "effect": "수치 변경 없음, 근거·리스크 문장만",
    },
    {
        "path": "B",
        "entry": "HybridDecisionRouter._route_to_llm",
        "api": "LLMClient.analyze_situation",
        "when": "라우터 정책·경보 복잡도 충족 시",
        "effect": "로그·권고 JSON, 설비 직접 명령 아님",
    },
]


def build_control_payload(settings: Any) -> Dict[str, Any]:
    """Settings 와 결합해 모니터링/대시보드용 페이로드."""
    scope = getattr(settings, "llm_router_scope", "pa_only")
    assist = getattr(settings, "llm_per_agent_assist", False)
    return {
        "control_layers": CONTROL_LAYERS,
        "agent_roles": AGENT_ROLES,
        "llm_paths": LLM_PATHS,
        "runtime_policy": {
            "llm_router_scope": scope,
            "llm_per_agent_assist": assist,
            "router_summary": _router_summary(scope, assist),
        },
    }


def _router_summary(scope: str, assist: bool) -> str:
    if scope == "pa_only":
        return (
            "라우터의 analyze_situation 은 PA 틱에서만 후보. "
            "CNP 근거 LLM은 별도(PlanningAgent)."
        )
    if scope == "all_gated":
        if assist:
            return (
                "비 PA 에이전트도 고심각·복합 경보 시에만 동일 LLM 경로 후보. "
                "기본은 규칙·솔버 우선."
            )
        return (
            "all_gated 이지만 per_agent_assist=0 이므로 라우터 LLM 후보는 PA 와 동일 조건."
        )
    return f"llm_router_scope={scope}"
