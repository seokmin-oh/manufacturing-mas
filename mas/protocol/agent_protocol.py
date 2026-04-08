"""
에이전트 SRA 루프와 HybridDecisionRouter 통합
=============================================

## 순서 (순차 폴백 기준)
1. **Sense** — `agent.sense(snapshot)`
2. **스냅샷 보강** — `enrich_snapshot_for_router` 로 라우터가 쓸 파생 지표 추가
3. **Router(선택)** — `decision_router.route` 가 LOG / SEND_MESSAGE 등 **ThinkResult** 를 먼저 적용 가능
4. **Reason** — `agent.reason(observations)`; `observations["new_alerts"]` 로 PA 쪽 조건 충족
5. **Act** — `agent.act(decision)`

`BaseAgent.run_cycle` 과 달리 **라우터가 Reason 앞에 온다**는 점이 핵심.

## LangGraph
기본은 `mas/protocol/sra_langgraph.py` 그래프.
환경변수 `MAS_USE_LANGGRAPH=0` 이거나 패키지 미설치 시 `_run_sra_sequential` 로 동일 의미 폴백.
"""


from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger(__name__)

from .agentic_loop import ActionType, ThinkResult
from ..agents.base_agent import BaseAgent, AgentState
from ..domain.agent_snapshot import enrich_snapshot_for_agents
from ..intelligence.snapshot_enrichment import enrich_snapshot_for_router

AGENT_PROTOCOL_ID = "mas.sra.v2"

LogFn = Callable[[str, str, str], None]


def _apply_think_result(
    tr: ThinkResult,
    agent: BaseAgent,
    log_fn: Optional[LogFn],
    broker: Any,
) -> None:
    """라우터가 반환한 액션 목록을 실행: 터미널 로그 또는 브로커 메시지 전송."""

    for action in tr.actions:
        if action.type == ActionType.LOG and action.log_msg:
            if log_fn:
                log_fn(agent.agent_id, action.log_msg, action.log_level or "INFO")
        elif action.type == ActionType.SEND_MESSAGE and action.message and broker:
            try:
                broker.deliver(action.message)
            except Exception as e:
                _log.debug("라우터 메시지 전달 실패: %s", e)


def _use_langgraph() -> bool:
    v = os.environ.get("MAS_USE_LANGGRAPH", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _run_sra_sequential(
    agent: BaseAgent,
    snapshot: Dict[str, Any],
    decision_router: Any = None,
    log_fn: Optional[LogFn] = None,
    broker: Any = None,
) -> Optional[Dict[str, Any]]:
    """LangGraph 없이 위 문서 순서대로 S+R+A 수행. 그래프 실패 시에도 이 경로로 수렴."""

    snapshot = enrich_snapshot_for_agents(dict(snapshot))
    agent._snapshot = snapshot
    agent._cycle_count += 1

    agent.state = AgentState.SENSING
    observations = agent.sense(snapshot)

    if isinstance(observations, dict):
        alerts = observations.get("alerts") or []
        observations["new_alerts"] = list(alerts)

    enriched = enrich_snapshot_for_router(snapshot)

    agent.state = AgentState.REASONING
    if decision_router:
        tr = decision_router.route(agent.agent_id, observations, enriched)
        if tr:
            _apply_think_result(tr, agent, log_fn, broker)

    decision = agent.reason(observations)
    if decision:
        agent._decisions.append(decision)
        if len(agent._decisions) > 100:
            agent._decisions = agent._decisions[-100:]

    agent.state = AgentState.ACTING
    agent.act(decision)
    agent.state = AgentState.IDLE
    return decision


def run_cycle_with_router(
    agent: BaseAgent,
    snapshot: Dict[str, Any],
    decision_router: Any = None,
    log_fn: Optional[LogFn] = None,
    broker: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Sense → (Router 선행 판단) → Reason → Act.
    observations 에 new_alerts 를 넣어 PA용 LLM 라우트 조건을 만족시킨다.

    LangGraph 그래프: sense → enrich → router → reason → act (`AGENT_PROTOCOL_ID`).
    """
    if _use_langgraph():
        try:
            from .sra_langgraph import invoke_sra_graph

            return invoke_sra_graph(
                agent, snapshot, decision_router, log_fn, broker
            )
        except ImportError:
            pass
        except Exception as e:
            _log.warning(
                "LangGraph SRA 실패 — 순차 SRA로 폴백 (%s: %s)",
                agent.agent_id,
                e,
                exc_info=_log.isEnabledFor(logging.DEBUG),
            )
    return _run_sra_sequential(
        agent, snapshot, decision_router, log_fn, broker
    )
