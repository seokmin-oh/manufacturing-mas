"""
계획 에이전트 (Planning Agent) — 공장 오케스트레이터
================================================

## 역할
- 타 에이전트 **inbox 경보** 수집·버퍼링 후 심각도 판단 → 필요 시 **CNP 소집**.
- `initiate_cnp`: `CNPSession` 으로 CFP/PROPOSE/ACCEPT 흐름 실행, **속도·검사모드** 등 통합 전략.
- **KPI_WEIGHTS**: 품질·납기·비용·안전 가중 — `optimization_engine` 과 맞물림.

## LLM
`llm_client` 가 있으면 전략 JSON·서술 보강. 없거나 실패 시 규칙/솔버만으로 동작.

## 런타임
`FactoryRuntime._run_pa` 만 `initiate_cnp` 플래그를 보고 CNP 루틴을 호출한다.
"""


from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Any

_log = logging.getLogger(__name__)

from .base_agent import BaseAgent
from .planning_sub import (
    build_pa_report_lines,
    collect_inbox_alerts,
    rank_proposals_by_comparison,
)
from ..messaging.message import AgentMessage, Intent
from ..protocol.cnp_comparison import merge_into_proposal
from ..protocol.cnp_session import CNPSession, CNPConstraints, PROTOCOL_VERSION
from ..intelligence.optimization_engine import build_llm_context
from ..intelligence.operational_decision_card import from_cnp_strategy

KPI_WEIGHTS = {
    "quality": 0.30,
    "delivery": 0.25,
    "cost": 0.25,
    "safety": 0.20,
}


