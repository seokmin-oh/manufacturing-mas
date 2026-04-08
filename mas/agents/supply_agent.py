"""
자재/공급 에이전트 (Supply Agent)
================================

## 입력
`materials` 재고·안전재고·리드타임·생산 속도에 따른 소모율(시뮬).

## 출력
부족·ROP 경보, PA/브로커 메시지. 런타임 이벤트 루프의 입고와 상호작용.
"""


from __future__ import annotations

from typing import Dict, List, Optional

from .base_agent import BaseAgent
from ..messaging.message import Intent


class SupplyAgent(BaseAgent):
    def __init__(self):
        super().__init__("SA", "자재 에이전트")

        self._consumption_history: Dict[str, List[int]] = {}
        self._reorder_log: List[Dict] = []
        self._supplier_scores: Dict[str, float] = {}
        self._sub_views: Dict[str, Dict] = {}

    def sense(self, snapshot: Dict) -> Dict:
        materials = snapshot.get("materials", {})
        obs = {
            "material_status": {},
            "shortages": [],
            "reorder_needed": [],
        }

        for name, mdata in materials.items():
            stock = mdata.get("stock", 0)
            ss = mdata.get("safety_stock", 0)
            dos = mdata.get("days_supply", 999)
            needs = mdata.get("needs_reorder", False)

            if name not in self._consumption_history:
                self._consumption_history[name] = []
            self._consumption_history[name].append(stock)
            if len(self._consumption_history[name]) > 100:
                self._consumption_history[name] = self._consumption_history[name][-100:]

            consumption_rate = self._calc_consumption_rate(name)

            status = "충분"
            if stock <= ss * 0.5:
                status = "위험"
                obs["shortages"].append({
                    "material": name, "stock": stock,
                    "safety_stock": ss, "days_supply": dos,
                })
            elif needs or stock <= ss:
                status = "부족"
                obs["reorder_needed"].append({
                    "material": name, "stock": stock,
                    "safety_stock": ss, "days_supply": dos,
                    "consumption_rate": round(consumption_rate, 1),
                })
            elif dos < 3:
                status = "주의"

            obs["material_status"][name] = {
                "stock": stock, "safety_stock": ss,
                "days_supply": dos, "status": status,
                "consumption_rate": round(consumption_rate, 1),
            }

        self._sub_views = {
            "SA-ROP": {
                "role_ko": "ROP·발주",
                "shortages_n": len(obs["shortages"]),
                "reorder_queue_n": len(obs["reorder_needed"]),
            },
            "SA-STOCK": {
                "role_ko": "재고·일수",
                "materials_n": len(obs["material_status"]),
                "recent_reorders_n": len(self._reorder_log),
            },
        }

        return obs

    def reason(self, obs: Dict) -> Optional[Dict]:
        decision = {
            "type": "supply_assessment",
            "reorders": [],
            "alerts": [],
            "priority": "LOW",
        }

        for shortage in obs.get("shortages", []):
            decision["priority"] = "CRITICAL"
            decision["reorders"].append({
                "material": shortage["material"],
                "type": "긴급발주",
                "reason": f"재고 {shortage['stock']}개 < 안전재고 50%",
            })
            decision["alerts"].append({
                "target": "PA",
                "severity": "CRITICAL",
                "message": f"자재 부족 위험: {shortage['material']} "
                           f"(재고 {shortage['stock']}, 안전재고 {shortage['safety_stock']})",
            })
            self.log_reasoning(f"[긴급] {shortage['material']} 재고 부족 → 긴급발주")

        for reorder in obs.get("reorder_needed", []):
            if decision["priority"] not in ("CRITICAL",):
                decision["priority"] = "MEDIUM"
            decision["reorders"].append({
                "material": reorder["material"],
                "type": "정기발주",
                "reason": f"잔여 {reorder['days_supply']:.1f}일분",
            })
            self.log_reasoning(
                f"[발주] {reorder['material']} — 잔여 {reorder['days_supply']:.1f}일, "
                f"소모율 {reorder['consumption_rate']}/cycle"
            )

        if not decision["reorders"] and not decision["alerts"]:
            safe_count = sum(
                1 for m in obs.get("material_status", {}).values()
                if m["status"] == "충분"
            )
            total = len(obs.get("material_status", {}))
            self.log_reasoning(f"자재 안정: {safe_count}/{total} 충분")
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
                "reorder_list": decision.get("reorders", []),
            })
            actions.append(f"경보: {alert['message']}")

        for ro in decision.get("reorders", []):
            self._reorder_log.append(ro)
            actions.append(f"발주: {ro['material']} ({ro['type']})")

        return actions

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        critical = [r for r in self._reorder_log[-5:] if r.get("type") == "긴급발주"]
        viol = 1.0 if critical else (0.4 if self._reorder_log else 0.0)
        cost_est = min(1.0, 0.2 * len(critical) + 0.05 * len(self._reorder_log[-10:]))
        return {
            "agent": self.agent_id,
            "proposal": "자재 관점 대응",
            "critical_materials": critical,
            "reorder_pending": len(self._reorder_log),
            "scores": {
                "quality": 0.5, "delivery": 0.8,
                "cost": 0.6, "safety": 0.6,
            },
            "proposal_metrics": {
                "cost_estimate": round(cost_est, 4),
                "constraint_violation_total": viol,
                "critical_material_n": len(critical),
            },
        }

    def execute_accepted_proposal(self, proposal: Dict):
        self.log_reasoning("자재 대응 실행 완료")

    def get_agent_status(self) -> Dict:
        st = super().get_agent_status()
        st["sub_agent_views"] = dict(self._sub_views)
        return st

    def _calc_consumption_rate(self, name: str) -> float:
        history = self._consumption_history.get(name, [])
        if len(history) < 3:
            return 0.0
        diffs = [history[i] - history[i + 1] for i in range(len(history) - 1) if history[i] > history[i + 1]]
        return sum(diffs) / len(diffs) if diffs else 0.0
