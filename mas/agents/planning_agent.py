from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent
from .planning_sub import (
    build_pa_report_lines,
    collect_inbox_alerts,
    evaluate_proposal,
    rank_proposals_by_comparison,
)
from ..intelligence.operational_decision_card import from_cnp_strategy
from ..intelligence.optimization_engine import build_llm_context
from ..messaging.message import AgentMessage, Intent
from ..protocol.cnp_session import CNPSession, CNPConstraints, PROTOCOL_VERSION

_log = logging.getLogger(__name__)

KPI_WEIGHTS = {
    "quality": 0.30,
    "delivery": 0.25,
    "cost": 0.25,
    "safety": 0.20,
}


class PlanningAgent(BaseAgent):
    """Planning orchestrator that delegates alert collection, scoring, ranking, and reporting."""

    def __init__(self, llm_client=None):
        super().__init__("PA", "Planning Agent")
        self.llm = llm_client
        self._cnp_count = 0
        self._last_cnp_cycle = 0
        self._strategy_log: List[Dict[str, Any]] = []
        self._pending_alerts: List[Dict[str, Any]] = []

    def sense(self, snapshot: Dict) -> Dict:
        msgs = self.pop_inbox()
        alerts = collect_inbox_alerts(msgs)
        self._pending_alerts = alerts

        mctx = snapshot.get("manufacturing_context")
        if not isinstance(mctx, dict):
            mctx = {}
        kpi_slices = mctx.get("kpi_slices") if isinstance(mctx.get("kpi_slices"), dict) else {}
        external_inputs = mctx.get("external_inputs") if isinstance(mctx.get("external_inputs"), dict) else {}
        recent_events = mctx.get("recent_events") if isinstance(mctx.get("recent_events"), list) else []

        return {
            "cycle": snapshot.get("cycle", 0),
            "avg_oee": snapshot.get("avg_oee", 1.0),
            "fg_stock": snapshot.get("fg_stock", 0),
            "total_produced": snapshot.get("total_produced", 0),
            "scrap_count": snapshot.get("scrap_count", 0),
            "shift": snapshot.get("shift", ""),
            "alerts": alerts,
            "stations": snapshot.get("stations", {}),
            "business_events": snapshot.get("business_events") or [],
            "recent_events": recent_events,
            "external_inputs": external_inputs,
            "standard_identifiers": mctx.get("identifiers") if isinstance(mctx.get("identifiers"), dict) else {},
            "standard_line_kpi": kpi_slices.get("line") if isinstance(kpi_slices, dict) else {},
            "context_validation": snapshot.get("manufacturing_context_validation") or [],
        }

    def reason(self, obs: Dict) -> Optional[Dict]:
        alerts = obs.get("alerts", [])
        cycle = obs.get("cycle", 0)
        avg_oee = obs.get("avg_oee", 1.0)
        recent_events = obs.get("recent_events") or []
        external_inputs = obs.get("external_inputs") or {}

        decision = {
            "type": "planning_assessment",
            "action": "monitor",
            "initiate_cnp": False,
            "speed_adjustments": {},
            "alerts_processed": len(alerts),
            "priority": "LOW",
        }

        critical_count = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
        high_count = sum(1 for a in alerts if a.get("severity") == "HIGH")
        event_risk_count = sum(
            1
            for event in recent_events
            if str(event.get("severity", "INFO")).upper() in ("CRITICAL", "HIGH")
        )
        qms_failures = sum(
            1
            for row in external_inputs.get("qms_inspections", [])
            if str(row.get("result", "")).upper() == "FAIL"
        )
        erp_urgent_orders = sum(
            1
            for row in external_inputs.get("erp_sales_orders", [])
            if str(row.get("priority", "")).upper() == "URGENT"
        )

        should_cnp = (
            critical_count >= 1
            or high_count >= 2
            or event_risk_count >= 1
            or qms_failures >= 1
            or erp_urgent_orders >= 2
            or (avg_oee < 0.65 and cycle - self._last_cnp_cycle > 30)
        )

        if should_cnp and cycle - self._last_cnp_cycle > 10:
            decision["initiate_cnp"] = True
            decision["action"] = "cnp"
            decision["priority"] = "CRITICAL" if critical_count > 0 else "HIGH"
            decision["cnp_reason"] = self._summarize_alerts(alerts)
            self.log_reasoning(
                f"[CNP] trigger critical={critical_count} high={high_count} "
                f"events={event_risk_count} qms_fail={qms_failures} "
                f"urgent_orders={erp_urgent_orders} oee={avg_oee:.1%} "
                f"reason={decision['cnp_reason']}"
            )
            return decision

        if alerts:
            decision["action"] = "adjust"
            decision["priority"] = "MEDIUM"
            for alert in alerts:
                self.log_reasoning(
                    f"[ALERT] {alert.get('sender', '?')}: {alert.get('summary', '')}"
                )
            return decision

        if avg_oee >= 0.85:
            self.log_reasoning(
                f"factory stable oee={avg_oee:.1%} produced={obs.get('total_produced', 0)}"
            )
        else:
            self.log_reasoning(f"monitoring oee={avg_oee:.1%} target=85%")
        return None

    def act(self, decision: Optional[Dict]) -> List[str]:
        if not decision:
            return []
        if decision.get("action") == "adjust":
            return [f"alerts reviewed: {decision.get('alerts_processed', 0)}"]
        return []

    def initiate_cnp(self, agents: List, snapshot: Dict) -> Optional[Dict]:
        self._cnp_count += 1
        self._last_cnp_cycle = snapshot.get("cycle", 0)

        session = CNPSession(CNPConstraints())
        conversation_id = session.begin()
        situation = self._summarize_alerts(self._pending_alerts)
        constraints = {
            "speed_min_pct": session.constraints.speed_min_pct,
            "speed_max_pct": session.constraints.speed_max_pct,
            "deadline_sec": session.constraints.deadline_sec,
        }

        snapshot_summary = {
            "avg_oee": snapshot.get("avg_oee", 0),
            "fg_stock": snapshot.get("fg_stock", 0),
            "scrap": snapshot.get("scrap_count", 0),
        }
        cfp_data = {
            "initiator": self.agent_id,
            "cnp_id": self._cnp_count,
            "protocol_version": PROTOCOL_VERSION,
            "conversation_id": conversation_id,
            "situation": situation,
            "snapshot_summary": snapshot_summary,
            "constraints": constraints,
        }

        self._broadcast_cfp(session, situation, snapshot_summary, conversation_id)

        session.mark_collecting()
        proposals = self._collect_proposals(agents, cfp_data, session)
        if not proposals:
            session.mark_timeout()
            return None

        session.mark_evaluating()
        proposals = rank_proposals_by_comparison(proposals, constraints=constraints)
        best = proposals[0]

        strategy = self._build_strategy(proposals, snapshot)
        strategy = session.clamp_strategy(strategy)
        strategy["operational_decision_card"] = from_cnp_strategy(
            situation,
            proposals,
            strategy,
            snapshot,
        )
        strategy["pa_report_lines"] = build_pa_report_lines(strategy, proposals)

        for agent in agents:
            if agent.agent_id == self.agent_id:
                continue
            matching = [proposal for proposal in proposals if proposal.get("agent") == agent.agent_id]
            if matching:
                try:
                    agent.execute_accepted_proposal(matching[0])
                except Exception as exc:
                    _log.warning("agent %s proposal execution failed: %s", agent.agent_id, exc)

        session.mark_completed()
        self._strategy_log.append(strategy)
        self.log_reasoning(
            f"[CNP#{self._cnp_count}] best={best.get('agent')} score={best.get('total_score', 0):.3f} "
            f"conv={conversation_id}"
        )
        return strategy

    def _broadcast_cfp(
        self,
        session: CNPSession,
        situation: str,
        snapshot_summary: Dict[str, Any],
        conversation_id: str,
    ) -> None:
        if not self.broker:
            return
        try:
            body = session.to_cfp_body(situation)
            body["snapshot_summary"] = snapshot_summary
            msg = AgentMessage.create(
                self.agent_id,
                "ALL",
                Intent.CFP,
                body,
                conversation_id=conversation_id,
            )
            self.broker.publish(msg)
        except Exception as exc:
            _log.debug("CNP CFP publish failed: %s", exc)

    def _collect_proposals(
        self,
        agents: List,
        cfp_data: Dict[str, Any],
        session: CNPSession,
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        for agent in agents:
            if agent.agent_id == self.agent_id:
                continue
            if session.is_expired():
                session.mark_timeout()
                self.log_reasoning(f"[CNP#{self._cnp_count}] collection timeout")
                return []
            try:
                raw = agent.handle_cfp(cfp_data)
                if not raw:
                    continue
                proposal = dict(raw)
                speed = proposal.get("speed_recommendation", proposal.get("target_speed_pct", 100))
                try:
                    speed = int(float(speed))
                except (TypeError, ValueError):
                    speed = 100
                speed = max(session.constraints.speed_min_pct, min(session.constraints.speed_max_pct, speed))
                proposal["speed_recommendation"] = speed
                proposals.append(
                    evaluate_proposal(
                        proposal,
                        constraints=cfp_data["constraints"],
                        kpi_weights=KPI_WEIGHTS,
                    )
                )
            except Exception as exc:
                _log.debug("agent %s proposal collection failed: %s", agent.agent_id, exc)
        return proposals

    def _build_strategy(self, proposals: List[Dict], snapshot: Dict) -> Dict:
        if self.llm and self.llm.enabled:
            return self._build_strategy_llm(proposals, snapshot)
        return self._build_strategy_rules(proposals)

    def _build_strategy_rules(self, proposals: List[Dict]) -> Dict:
        best = proposals[0] if proposals else {}
        return {
            "cnp_id": self._cnp_count,
            "decision": "rule_based",
            "target_speed_pct": best.get("speed_recommendation", 100),
            "inspection_mode": best.get("inspection_mode", "standard"),
            "best_agent": best.get("agent", ""),
            "best_score": best.get("total_score", 0),
            "comparison_score": best.get("comparison_score", 0),
            "business_score": best.get("business_score", 0),
            "constraint_penalty": best.get("constraint_penalty", 0),
            "proposals_count": len(proposals),
            "rationale": "rule-ranked manufacturing proposal selected",
        }

    def _build_strategy_llm(self, proposals: List[Dict], snapshot: Dict) -> Dict:
        try:
            context = build_llm_context(snapshot)
            result = self.llm.evaluate_proposals(context, proposals)
            if result:
                result["cnp_id"] = self._cnp_count
                return result
        except Exception as exc:
            _log.warning("LLM strategy generation failed, falling back to rules: %s", exc)
        return self._build_strategy_rules(proposals)

    def _summarize_alerts(self, alerts: List[Dict]) -> str:
        if not alerts:
            return "steady-state monitoring"
        parts = []
        for alert in alerts[:3]:
            parts.append(f"{alert.get('sender', '?')}: {str(alert.get('summary', ''))[:40]}")
        return " | ".join(parts)

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        return None

    def execute_accepted_proposal(self, proposal: Dict):
        return None

    @property
    def cnp_count(self) -> int:
        return self._cnp_count

    def get_agent_status(self) -> Dict:
        status = super().get_agent_status()
        status["cnp_rounds"] = self._cnp_count
        status["last_cnp_cycle"] = self._last_cnp_cycle
        status["recent_strategies"] = self._strategy_log[-4:] if self._strategy_log else []
        status["pending_alerts_n"] = len(self._pending_alerts)
        status["sub_agent_views"] = {
            "PA-ORCH": {
                "role": "planning orchestrator",
                "cnp_rounds_total": self._cnp_count,
                "strategies_on_record": len(self._strategy_log),
                "pending_alerts": len(self._pending_alerts),
            },
            "PA-ALERT": {
                "role": "alert collector",
                "last_cnp_cycle": self._last_cnp_cycle,
            },
            "PA-RANK": {"role": "recommendation ranker"},
            "PA-EVAL": {"role": "constraint and scoring evaluator"},
            "PA-REPORT": {"role": "report generator"},
        }
        return status
