"""
Agentic Loop — Sense-Think-Act 자율 실행 엔진
==============================================
순수 Python `AgentExecutor` 자율 루프(도구·MQTT).
SRA+라우터 통합은 `agent_protocol` + 선택적 LangGraph(`sra_langgraph`)를 사용한다.
각 에이전트가 백그라운드 스레드에서 무한 반복:

  ┌─── Sense ───┐     ┌─── Think ───┐     ┌─── Act ────┐
  │ MQTT/Broker  │ ──> │ Rule + LLM  │ ──> │ Tool Call  │
  │ 환경 스냅샷  │     │ 판단 + 계획 │     │ 메시지 전송│
  │ 수신 메시지  │     │ Tool 선택   │     │ 상태 갱신  │
  └──────────────┘     └─────────────┘     └────────────┘

핵심 개념:
  - AgenticStep: 하나의 Sense-Think-Act 사이클
  - ThinkResult: Think 단계의 출력 (actions 리스트)
  - Action: Tool 호출, 메시지 전송, 상태 갱신 등
  - AgentExecutor: 에이전트별 자율 루프 실행기
"""

import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable

from ..messaging.message import AgentMessage, Intent


class ActionType(Enum):
    TOOL_CALL = "tool_call"
    SEND_MESSAGE = "send_message"
    UPDATE_STATE = "update_state"
    LOG = "log"
    NOOP = "noop"


@dataclass
class Action:
    """에이전트가 실행할 단일 행동."""
    type: ActionType
    tool_name: str = ""
    tool_kwargs: dict = field(default_factory=dict)
    message: Optional[AgentMessage] = None
    state_update: dict = field(default_factory=dict)
    log_msg: str = ""
    log_level: str = "INFO"


@dataclass
class ThinkResult:
    """Think 단계의 출력."""
    actions: List[Action]
    reasoning: str = ""
    decision_source: str = "rule"  # "rule" or "llm"


@dataclass
class AgenticStep:
    """하나의 Sense-Think-Act 사이클 기록."""
    agent_id: str
    cycle: int
    timestamp: float
    sensed: dict = field(default_factory=dict)
    think_result: Optional[ThinkResult] = None
    act_results: List[dict] = field(default_factory=list)
    duration_ms: float = 0.0


