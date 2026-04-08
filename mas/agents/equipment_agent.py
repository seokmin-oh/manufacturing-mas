"""
설비 에이전트 (Equipment Agent) — 예지보전·라인 건강도
====================================================

## 입력
`get_snapshot()["stations"]` — 공정별 센서·상태·공구.

## 처리
- `equipment_sub`: 원시 이상 점수·RUL 시간 추정(휴리스틱).
- `equipment_predictive_models`: `station_type` 별 PdM 프로파일로 스케일·메타.

## 출력
- PA·브로커로 ALERT, `get_agent_status()` 에 `equipment_by_station`, `sub_agent_views` 등.
"""


from __future__ import annotations

import math
from typing import Dict, List, Optional

from .base_agent import BaseAgent
from .equipment_sub import compute_raw_anomaly, estimate_rul_hours, trim_history
from ..messaging.message import Intent
from ..intelligence.equipment_predictive_models import (
    model_catalog,
    profile_for_station_type,
    scale_anomaly_for_type,
)


class EquipmentAgent(BaseAgent):
    ANOMALY_ALARM_THRESHOLD = 0.7
    ANOMALY_CRITICAL_THRESHOLD = 0.9
    SLOPE_ALERT_THRESHOLD = 0.05
    TOOL_WARN_PCT = 15
    TOOL_URGENT_PCT = 5
    HEALTH_PENALTY_PER_ANOMALY = 30
    HEALTH_PENALTY_PER_TOOL_PCT = 3
    SPEED_CRITICAL_PCT = 60
    SPEED_WARNING_PCT = 80
    RUL_LOW_HOURS = 4
    RUL_CNP_HOURS = 8
    TREND_HISTORY_MAXLEN = 200

    def __init__(self):
        super().__init__("EA", "설비 에이전트")

        self._trend_history: Dict[str, List[float]] = {}
        self._alarm_state: Dict[str, str] = {}
        self._rul_estimates: Dict[str, float] = {}
        self._maintenance_queue: List[Dict] = []
        self._anomaly_scores: Dict[str, float] = {}
        self._equipment_by_station: Dict[str, Dict] = {}

    def sense(self, snapshot: Dict) -> Dict:
        stations = snapshot.get("stations", {})
        self._equipment_by_station = {}
        observations = {
            "station_health": {},
            "alarms": [],
            "tool_warnings": [],
            "trend_alerts": [],
        }

        for sid, sdata in stations.items():
            sensors = sdata.get("sensors", {})
            health_score = 100.0
            stype = (sdata.get("type") or "PRESS").strip().upper()
            prof = profile_for_station_type(stype)
            max_an = 0.0
            worst_sn = ""

            for sname, sinfo in sensors.items():
                key = f"{sid}.{sname}"
                val = sinfo.get("value", 0)
                ma = sinfo.get("ma", val)
                slope = sinfo.get("slope", 0)
                std_dev = sinfo.get("std", 0)

                trim_history(self._trend_history, key, val, maxlen=self.TREND_HISTORY_MAXLEN)
                hist = self._trend_history.get(key, [])
                raw_an = compute_raw_anomaly(val, ma, std_dev, hist)
                anomaly = scale_anomaly_for_type(stype, sname, raw_an)
                self._anomaly_scores[key] = anomaly
                if anomaly > max_an:
                    max_an = anomaly
                    worst_sn = sname

                if anomaly > self.ANOMALY_ALARM_THRESHOLD:
                    observations["alarms"].append({
                        "station": sid, "sensor": sname,
                        "value": val, "anomaly": round(anomaly, 2),
                        "trend": "상승" if slope > 0 else "하강",
                    })
                    health_score -= anomaly * self.HEALTH_PENALTY_PER_ANOMALY

                if abs(slope) > self.SLOPE_ALERT_THRESHOLD:
                    observations["trend_alerts"].append({
                        "station": sid, "sensor": sname,
                        "slope": round(slope, 4),
                        "direction": "악화" if slope > 0 else "개선",
                    })

            tool_life = sdata.get("tool_life_pct", 100)
            if tool_life < self.TOOL_WARN_PCT:
                observations["tool_warnings"].append({
                    "station": sid,
                    "tool_life_pct": tool_life,
                    "region": sdata.get("tool_region", ""),
                    "urgency": "긴급" if tool_life < self.TOOL_URGENT_PCT else "주의",
                })
                health_score -= (self.TOOL_WARN_PCT - tool_life) * self.HEALTH_PENALTY_PER_TOOL_PCT

            # 스냅샷은 JSON 호환을 위해 mtbf 없음(고장 0회)을 null 로 보냄 → 내부는 inf 로 취급
            mtbf = sdata.get("mtbf", float("inf"))
            if mtbf is None:
                mtbf_sec = float("inf")
            else:
                try:
                    mtbf_sec = float(mtbf) if mtbf != float("inf") else float("inf")
                except (TypeError, ValueError):
                    mtbf_sec = float("inf")
            rul = estimate_rul_hours(sid, health_score, mtbf_sec, stype)
            self._rul_estimates[sid] = rul

            observations["station_health"][sid] = {
                "score": round(max(0, health_score), 1),
                "state": sdata.get("state", ""),
                "oee": sdata.get("oee", {}),
                "rul_hours": round(rul, 1),
                "tool_life_pct": tool_life,
                "station_type": stype,
                "predictive_model_id": prof["model_id"],
                "predictive_model_name": prof["name_kr"],
                "max_anomaly": round(max_an, 3),
                "worst_sensor": worst_sn or "-",
            }

            self._equipment_by_station[sid] = {
                "station_type": stype,
                "model_id": prof["model_id"],
                "model_name_kr": prof["name_kr"],
                "focus": prof.get("focus", ""),
                "health_score": round(max(0, health_score), 1),
                "rul_hours": round(rul, 1),
                "max_anomaly": round(max_an, 3),
                "worst_sensor": worst_sn or "-",
            }

        return observations

    def reason(self, obs: Dict) -> Optional[Dict]:
        decision = {
            "type": "equipment_assessment",
            "maintenance_actions": [],
            "speed_adjustments": [],
            "alerts_to_send": [],
            "priority": "LOW",
        }

        for alarm in obs.get("alarms", []):
            sid = alarm["station"]
            if alarm["anomaly"] > self.ANOMALY_CRITICAL_THRESHOLD:
                decision["maintenance_actions"].append({
                    "station": sid,
                    "action": "비상정비",
                    "reason": f"{alarm['sensor']} 이상 감지 (score: {alarm['anomaly']})",
                })
                decision["speed_adjustments"].append({"station": sid, "target_pct": self.SPEED_CRITICAL_PCT})
                decision["priority"] = "CRITICAL"
                decision["alerts_to_send"].append({
                    "target": "PA", "severity": "CRITICAL",
                    "message": f"{sid} 비상: {alarm['sensor']} 이상({alarm['value']:.2f})",
                })
                self.log_reasoning(f"[비상] {sid} {alarm['sensor']} 이상탐지 점수 {alarm['anomaly']}")
            elif alarm["anomaly"] > self.ANOMALY_ALARM_THRESHOLD:
                decision["speed_adjustments"].append({"station": sid, "target_pct": self.SPEED_WARNING_PCT})
                if decision["priority"] != "CRITICAL":
                    decision["priority"] = "HIGH"
                self.log_reasoning(f"[경고] {sid} {alarm['sensor']} 주의 필요")

        for tw in obs.get("tool_warnings", []):
            sid = tw["station"]
            if tw["urgency"] == "긴급":
                decision["maintenance_actions"].append({
                    "station": sid,
                    "action": "공구교체",
                    "reason": f"잔여수명 {tw['tool_life_pct']:.0f}% ({tw['region']})",
                })
                decision["alerts_to_send"].append({
                    "target": "PA", "severity": "HIGH",
                    "message": f"{sid} 공구교체 필요 (잔여 {tw['tool_life_pct']:.0f}%)",
                })
                self.log_reasoning(f"[공구] {sid} 교체 필요 — 급격마모 구간")

        for health in obs.get("station_health", {}).values():
            if health["rul_hours"] < self.RUL_LOW_HOURS:
                if decision["priority"] == "LOW":
                    decision["priority"] = "MEDIUM"
                self.log_reasoning(f"RUL 경고: 예상 잔여수명 {health['rul_hours']:.1f}h")

        if not decision["maintenance_actions"] and not decision["alerts_to_send"]:
            self.log_reasoning("전 공정 정상 가동 중")
            return None

        return decision

    def act(self, decision: Optional[Dict]) -> List[str]:
        actions = []
        if not decision:
            return actions

        for alert in decision.get("alerts_to_send", []):
            self.send_message(alert["target"], Intent.ALERT, {
                "source": self.agent_id,
                "severity": alert["severity"],
                "summary": alert["message"],
                "rul_estimates": self._rul_estimates,
            })
            actions.append(f"경보 전송: {alert['message']}")

        self._maintenance_queue = decision.get("maintenance_actions", [])
        for ma in self._maintenance_queue:
            actions.append(f"정비요청: {ma['station']} — {ma['action']}")

        return actions

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        worst_station = min(
            self._rul_estimates.items(), key=lambda x: x[1], default=(None, 999)
        )
        wr = float(worst_station[1]) if worst_station[0] is not None else 999.0
        cost_est = max(0.0, min(1.0, 1.0 - min(wr, 120.0) / 120.0))
        viol = 1.0 if wr < self.RUL_LOW_HOURS else (0.5 if wr < self.RUL_CNP_HOURS else 0.0)
        return {
            "agent": self.agent_id,
            "proposal": "설비 관점 대응",
            "speed_recommendation": self.SPEED_WARNING_PCT if worst_station[1] < self.RUL_CNP_HOURS else 100,
            "maintenance_needed": list(self._maintenance_queue),
            "health_summary": {
                sid: round(rul, 1) for sid, rul in self._rul_estimates.items()
            },
            "scores": {
                "quality": 0.7, "delivery": 0.6,
                "cost": 0.5, "safety": 0.9,
            },
            "proposal_metrics": {
                "cost_estimate": round(cost_est, 4),
                "constraint_violation_total": viol,
                "rul_worst_hours": round(wr, 2),
            },
        }

    def execute_accepted_proposal(self, proposal: Dict):
        for ma in proposal.get("maintenance_needed", []):
            self.log_reasoning(f"정비 실행: {ma['station']} — {ma['action']}")

    def get_agent_status(self) -> Dict:
        st = super().get_agent_status()
        st["equipment_by_station"] = dict(self._equipment_by_station)
        st["pm_model_catalog"] = model_catalog()
        st["rul_estimates"] = dict(self._rul_estimates)
        ad_summary = {
            sid: round(v.get("max_anomaly", 0.0), 4)
            for sid, v in self._equipment_by_station.items()
            if isinstance(v, dict)
        }
        st["sub_agent_views"] = {
            "EA-AD": {
                "role_ko": "이상 감지",
                "max_anomaly_by_station": ad_summary,
            },
            "EA-RUL": {
                "role_ko": "RUL 추정",
                "rul_hours_by_station": {k: round(v, 2) for k, v in self._rul_estimates.items()},
            },
        }
        return st