class PlanningAgent(BaseAgent):
    def __init__(self, llm_client=None):
        super().__init__("PA", "계획 에이전트")

        self.llm = llm_client
        self._alert_buffer: List[Dict] = []
        self._cnp_count = 0
        self._last_cnp_cycle = 0
        self._strategy_log: List[Dict] = []
        self._pending_alerts: List[Dict] = []

    def sense(self, snapshot: Dict) -> Dict:
        msgs = self.pop_inbox()
        alerts = collect_inbox_alerts(msgs)
        self._pending_alerts = alerts

        mctx = snapshot.get("manufacturing_context") if isinstance(snapshot.get("manufacturing_context"), dict) else {}
        id_block = mctx.get("identifiers") if isinstance(mctx, dict) else {}
        kpi_line = (mctx.get("kpi_slices") or {}).get("line") if isinstance(mctx, dict) else {}

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
            "standard_identifiers": id_block,
            "standard_line_kpi": kpi_line,
        }

    def reason(self, obs: Dict) -> Optional[Dict]:
        alerts = obs.get("alerts", [])
        cycle = obs.get("cycle", 0)
        avg_oee = obs.get("avg_oee", 1.0)

        decision = {
            "type": "planning_assessment",
            "action": "monitor",
            "initiate_cnp": False,
            "speed_adjustments": {},
            "alerts_processed": len(alerts),
            "priority": "LOW",
        }

        critical_count = sum(1 for a in alerts if a["severity"] == "CRITICAL")
        high_count = sum(1 for a in alerts if a["severity"] == "HIGH")

        should_cnp = (
            critical_count >= 1
            or high_count >= 2
            or (avg_oee < 0.65 and cycle - self._last_cnp_cycle > 30)
        )

        if should_cnp and cycle - self._last_cnp_cycle > 10:
            decision["initiate_cnp"] = True
            decision["action"] = "cnp"
            decision["priority"] = "CRITICAL" if critical_count > 0 else "HIGH"
            decision["cnp_reason"] = self._summarize_alerts(alerts)
            self.log_reasoning(
                f"[CNP] 협상 개시: CRITICAL={critical_count} HIGH={high_count} "
                f"OEE={avg_oee:.1%} — {decision['cnp_reason']}"
            )
        elif alerts:
            decision["action"] = "adjust"
            decision["priority"] = "MEDIUM"
            for a in alerts:
                self.log_reasoning(f"[수신] {a['sender']}: {a['summary']}")
        else:
            if avg_oee >= 0.85:
                self.log_reasoning(f"공장 정상: OEE={avg_oee:.1%}, 생산={obs.get('total_produced', 0)}개")
            else:
                self.log_reasoning(f"OEE 모니터링: {avg_oee:.1%} (목표 85%)")
            return None

        return decision

    def act(self, decision: Optional[Dict]) -> List[str]:
        actions = []
        if not decision:
            return actions

        if decision.get("action") == "adjust":
            actions.append(f"경보 처리: {decision.get('alerts_processed', 0)}건")

        return actions

    def initiate_cnp(self, agents: List, snapshot: Dict) -> Optional[Dict]:
        """CNP 프로세스 실행 — 세션(제약·대화 ID)·브로커 CFP·제안 정규화."""
        self._cnp_count += 1
        self._last_cnp_cycle = snapshot.get("cycle", 0)

        session = CNPSession(CNPConstraints())
        conversation_id = session.begin()
        situation = self._summarize_alerts(self._pending_alerts)

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
            "constraints": {
                "speed_min_pct": session.constraints.speed_min_pct,
                "speed_max_pct": session.constraints.speed_max_pct,
                "deadline_sec": session.constraints.deadline_sec,
            },
        }

        if self.broker:
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
            except Exception as e:
                _log.debug("CNP CFP 브로드캐스트 실패: %s", e)

        session.mark_collecting()
        proposals: List[Dict[str, Any]] = []
        for agent in agents:
            if agent.agent_id == self.agent_id:
                continue
            if session.is_expired():
                session.mark_timeout()
                self.log_reasoning(f"[CNP#{self._cnp_count}] 타임아웃(수집 단계)")
                return None
            try:
                raw = agent.handle_cfp(cfp_data)
                if not raw:
                    continue
                prop = dict(raw)
                merge_into_proposal(prop)
                sp = prop.get("speed_recommendation", prop.get("target_speed_pct", 100))
                try:
                    sp = int(float(sp))
                except (TypeError, ValueError):
                    sp = 100
                sp = max(
                    session.constraints.speed_min_pct,
                    min(session.constraints.speed_max_pct, sp),
                )
                prop["speed_recommendation"] = sp
                total = sum(
                    prop.get("scores", {}).get(k, 0) * w
                    for k, w in KPI_WEIGHTS.items()
                )
                pm = prop.get("proposal_metrics") or {}
                viol = float(pm.get("constraint_violation_total") or 0.0)
                total_adj = total - 0.05 * min(viol, 1.0)
                prop["total_score"] = round(total_adj, 3)
                proposals.append(prop)
            except Exception as e:
                _log.debug("에이전트 %s 제안 수집 실패: %s", agent.agent_id, e)
                continue

        if not proposals:
            session.mark_timeout()
            return None

        session.mark_evaluating()
        proposals = rank_proposals_by_comparison(proposals)
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
            matching = [p for p in proposals if p.get("agent") == agent.agent_id]
            if matching:
                try:
                    agent.execute_accepted_proposal(matching[0])
                except Exception as e:
                    _log.warning("에이전트 %s 제안 실행 실패: %s", agent.agent_id, e)

        session.mark_completed()
        self._strategy_log.append(strategy)
        self.log_reasoning(
            f"[CNP#{self._cnp_count}] 완료: 최우선={best.get('agent')} "
            f"(점수 {best['total_score']:.3f}) conv={conversation_id}"
        )

        return strategy

    def _build_strategy(self, proposals: List[Dict], snapshot: Dict) -> Dict:
        if self.llm and self.llm.enabled:
            return self._build_strategy_llm(proposals, snapshot)
        return self._build_strategy_rules(proposals, snapshot)

    def _build_strategy_rules(self, proposals: List[Dict], snapshot: Dict) -> Dict:
        best = proposals[0] if proposals else {}
        speed = best.get("speed_recommendation", 100)
        return {
            "cnp_id": self._cnp_count,
            "decision": "rule_based",
            "target_speed_pct": speed,
            "inspection_mode": best.get("inspection_mode", "표준"),
            "best_agent": best.get("agent", ""),
            "best_score": best.get("total_score", 0),
            "proposals_count": len(proposals),
            "rationale": "규칙 기반 최적 제안 선정",
        }

    def _build_strategy_llm(self, proposals: List[Dict], snapshot: Dict) -> Dict:
        try:
            context = build_llm_context(snapshot)
            result = self.llm.evaluate_proposals(context, proposals)
            if result:
                result["cnp_id"] = self._cnp_count
                return result
        except Exception as e:
            _log.warning("LLM 전략 생성 실패, 규칙 기반으로 폴백: %s", e)
        return self._build_strategy_rules(proposals, snapshot)

    def _summarize_alerts(self, alerts: List[Dict]) -> str:
        if not alerts:
            return "정기 점검"
        parts = []
        for a in alerts[:3]:
            parts.append(f"{a.get('sender', '?')}: {a.get('summary', '')[:40]}")
        return " | ".join(parts)

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        return None

    def execute_accepted_proposal(self, proposal: Dict):
        pass

    @property
    def cnp_count(self) -> int:
        return self._cnp_count

    def get_agent_status(self) -> Dict:
        st = super().get_agent_status()
        st["cnp_rounds"] = self._cnp_count
        st["last_cnp_cycle"] = self._last_cnp_cycle
        st["recent_strategies"] = self._strategy_log[-4:] if self._strategy_log else []
        st["pending_alerts_n"] = len(self._pending_alerts)
        st["sub_agent_views"] = {
            "PA-ORCH": {
                "role_ko": "계획·CNP 오케스트레이션",
                "cnp_rounds_total": self._cnp_count,
                "strategies_on_record": len(self._strategy_log),
                "pending_alerts": len(self._pending_alerts),
            },
            "PA-ALERT": {
                "role_ko": "경보 수집 (Alert collector)",
                "last_cnp_cycle": self._last_cnp_cycle,
            },
            "PA-RANK": {"role_ko": "대안 랭킹 (Recommendation ranker)"},
            "PA-EVAL": {"role_ko": "제약 평가 (Constraint evaluator)"},
            "PA-REPORT": {"role_ko": "전략 리포트 (Report generator)"},
        }
        return st