class AgentExecutor:
    """
    에이전트 자율 실행 엔진.
    Tool Registry와 Decision Router를 주입받아
    에이전트의 SRA 루프를 자율적으로 실행한다.
    """

    def __init__(self, agent, tool_registry=None, decision_router=None,
                 mqtt=None, runtime_log=None):
        self.agent = agent
        self.tool_registry = tool_registry
        self.decision_router = decision_router
        self.mqtt = mqtt
        self._runtime_log = runtime_log
        self._cycle = 0
        self._step_history: List[AgenticStep] = []
        self._lock = threading.Lock()

    def execute_cycle(self, env_snapshot: dict) -> AgenticStep:
        """한 번의 Sense-Think-Act 사이클 실행."""
        t0 = time.perf_counter()
        self._cycle += 1

        step = AgenticStep(
            agent_id=self.agent.agent_id,
            cycle=self._cycle,
            timestamp=time.time(),
        )

        # ── SENSE ─────────────────────────────────────
        step.sensed = self._sense(env_snapshot)

        # ── THINK ─────────────────────────────────────
        step.think_result = self._think(step.sensed, env_snapshot)

        # ── ACT ───────────────────────────────────────
        if step.think_result:
            step.act_results = self._act(step.think_result, env_snapshot)

        step.duration_ms = (time.perf_counter() - t0) * 1000

        with self._lock:
            self._step_history.append(step)
            if len(self._step_history) > 100:
                self._step_history = self._step_history[-50:]

        return step

    def _sense(self, env_snapshot: dict) -> dict:
        """Sense: 환경 + 수신 메시지 감지."""
        sensed = self.agent.sense(env_snapshot)

        inbox_msgs = self.agent.pop_inbox()
        if inbox_msgs:
            sensed["inbox_messages"] = [
                {"sender": m.header.sender, "intent": m.intent.value,
                 "summary": m.body.get("summary", "")}
                for m in inbox_msgs
            ]

        return sensed

    def _think(self, sensed: dict, env_snapshot: dict) -> ThinkResult:
        """Think: 판단 + 도구 선택 + 행동 계획."""
        actions = []
        reasoning = ""
        source = "rule"

        aid = self.agent.agent_id

        if self.decision_router:
            routed = self.decision_router.route(aid, sensed, env_snapshot)
            if routed:
                return routed

        decision = self.agent.reason(sensed)
        action_name = decision.get("action", "none")
        reasoning = f"{aid} decision: {action_name}"

        if action_name == "alert_pa" or action_name == "request_material":
            act_result = self.agent.act(decision)
            if act_result.get("sent_alert"):
                actions.append(Action(type=ActionType.LOG,
                                      log_msg=f"Alert sent to PA", log_level="ALERT"))

        elif action_name not in ("none", "monitor"):
            self.agent.act(decision)
            actions.append(Action(type=ActionType.LOG,
                                  log_msg=f"Action: {action_name}", log_level="INFO"))

        # 에이전트별 도구 호출 결정
        tool_actions = self._select_tools(aid, sensed, env_snapshot)
        actions.extend(tool_actions)

        if not actions:
            actions.append(Action(type=ActionType.NOOP))

        return ThinkResult(actions=actions, reasoning=reasoning, decision_source=source)

    def _select_tools(self, aid: str, sensed: dict, snap: dict) -> List[Action]:
        """에이전트별 도구 호출 자동 선택."""
        actions = []

        if not self.tool_registry:
            return actions

        if aid == "EA":
            vib = snap.get("vibration", 0)
            slope = snap.get("vibration_slope", 0)
            if vib > 3.0 or slope > 0.05:
                actions.append(Action(
                    type=ActionType.TOOL_CALL,
                    tool_name="predictive_maintenance",
                    tool_kwargs={"vibration": vib, "trend_slope": slope},
                ))
                actions.append(Action(
                    type=ActionType.TOOL_CALL,
                    tool_name="capacity_estimation",
                    tool_kwargs={"vibration": vib, "vib_slope": slope,
                                 "speed_pct": snap.get("line_speed_pct", 100)},
                ))

        elif aid == "QA":
            vib = snap.get("vibration", 0)
            oil = snap.get("oil_temp", 42)
            slope = snap.get("vibration_slope", 0)
            if self.agent.internal_state.get("inspected", 0) > 5:
                burr_mean = self.agent.get_recent_mean("burr_height", 5) if hasattr(self.agent, 'get_recent_mean') else 0.03
                actions.append(Action(
                    type=ActionType.TOOL_CALL,
                    tool_name="defect_prediction",
                    tool_kwargs={"vibration": vib, "oil_temp": oil,
                                 "vibration_trend_slope": slope,
                                 "recent_burr_mean": burr_mean},
                ))

        elif aid == "DA":
            demand_data = snap.get("demand", {})
            history = demand_data.get("demand_history", [])
            if len(history) >= 5:
                actions.append(Action(
                    type=ActionType.TOOL_CALL,
                    tool_name="demand_forecast",
                    tool_kwargs={"demand_history": history[-20:], "horizon": 10},
                ))

        elif aid == "IA":
            wh = snap.get("warehouse", {})
            stock = wh.get("stock", 0)
            ss = wh.get("safety_stock", 0)
            if stock < ss * 1.5:
                actions.append(Action(
                    type=ActionType.TOOL_CALL,
                    tool_name="safety_stock_calc",
                    tool_kwargs={
                        "z_score": 1.645,
                        "leadtime_mean": wh.get("leadtime_mean", 4.5),
                        "demand_std": wh.get("demand_std", 3.0),
                        "avg_demand": wh.get("avg_demand_per_cycle", 4.0),
                        "leadtime_std": wh.get("leadtime_std", 1.0),
                    },
                ))

        return actions

    def _act(self, think_result: ThinkResult, env_snapshot: dict) -> List[dict]:
        """Act: 도구 호출 + 메시지 전송 + 상태 갱신 실행."""
        results = []

        for action in think_result.actions:
            if action.type == ActionType.TOOL_CALL and self.tool_registry:
                tool_result = self.tool_registry.call(action.tool_name, **action.tool_kwargs)
                results.append(tool_result)

                if self.mqtt and tool_result.get("status") == "ok":
                    self.mqtt.publish_tool_call(
                        self.agent.agent_id, action.tool_name, tool_result)

                if self._runtime_log:
                    status = tool_result.get("status", "?")
                    lat = tool_result.get("latency_ms", 0)
                    self._runtime_log(
                        self.agent.agent_id,
                        f"Tool:{action.tool_name} [{status}] {lat:.1f}ms",
                        "TOOL"
                    )

            elif action.type == ActionType.SEND_MESSAGE and action.message:
                self.agent.send_message(action.message)
                results.append({"type": "message_sent", "receiver": action.message.header.receiver})

            elif action.type == ActionType.UPDATE_STATE:
                with self.agent._lock:
                    self.agent.internal_state.update(action.state_update)
                results.append({"type": "state_updated", "keys": list(action.state_update.keys())})

            elif action.type == ActionType.LOG:
                if self._runtime_log:
                    self._runtime_log(self.agent.agent_id, action.log_msg, action.log_level)
                results.append({"type": "logged"})

        return results

    @property
    def stats(self) -> dict:
        with self._lock:
            total = len(self._step_history)
            tool_calls = sum(
                1 for s in self._step_history
                if s.think_result
                for a in s.think_result.actions
                if a.type == ActionType.TOOL_CALL
            )
            avg_dur = (
                sum(s.duration_ms for s in self._step_history) / total
                if total else 0
            )
        return {
            "agent_id": self.agent.agent_id,
            "total_cycles": self._cycle,
            "tool_calls": tool_calls,
            "avg_cycle_ms": round(avg_dur, 2),
        }
