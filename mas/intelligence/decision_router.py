"""
Hybrid Decision Router — Rule-based vs LLM 판단 분기
=====================================================
제조 현장의 두 가지 판단 영역을 명확히 분리:

┌─────────────────────────────────────────────────────────┐
│                  Decision Router                         │
├────────────────────────┬────────────────────────────────┤
│   Hard-coded Rules     │        LLM (GPT)               │
│   (실시간, < 10ms)     │    (전략적, ~1-3s)             │
├────────────────────────┼────────────────────────────────┤
│ • 설비 안전 인터록     │ • 공정 간 이해관계 충돌 조정  │
│ • 진동 임계값 알람     │ • 예상치 못한 알람 원인 분석  │
│ • SPC 관리도 이탈      │ • 최적 감속률 결정            │
│ • 재고 부족 즉시 알람  │ • 복합 이벤트 대안 수립       │
│ • AGV 충돌 방지        │ • 수요-공급-품질 트레이드오프 │
│ • 라인 속도 상/하한    │ • CNP 전략 종합 평가          │
│ • 자재 소진 경고       │ • 안전재고 동적 최적화 판단   │
│ • 센서 이상치 필터링   │ • 고객 납기 조정 협상 전략    │
└────────────────────────┴────────────────────────────────┘

라우팅 로직:
  1. 안전 관련 → 무조건 Rule (지연 불가)
  2. 단일 지표 임계값 → Rule
  3. 복합 판단 (2개+ 에이전트 관련) → LLM
  4. 전략적 최적화 → LLM
  5. LLM 실패 → Rule 폴백

## 코드에서의 위치
`run_cycle_with_router` / LangGraph SRA 그래프가 에이전트 **Reason 직전**에 `route()` 호출.
설정: `MAS_LLM_ROUTER_SCOPE`, `MAS_LLM_PER_AGENT_ASSIST` (`mas/core/config.py`).
"""

import time

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..protocol.agentic_loop import ThinkResult, Action, ActionType
from ..messaging.message import AgentMessage, Intent


# ── 하드코딩 규칙 임계값 ──────────────────────────────────────────

RULES = {
    "vibration_emergency": 5.5,     # 즉시 정지
    "vibration_critical": 4.5,      # 긴급 감속
    "vibration_warning": 3.5,       # 경고
    "oil_temp_critical": 75.0,      # 유온 위험
    "oil_temp_warning": 60.0,       # 유온 경고
    "speed_min": 40,                # 최저 라인 속도
    "speed_max": 100,               # 최대 라인 속도
    "cpk_critical": 0.67,           # SPC 위험
    "cpk_warning": 1.0,             # SPC 경고
    "sl_critical": 0.90,            # 서비스레벨 위험
    "material_buffer_critical_h": 1.0,
    "material_buffer_warning_h": 3.0,
}


@dataclass
class DecisionRecord:
    timestamp: float
    agent_id: str
    route: str          # "rule" or "llm"
    rule_name: str = ""
    reasoning: str = ""
    latency_ms: float = 0.0


@dataclass
class RouterMetrics:
    rule_decisions: int = 0
    llm_decisions: int = 0
    llm_fallbacks: int = 0
    total_latency_ms: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, route: str, latency_ms: float):
        with self._lock:
            if route == "rule":
                self.rule_decisions += 1
            elif route == "llm":
                self.llm_decisions += 1
            self.total_latency_ms += latency_ms

    def to_dict(self) -> dict:
        total = self.rule_decisions + self.llm_decisions
        return {
            "rule_decisions": self.rule_decisions,
            "llm_decisions": self.llm_decisions,
            "llm_fallbacks": self.llm_fallbacks,
            "total_decisions": total,
            "rule_pct": round(self.rule_decisions / max(total, 1) * 100, 1),
            "llm_pct": round(self.llm_decisions / max(total, 1) * 100, 1),
            "avg_latency_ms": round(self.total_latency_ms / max(total, 1), 2),
        }


