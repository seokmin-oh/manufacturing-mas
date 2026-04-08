"""
SRA(Sense → Router → Reason → Act) LangGraph 워크플로.

에이전트 프로토콜 버전 `mas.sra.v2` — 노드 단위로 관측·라우팅·추론·행동을 분리해
추후 조건부 분기·휴먼 인 더 루프·체크포인트 확장이 가능하다.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from ..agents.base_agent import BaseAgent, AgentState
from ..intelligence.snapshot_enrichment import enrich_snapshot_for_router

LogFn = Callable[[str, str, str], None]


class SRAState(TypedDict, total=False):
    """직렬화 가능한 필드만 유지 (에이전트는 클로저로 전달)."""

    snapshot: Dict[str, Any]
    observations: Dict[str, Any]
    enriched: Dict[str, Any]
    decision: Optional[Dict[str, Any]]


def _build_graph(
    agent: BaseAgent,
    decision_router: Any,
    log_fn: Optional[LogFn],
    broker: Any,
):
    def node_sense(state: SRAState) -> Dict[str, Any]:
        snap = state["snapshot"]
        agent._snapshot = snap
        agent._cycle_count += 1
        agent.state = AgentState.SENSING
        observations = agent.sense(snap)
        if isinstance(observations, dict):
            alerts = observations.get("alerts") or []
            observations["new_alerts"] = list(alerts)
        return {"observations": observations}

    def node_enrich(state: SRAState) -> Dict[str, Any]:
        enriched = enrich_snapshot_for_router(state["snapshot"])
        return {"enriched": enriched}

    def node_router(state: SRAState) -> Dict[str, Any]:
        from .agent_protocol import _apply_think_result

        agent.state = AgentState.REASONING
        if not decision_router:
            return {}
        obs = state.get("observations") or {}
        enriched = state.get("enriched") or {}
        tr = decision_router.route(agent.agent_id, obs, enriched)
        if tr:
            _apply_think_result(tr, agent, log_fn, broker)
        return {}

    def node_reason(state: SRAState) -> Dict[str, Any]:
        observations = state.get("observations") or {}
        decision = agent.reason(observations)
        if decision:
            agent._decisions.append(decision)
            if len(agent._decisions) > 100:
                agent._decisions = agent._decisions[-100:]
        return {"decision": decision}

    def node_act(state: SRAState) -> Dict[str, Any]:
        agent.state = AgentState.ACTING
        agent.act(state.get("decision"))
        agent.state = AgentState.IDLE
        return {}

    workflow = StateGraph(SRAState)
    workflow.add_node("sense", node_sense)
    workflow.add_node("enrich", node_enrich)
    workflow.add_node("router", node_router)
    workflow.add_node("reason", node_reason)
    workflow.add_node("act", node_act)

    workflow.add_edge(START, "sense")
    workflow.add_edge("sense", "enrich")
    workflow.add_edge("enrich", "router")
    workflow.add_edge("router", "reason")
    workflow.add_edge("reason", "act")
    workflow.add_edge("act", END)

    return workflow.compile()


_graph_cache: Dict[Tuple[str, int, int, int], Any] = {}


def invoke_sra_graph(
    agent: BaseAgent,
    snapshot: Dict[str, Any],
    decision_router: Any = None,
    log_fn: Optional[LogFn] = None,
    broker: Any = None,
) -> Optional[Dict[str, Any]]:
    """LangGraph로 SRA 1사이클 실행. 최종 state 의 decision 반환.

    그래프는 (에이전트 ID, 라우터, 브로커, log_fn) 별로 캐시한다.
    log_fn 은 클로저에 묶이므로 id 가 다르면 별도 컴파일 그래프가 필요하다.
    """
    rid = id(decision_router) if decision_router is not None else 0
    bid = id(broker) if broker is not None else 0
    lid = id(log_fn) if log_fn is not None else 0
    key = (agent.agent_id, rid, bid, lid)

    if key not in _graph_cache:
        _graph_cache[key] = _build_graph(agent, decision_router, log_fn, broker)

    graph = _graph_cache[key]
    final: SRAState = graph.invoke({"snapshot": snapshot})
    return final.get("decision")


def clear_sra_graph_cache() -> None:
    """테스트용 — 브로커/라우터 교체 시 캐시 무효화."""
    _graph_cache.clear()
