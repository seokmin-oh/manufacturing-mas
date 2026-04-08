"""
재고 에이전트 (Inventory Agent)
===============================

## 입력
WIP 버퍼·완제품·스냅샷 KPI. 병목 힌트는 공정 OEE/대기와 결합.

## 역할
버퍼 과포화·FG 부족 등을 경보. PA 협상 시 처리량·출하 관점 제안.
"""


from __future__ import annotations

from typing import Dict, List, Optional

from .base_agent import BaseAgent
from ..messaging.message import Intent


class InventoryAgent(BaseAgent):
    WIP_WARN_UTIL = 0.8
    WIP_OVERLOAD_UTIL = 0.9
    BOTTLENECK_OEE_THRESHOLD = 0.65
    SCRAP_RATE_THRESHOLD = 0.05

    def __init__(self):
        super().__init__("IA", "재고 에이전트")

        self._wip_history: Dict[str, List[int]] = {}
        self._throughput_history: List[int] = []
        self._bottleneck_station: Optional[str] = None
        self._sub_views: Dict[str, Dict] = {}
        self._last_scrap_rate: float = 0.0
        self._last_wip_alert_n: int = 0

    def sense(self, snapshot: Dict) -> Dict:
        wip = snapshot.get("wip", [])
        stations = snapshot.get("stations", {})
        fg_stock = snapshot.get("fg_stock", 0)
        scrap = snapshot.get("scrap_count", 0)
        total = snapshot.get("total_produced", 0)

        obs = {
            "wip_levels": {},
            "bottleneck": None,
            "fg_stock": fg_stock,
            "throughput": total,
            "scrap_rate": scrap / max(1, total + scrap),
            "station_utilization": {},
            "wip_alerts": [],
        }

        for w in wip:
            key = f"WC-{w['from'] + 1:02d}→WC-{w['to'] + 1:02d}"
            count = w.get("count", 0)
            util = w.get("util", 0)
            obs["wip_levels"][key] = {"count": count, "util": util}

            if key not in self._wip_history:
                self._wip_history[key] = []
            self._wip_history[key].append(count)
            if len(self._wip_history[key]) > 100:
                self._wip_history[key] = self._wip_history[key][-100:]

            if util > self.WIP_WARN_UTIL:
                obs["wip_alerts"].append({
                    "buffer": key, "count": count,
                    "util": util, "status": "과적" if util > self.WIP_OVERLOAD_UTIL else "주의",
                })

        min_oee = 1.0
        bottleneck_id = None
        for sid, sdata in stations.items():
            oee = sdata.get("oee", {}).get("oee", 1.0)
            obs["station_utilization"][sid] = oee
            if oee < min_oee:
                min_oee = oee
                bottleneck_id = sid

        obs["bottleneck"] = bottleneck_id
        self._bottleneck_station = bottleneck_id
        self._throughput_history.append(total)

        self._sub_views = {
            "IA-WIP": {
                "role_ko": "WIP·병목",
                "bottleneck": obs["bottleneck"],
                "wip_alerts_n": len(obs["wip_alerts"]),
            },
            "IA-SCRAP": {
                "role_ko": "폐기·완제품",
                "scrap_rate": round(obs["scrap_rate"], 4),
                "fg_stock": obs["fg_stock"],
                "throughput": obs["throughput"],
            },
        }

        self._last_scrap_rate = float(obs["scrap_rate"])
        self._last_wip_alert_n = len(obs["wip_alerts"])

        return obs

    def reason(self, obs: Dict) -> Optional[Dict]:
        decision = {
            "type": "inventory_assessment",
            "wip_actions": [],
            "alerts": [],
            "priority": "LOW",
        }

        for wa in obs.get("wip_alerts", []):
            if wa["status"] == "과적":
                decision["priority"] = "HIGH"
                decision["wip_actions"].append({
                    "buffer": wa["buffer"],
                    "action": "속도조절",
                    "reason": f"WIP 과적 ({wa['count']}개, {wa['util']:.0%})",
                })
                decision["alerts"].append({
                    "target": "PA",
                    "severity": "HIGH",
                    "message": f"WIP 과적: {wa['buffer']} ({wa['count']}개, {wa['util']:.0%})",
                })
                self.log_reasoning(f"[WIP] {wa['buffer']} 과적 → 전공정 속도조절 필요")

        bn = obs.get("bottleneck")
        if bn:
            bn_oee = obs.get("station_utilization", {}).get(bn, 1.0)
            if bn_oee < self.BOTTLENECK_OEE_THRESHOLD:
                decision["priority"] = max(decision["priority"], "MEDIUM")
                decision["alerts"].append({
                    "target": "PA",
                    "severity": "MEDIUM",
                    "message": f"병목공정: {bn} (OEE {bn_oee:.1%})",
                })
                self.log_reasoning(f"[병목] {bn} OEE={bn_oee:.1%} — 개선 필요")

        scrap_rate = obs.get("scrap_rate", 0)
        if scrap_rate > self.SCRAP_RATE_THRESHOLD:
            decision["alerts"].append({
                "target": "PA",
                "severity": "MEDIUM",
                "message": f"폐기율 상승: {scrap_rate:.1%}",
            })
            self.log_reasoning(f"[폐기] 폐기율 {scrap_rate:.1%} > 5% 기준")

        if not decision["wip_actions"] and not decision["alerts"]:
            self.log_reasoning(
                f"물류 안정: 병목={bn or '없음'}, FG={obs.get('fg_stock', 0)}개, "
                f"폐기율={scrap_rate:.1%}"
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
                "bottleneck": self._bottleneck_station,
            })
            actions.append(f"경보: {alert['message']}")

        return actions

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        th = self._throughput_history
        trend_up = len(th) > 2 and th[-1] > th[-2]
        viol = min(
            1.0,
            0.35 * float(self._last_wip_alert_n) + (0.45 if self._bottleneck_station else 0.0),
        )
        cost_est = min(1.0, self._last_scrap_rate * 8.0 + (0.12 if trend_up else 0.0))
        return {
            "agent": self.agent_id,
            "proposal": "물류 관점 대응",
            "bottleneck": self._bottleneck_station,
            "throughput_trend": "상승" if trend_up else "정체",
            "scores": {
                "quality": 0.6, "delivery": 0.7,
                "cost": 0.7, "safety": 0.5,
            },
            "proposal_metrics": {
                "cost_estimate": round(cost_est, 4),
                "constraint_violation_total": viol,
                "bottleneck_station": self._bottleneck_station,
            },
        }

    def execute_accepted_proposal(self, proposal: Dict):
        self.log_reasoning("물류 대응 실행 완료")

    def get_agent_status(self) -> Dict:
        st = super().get_agent_status()
        st["sub_agent_views"] = dict(self._sub_views)
        return st
