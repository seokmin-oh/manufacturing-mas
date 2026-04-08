"""
수요 에이전트 (Demand Agent)
===========================

## 입력
`orders` 리스트 — 수량·납기·우선순위. 이벤트 루프가 신규 주문을 추가.

## 역할
수요 급변·납기 압력을 감지해 PA·IA 에 신호. 생산 **캐파 배분 솔버**는 PA/CNP 쪽과 연동.
"""


from __future__ import annotations

from typing import Dict, List, Optional

from .base_agent import BaseAgent
from ..messaging.message import Intent


class DemandAgent(BaseAgent):
    def __init__(self):
        super().__init__("DA", "수요 에이전트")

        self._delivery_history: List[Dict] = []
        self._demand_forecast: float = 0.0
        self._capacity_util: float = 0.0
        self._sub_views: Dict[str, Dict] = {}

    def sense(self, snapshot: Dict) -> Dict:
        orders = snapshot.get("orders", [])
        total_produced = snapshot.get("total_produced", 0)
        fg_stock = snapshot.get("fg_stock", 0)
        cycle = snapshot.get("cycle", 0)

        obs = {
            "total_demand": 0,
            "total_delivered": 0,
            "urgent_orders": [],
            "at_risk_orders": [],
            "on_time_rate": 1.0,
            "capacity_utilization": 0.0,
        }

        for o in orders:
            obs["total_demand"] += o.get("qty", 0)
            obs["total_delivered"] += o.get("delivered", 0)
            remaining = o.get("remaining", 0)

            if o.get("priority") == "긴급" and remaining > 0:
                obs["urgent_orders"].append(o)

            if remaining > 0 and fg_stock < remaining * 0.3:
                obs["at_risk_orders"].append({
                    "order": o["id"],
                    "customer": o["customer"],
                    "remaining": remaining,
                    "fg_available": fg_stock,
                })

        if obs["total_demand"] > 0:
            obs["on_time_rate"] = obs["total_delivered"] / obs["total_demand"]

        if cycle > 0:
            daily_capacity = total_produced / max(1, cycle) * 480
            daily_demand = obs["total_demand"] / max(1, len(orders)) if orders else 0
            obs["capacity_utilization"] = min(1.5, daily_demand / max(1, daily_capacity))

        self._capacity_util = obs["capacity_utilization"]

        self._sub_views = {
            "DA-SCHED": {
                "role_ko": "납기·주문",
                "urgent_n": len(obs["urgent_orders"]),
                "at_risk_n": len(obs["at_risk_orders"]),
                "on_time_rate": round(obs["on_time_rate"], 4),
            },
            "DA-CAP": {
                "role_ko": "수요·캐파 균형",
                "capacity_utilization": round(obs["capacity_utilization"], 4),
            },
        }

        return obs

    def reason(self, obs: Dict) -> Optional[Dict]:
        decision = {
            "type": "demand_assessment",
            "schedule_changes": [],
            "alerts": [],
            "priority": "LOW",
        }

        for risk in obs.get("at_risk_orders", []):
            decision["priority"] = "HIGH"
            decision["alerts"].append({
                "target": "PA",
                "severity": "HIGH",
                "message": f"납기 위험: {risk['customer']} — "
                           f"잔여 {risk['remaining']}개, 재고 {risk['fg_available']}개",
            })
            self.log_reasoning(
                f"[납기위험] {risk['customer']}: 잔여주문 {risk['remaining']}개 > 재고 {risk['fg_available']}개"
            )

        for urg in obs.get("urgent_orders", []):
            decision["schedule_changes"].append({
                "order": urg["id"],
                "action": "우선생산",
                "customer": urg["customer"],
                "remaining": urg["remaining"],
            })

        if obs.get("on_time_rate", 1.0) < 0.85:
            decision["priority"] = "CRITICAL"
            decision["alerts"].append({
                "target": "PA",
                "severity": "CRITICAL",
                "message": f"납기 준수율 저하: {obs['on_time_rate']:.1%} (목표 95%)",
            })
            self.log_reasoning(f"[긴급] 납기 준수율 {obs['on_time_rate']:.1%} — 생산 증대 필요")

        if obs.get("capacity_utilization", 0) > 1.1:
            decision["alerts"].append({
                "target": "PA",
                "severity": "MEDIUM",
                "message": f"수요 초과: 생산능력 대비 {obs['capacity_utilization']:.0%}",
            })
            self.log_reasoning(f"수요 > 생산능력: {obs['capacity_utilization']:.0%}")

        if not decision["alerts"] and not decision["schedule_changes"]:
            self.log_reasoning(
                f"수요 안정: 납기율 {obs.get('on_time_rate', 1):.1%}, "
                f"가동률 {obs.get('capacity_utilization', 0):.0%}"
            )
            return None

        return decision

    def act(self, decision: Optional[Dict]) -> List[str]:
        actions = []
        if not decision:
            return actions

        for alert in decision.get("alerts", []):
            self.send_message(alert["target"], Intent.ALERT, {
                "source": self.agent_id,
                "severity": alert["severity"],
                "summary": alert["message"],
                "on_time_rate": self._capacity_util,
            })
            actions.append(f"경보: {alert['message']}")

        return actions

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        cu = float(self._capacity_util)
        viol = 1.0 if cu > 1.1 else (0.5 if cu > 1.0 else 0.0)
        cost_est = max(0.0, min(1.0, cu - 1.0)) if cu > 1.0 else 0.0
        return {
            "agent": self.agent_id,
            "proposal": "수요 관점 대응",
            "speed_recommendation": 110 if self._capacity_util > 1.0 else 100,
            "delivery_risk": self._capacity_util > 0.9,
            "scores": {
                "quality": 0.5, "delivery": 0.9,
                "cost": 0.6, "safety": 0.5,
            },
            "proposal_metrics": {
                "cost_estimate": round(cost_est, 4),
                "constraint_violation_total": viol,
                "capacity_utilization": round(cu, 4),
            },
        }

    def execute_accepted_proposal(self, proposal: Dict):
        self.log_reasoning("수요 대응 실행 완료")

    def get_agent_status(self) -> Dict:
        st = super().get_agent_status()
        st["sub_agent_views"] = dict(self._sub_views)
        return st
