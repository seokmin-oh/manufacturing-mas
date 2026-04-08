"""
품질 에이전트 (Quality Agent) — SPC / 공정능력
===========================================

## 입력
스냅샷의 공정별 측정·수율·불량 힌트(시뮬 데이터).

## 로직(요지)
관리도·런 규칙·Cpk 임계로 경보 생성 → PA 에 ALERT 가능.

## 출력
`get_agent_status` 에 SPC 요약·서브뷰. 품질 위기 시 CNP 제안에 반영.
"""


from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .base_agent import BaseAgent
from .qa_sub import spc as qa_spc
from .qa_sub import vision as qa_vision
from ..messaging.message import Intent
from ..protocol.cnp_comparison import merge_into_proposal


class QualityAgent(BaseAgent):
    CPK_GOOD = 1.33
    CPK_WARNING = 1.0
    QUALITY_RATE_RISK = 0.90
    RISK_STATIONS_WARN = 1
    RISK_STATIONS_BAD = 3
    CPK_TREND_THRESHOLD = 0.1
    MEASUREMENT_HISTORY_LEN = 200
    CPK_HISTORY_LEN = 50

    def __init__(self):
        super().__init__("QA", "품질 에이전트")

        self._measurement_history: Dict[str, List[float]] = defaultdict(list)
        self._cpk_history: Dict[str, List[float]] = defaultdict(list)
        self._defect_log: List[Dict] = []
        self._run_rule_violations: List[Dict] = []
        self._inspection_mode = "표준"  # 표준 / 강화 / 전수
        self._sub_views: Dict[str, Dict] = {}

        self._spec_limits = {
            "WC-01.진동": (0, 5.0),
            "WC-01.금형간극": (0.08, 0.28),
            "WC-02.스프링백": (0, 1.5),
            "WC-03.너겟직경": (4.5, 7.0),
            "WC-04.경도(HRC)": (52, 64),
            "WC-05.치수편차": (-0.05, 0.05),
            "WC-05.표면거칠기": (0, 3.2),
            "WC-06.체결토크": (20, 30),
            "WC-06.비전점수": (85, 100),
        }

    def sense(self, snapshot: Dict) -> Dict:
        stations = snapshot.get("stations", {})
        obs = {
            "cpk_status": {},
            "spc_violations": [],
            "defect_trend": "안정",
            "yield_by_station": {},
            "quality_risk_stations": [],
            "recent_business_events": snapshot.get("business_events") or [],
        }

        for sid, sdata in stations.items():
            sensors = sdata.get("sensors", {})
            oee = sdata.get("oee", {})
            quality_rate = oee.get("quality", 1.0)
            obs["yield_by_station"][sid] = round(quality_rate * 100, 1)

            for sname, sinfo in sensors.items():
                key = f"{sid}.{sname}"
                val = sinfo.get("value", 0)

                self._measurement_history[key].append(val)
                if len(self._measurement_history[key]) > self.MEASUREMENT_HISTORY_LEN:
                    self._measurement_history[key] = self._measurement_history[key][-self.MEASUREMENT_HISTORY_LEN:]

                if key in self._spec_limits:
                    cpk = self._calc_cpk(key)
                    self._cpk_history[key].append(cpk)
                    if len(self._cpk_history[key]) > self.CPK_HISTORY_LEN:
                        self._cpk_history[key] = self._cpk_history[key][-self.CPK_HISTORY_LEN:]

                    obs["cpk_status"][key] = {
                        "cpk": round(cpk, 3),
                        "trend": self._cpk_trend(key),
                        "status": "양호" if cpk >= self.CPK_GOOD else ("주의" if cpk >= self.CPK_WARNING else "위험"),
                    }

                violations = self._check_run_rules(key)
                if violations:
                    for v in violations:
                        obs["spc_violations"].append({
                            "station": sid, "sensor": sname,
                            "rule": v, "key": key,
                        })

            if quality_rate < self.QUALITY_RATE_RISK:
                obs["quality_risk_stations"].append({
                    "station": sid, "quality_rate": round(quality_rate, 3),
                    "name": sdata.get("name", sid),
                })

        risk_count = len(obs["quality_risk_stations"])
        if risk_count >= self.RISK_STATIONS_BAD:
            obs["defect_trend"] = "악화"
        elif risk_count >= self.RISK_STATIONS_WARN:
            obs["defect_trend"] = "주의"

        obs["qa_sub_spc"] = qa_spc.summarize_spc(obs)
        obs["qa_sub_vision"] = qa_vision.vision_channel_stub(stations)

        cpk_vals = [v["cpk"] for v in obs["cpk_status"].values()] if obs["cpk_status"] else []
        min_cpk = min(cpk_vals) if cpk_vals else 2.0
        vision_ch = {k: v for k, v in obs["cpk_status"].items() if "비전" in k}
        vmin = min((v["cpk"] for v in vision_ch.values()), default=None)
        self._sub_views = {
            "QA-SPC": {
                "role_ko": "SPC·Cpk",
                "min_cpk": round(min_cpk, 3),
                "spc_violations_n": len(obs["spc_violations"]),
                "defect_trend": obs["defect_trend"],
            },
            "QA-VISION": {
                "role_ko": "비전·치수",
                "channels": list(vision_ch.keys())[:12],
                "min_cpk_vision": round(vmin, 3) if vmin is not None else None,
            },
            "QA-RISK": {
                "role_ko": "공정 품질 리스크",
                "risk_stations_n": risk_count,
                "inspection_mode": self._inspection_mode,
            },
        }

        return obs

    def reason(self, obs: Dict) -> Optional[Dict]:
        decision = {
            "type": "quality_assessment",
            "inspection_mode": self._inspection_mode,
            "alerts": [],
            "actions": [],
            "priority": "LOW",
        }

        critical_cpk = []
        for key, info in obs.get("cpk_status", {}).items():
            if info["status"] == "위험":
                critical_cpk.append((key, info))
            elif info["status"] == "주의" and info["trend"] == "하강":
                critical_cpk.append((key, info))

        if critical_cpk:
            decision["priority"] = "HIGH"
            self._inspection_mode = "강화"
            decision["inspection_mode"] = "강화"
            for key, info in critical_cpk:
                decision["alerts"].append({
                    "target": "PA",
                    "message": f"Cpk 위험: {key} = {info['cpk']:.2f} ({info['trend']})",
                    "severity": "HIGH",
                })
                self.log_reasoning(f"[SPC] {key} Cpk={info['cpk']:.2f} → 강화 검사")

        for v in obs.get("spc_violations", []):
            decision["alerts"].append({
                "target": "PA",
                "message": f"관리도 위반: {v['station']} {v['sensor']} — {v['rule']}",
                "severity": "MEDIUM",
            })
            self.log_reasoning(f"[SPC규칙] {v['station']}.{v['sensor']}: {v['rule']}")
            if decision["priority"] == "LOW":
                decision["priority"] = "MEDIUM"

        for risk in obs.get("quality_risk_stations", []):
            decision["actions"].append({
                "action": "품질강화",
                "station": risk["station"],
                "reason": f"수율 {risk['quality_rate']:.1%} — 전수검사 권장",
            })

        if obs.get("defect_trend") == "악화":
            self._inspection_mode = "전수"
            decision["inspection_mode"] = "전수"
            decision["priority"] = "CRITICAL"
            decision["alerts"].append({
                "target": "PA",
                "message": f"품질 악화 추세 — 전수검사 전환 ({len(obs['quality_risk_stations'])}개 공정)",
                "severity": "CRITICAL",
            })
            self.log_reasoning("[긴급] 다수 공정 품질 악화 → 전수검사 전환")

        if not decision["alerts"] and not decision["actions"]:
            best_cpk = min(
                (v["cpk"] for v in obs.get("cpk_status", {}).values()),
                default=2.0,
            )
            self.log_reasoning(f"품질 안정: 최저 Cpk={best_cpk:.2f}, 검사={self._inspection_mode}")
            if self._inspection_mode != "표준" and best_cpk >= self.CPK_GOOD:
                self._inspection_mode = "표준"
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
                "inspection_mode": self._inspection_mode,
                "cpk_summary": {
                    k: v[-1] if v else 0
                    for k, v in self._cpk_history.items()
                },
            })
            actions.append(f"경보: {alert['message']}")

        return actions

    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        worst_cpk = min(
            (h[-1] for h in self._cpk_history.values() if h),
            default=2.0,
        )
        cost_est = max(0.0, min(1.0, (self.CPK_GOOD - worst_cpk) / self.CPK_GOOD)) if worst_cpk < self.CPK_GOOD else 0.0
        viol = 1.0 if worst_cpk < self.CPK_WARNING else (0.5 if worst_cpk < self.CPK_GOOD else 0.0)
        out = {
            "agent": self.agent_id,
            "proposal": "품질 관점 대응",
            "inspection_mode": "전수" if worst_cpk < self.CPK_WARNING else "강화",
            "speed_recommendation": 70 if worst_cpk < self.CPK_WARNING else 90,
            "cpk_summary": {k: round(v[-1], 2) for k, v in self._cpk_history.items() if v},
            "scores": {
                "quality": 0.9, "delivery": 0.5,
                "cost": 0.4, "safety": 0.8,
            },
            "proposal_metrics": {
                "cost_estimate": round(cost_est, 4),
                "constraint_violation_total": viol,
                "worst_cpk": round(worst_cpk, 3),
                "expected_effect": round(0.5 + 0.5 * (worst_cpk / max(self.CPK_GOOD, 0.01)), 4),
                "quality_risk": round(1.0 - min(1.0, worst_cpk / self.CPK_GOOD), 4),
                "delivery_impact": 0.2,
                "material_impact": 0.1,
                "confidence": 0.82,
            },
        }
        merge_into_proposal(out)
        return out

    def execute_accepted_proposal(self, proposal: Dict):
        mode = proposal.get("inspection_mode", self._inspection_mode)
        self._inspection_mode = mode
        self.log_reasoning(f"검사 모드 변경: {mode}")

    def _calc_cpk(self, key: str) -> float:
        data = self._measurement_history.get(key, [])
        if len(data) < 10:
            return 2.0
        lsl, usl = self._spec_limits.get(key, (0, float("inf")))

        recent = data[-30:]
        mean = sum(recent) / len(recent)
        std = (sum((x - mean) ** 2 for x in recent) / len(recent)) ** 0.5
        if std < 0.0001:
            return 2.0

        cpu = (usl - mean) / (3 * std) if usl < float("inf") else 2.0
        cpl = (mean - lsl) / (3 * std) if lsl > -float("inf") else 2.0
        return min(cpu, cpl)

    def _cpk_trend(self, key: str) -> str:
        history = self._cpk_history.get(key, [])
        if len(history) < 5:
            return "안정"
        recent = history[-10:]
        if len(recent) < 3:
            return "안정"
        first_half = sum(recent[: len(recent) // 2]) / (len(recent) // 2)
        second_half = sum(recent[len(recent) // 2:]) / (len(recent) - len(recent) // 2)
        diff = second_half - first_half
        if diff < -self.CPK_TREND_THRESHOLD:
            return "하강"
        elif diff > self.CPK_TREND_THRESHOLD:
            return "상승"
        return "안정"

    def _check_run_rules(self, key: str) -> List[str]:
        data = self._measurement_history.get(key, [])
        if len(data) < 9:
            return []

        violations = []
        recent = data[-9:]
        mean = sum(data[-30:]) / min(30, len(data))
        std = (sum((x - mean) ** 2 for x in data[-30:]) / min(30, len(data))) ** 0.5
        if std < 0.0001:
            return []

        if all((x - mean) > 0 for x in recent[-7:]) or all((x - mean) < 0 for x in recent[-7:]):
            violations.append("규칙2: 연속 7점 한쪽")

        if len(recent) >= 9:
            diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
            if all(d > 0 for d in diffs[-6:]) or all(d < 0 for d in diffs[-6:]):
                violations.append("규칙3: 연속 6점 증가/감소")

        outside_2sigma = sum(1 for x in recent if abs(x - mean) > 2 * std)
        if outside_2sigma >= 2:
            violations.append("규칙4: 3점 중 2점 2σ 밖")

        return violations

    def get_agent_status(self) -> Dict:
        st = super().get_agent_status()
        st["sub_agent_views"] = dict(self._sub_views)
        st["inspection_mode"] = self._inspection_mode
        return st