class HybridDecisionRouter:
    """
    하이브리드 판단 라우터.

    1단계: 안전 규칙 검사 (Rule, < 1ms)
    2단계: 복잡도 평가 → Rule 또는 LLM 라우팅
    3단계: LLM 실패 시 Rule 폴백

    MAS_LLM_ROUTER_SCOPE=pa_only | all_gated
    MAS_LLM_PER_AGENT_ASSIST=1 일 때 all_gated 에서 비 PA 도 복합·고심각 경보 시 LLM 후보.
    """

    def __init__(
        self,
        llm_client=None,
        *,
        llm_router_scope: str = "pa_only",
        llm_per_agent_assist: bool = False,
    ):
        self.llm = llm_client
        self.llm_router_scope = llm_router_scope
        self.llm_per_agent_assist = llm_per_agent_assist
        self.metrics = RouterMetrics()
        self._decision_log: List[DecisionRecord] = []
        self._lock = threading.Lock()

    def route(self, agent_id: str, sensed: dict, env_snapshot: dict) -> Optional[ThinkResult]:
        """
        판단 라우팅. Rule로 처리 가능하면 즉시 반환, 아니면 None (호출자가 기본 로직 사용).
        PA의 복합 판단만 LLM 라우팅 후보.
        """
        t0 = time.perf_counter()

        # 1단계: 안전 인터록 (모든 에이전트)
        safety_result = self._check_safety_rules(agent_id, env_snapshot)
        if safety_result:
            self._record("rule", agent_id, "safety_interlock",
                         safety_result.reasoning, t0)
            return safety_result

        # 2단계: 에이전트별 임계값 규칙
        threshold_result = self._check_threshold_rules(agent_id, sensed, env_snapshot)
        if threshold_result:
            self._record("rule", agent_id, "threshold",
                         threshold_result.reasoning, t0)
            return threshold_result

        # 3단계: 라우터 LLM (정책: PA 전용 또는 게이트된 전 에이전트)
        if self._should_route_to_llm(agent_id, sensed, env_snapshot):
            llm_result = self._route_to_llm(sensed, env_snapshot, agent_id=agent_id)
            if llm_result:
                self._record(
                    "llm",
                    agent_id,
                    "strategic_decision",
                    llm_result.reasoning,
                    t0,
                )
                return llm_result
            self.metrics.llm_fallbacks += 1

        return None

    # ── 안전 인터록 규칙 ──────────────────────────────────────

    def _check_safety_rules(self, aid: str, snap: dict) -> Optional[ThinkResult]:
        vib = snap.get("vibration", 0)

        if vib >= RULES["vibration_emergency"]:
            return ThinkResult(
                actions=[
                    Action(type=ActionType.LOG,
                           log_msg=f"[비상정지] 진동 {vib:.1f}mm/s ≥ {RULES['vibration_emergency']}",
                           log_level="ALERT"),
                ],
                reasoning=f"Safety interlock: vibration {vib:.1f} >= emergency threshold",
                decision_source="rule",
            )

        oil = snap.get("oil_temp", 0)
        if oil >= RULES["oil_temp_critical"]:
            return ThinkResult(
                actions=[
                    Action(type=ActionType.LOG,
                           log_msg=f"[유온위험] {oil:.0f}°C ≥ {RULES['oil_temp_critical']}°C",
                           log_level="ALERT"),
                ],
                reasoning=f"Safety interlock: oil temp {oil:.0f} >= critical",
                decision_source="rule",
            )

        return None

    # ── 임계값 규칙 ──────────────────────────────────────────

    def _check_threshold_rules(self, aid: str, sensed: dict,
                               snap: dict) -> Optional[ThinkResult]:
        if aid == "EA":
            return self._ea_rules(snap)
        if aid == "SA":
            return self._sa_rules(snap)
        return None

    def _ea_rules(self, snap: dict) -> Optional[ThinkResult]:
        vib = snap.get("vibration", 0)
        if vib >= RULES["vibration_critical"]:
            return ThinkResult(
                actions=[
                    Action(type=ActionType.LOG,
                           log_msg=f"Rule: 진동 {vib:.1f} ≥ {RULES['vibration_critical']} → 즉시 감속",
                           log_level="ALERT"),
                ],
                reasoning=f"Threshold rule: vib {vib:.1f} >= critical, force speed reduction",
                decision_source="rule",
            )
        return None

    def _sa_rules(self, snap: dict) -> Optional[ThinkResult]:
        buf = snap.get("material_buffer_hours", 99)
        if buf < RULES["material_buffer_critical_h"]:
            return ThinkResult(
                actions=[
                    Action(type=ActionType.LOG,
                           log_msg=f"Rule: 자재 버퍼 {buf:.1f}h < {RULES['material_buffer_critical_h']}h → 긴급 보충",
                           log_level="ALERT"),
                ],
                reasoning=f"Threshold rule: material buffer critical ({buf:.1f}h)",
                decision_source="rule",
            )
        return None

    # ── LLM 라우팅 판단 ──────────────────────────────────────

    def _should_route_to_llm(self, agent_id: str, sensed: dict, snap: dict) -> bool:
        if not self.llm or not self.llm.enabled:
            return False
        if agent_id == "PA":
            return self._should_use_llm_pa(sensed, snap)
        if self.llm_router_scope != "all_gated" or not self.llm_per_agent_assist:
            return False
        if agent_id not in ("EA", "QA", "SA", "DA", "IA"):
            return False
        return self._should_use_llm_non_pa(sensed)

    def _should_use_llm_pa(self, sensed: dict, snap: dict) -> bool:
        """PA: 복합 판단(경보 유형 2종 이상)일 때 LLM 후보."""
        alerts = sensed.get("new_alerts") or sensed.get("alerts") or []
        if len(alerts) < 2:
            return False

        alert_types = set()
        for a in alerts:
            if hasattr(a, "body"):
                alert_types.add(a.body.get("type", ""))
            elif isinstance(a, dict):
                alert_types.add(a.get("type", ""))

        return len(alert_types) >= 2

    def _should_use_llm_non_pa(self, sensed: dict) -> bool:
        """비 PA: 고심각 또는 다건 경보일 때만 LLM 후보 (설비 직접 명령 없음)."""
        alerts = sensed.get("new_alerts") or sensed.get("alerts") or []
        if len(alerts) < 2:
            return False

        def _sev(x: Any) -> str:
            if isinstance(x, dict):
                return str(x.get("severity", "") or "").upper()
            if hasattr(x, "body"):
                return str(x.body.get("severity", "") or "").upper()
            return ""

        severities = [_sev(a) for a in alerts]
        if any(s in ("CRITICAL", "HIGH") for s in severities):
            return True
        return len(alerts) >= 3

    def _route_to_llm(
        self,
        sensed: dict,
        snap: dict,
        agent_id: str = "PA",
    ) -> Optional[ThinkResult]:
        """복합 상황을 LLM에 위임 (로그·권고; 실행은 규칙·에이전트 reason 유지)."""
        if not self.llm or not self.llm.enabled:
            return None

        alerts = sensed.get("new_alerts") or sensed.get("alerts") or []
        alert_dicts = []
        for a in alerts:
            if hasattr(a, "header"):
                alert_dicts.append({
                    "sender": a.header.sender,
                    "type": a.body.get("type", ""),
                    "summary": a.body.get("summary", ""),
                })
            elif isinstance(a, dict):
                alert_dicts.append(a)

        result = self.llm.analyze_situation(snap, alert_dicts, agent_id=agent_id)
        if not result:
            return None

        actions = []
        severity = result.get("severity", "MEDIUM")
        should_cnp = result.get("should_initiate_cnp", False)

        for action_text in result.get("immediate_actions", []):
            actions.append(Action(
                type=ActionType.LOG,
                log_msg=f"LLM → {action_text}",
                log_level="INFO",
            ))

        reasoning = (
            f"[{agent_id}] LLM analysis: severity={severity}, CNP={should_cnp}. "
            f"{result.get('reasoning', '')}"
        )

        return ThinkResult(
            actions=actions,
            reasoning=reasoning,
            decision_source="llm",
        )

    # ── 기록 ──────────────────────────────────────────────────

    def _record(self, route: str, aid: str, rule_name: str,
                reasoning: str, t0: float):
        latency = (time.perf_counter() - t0) * 1000
        self.metrics.record(route, latency)
        record = DecisionRecord(
            timestamp=time.time(), agent_id=aid,
            route=route, rule_name=rule_name,
            reasoning=reasoning, latency_ms=round(latency, 2),
        )
        with self._lock:
            self._decision_log.append(record)
            if len(self._decision_log) > 300:
                self._decision_log = self._decision_log[-150:]

    def get_status(self) -> dict:
        return {
            "rules": RULES,
            "llm_router_scope": self.llm_router_scope,
            "llm_per_agent_assist": self.llm_per_agent_assist,
            "metrics": self.metrics.to_dict(),
            "recent_decisions": [
                {"agent": d.agent_id, "route": d.route,
                 "rule": d.rule_name, "latency_ms": d.latency_ms}
                for d in self._decision_log[-10:]
            ],
        }
