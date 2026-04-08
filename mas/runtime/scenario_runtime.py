"""
시나리오 전용 런타임 — ManufacturingEnvironment + 6에이전트 + 도구/라우터 메트릭.
FactoryRuntime과 동일한 스레드 패턴이며, 시나리오 택트·에이전트 주기를 YAML에서 읽는다.

동시성: _snapshot, _log_buffer는 각각 threading.Lock으로 보호한다.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ..domain.agent_snapshot import enrich_snapshot_for_agents
from ..domain.environment import ProductStatus, CustomerOrder, OrderPriority
from ..domain.demand import CustomerOrder as DemandCustomerOrder, OrderPriority as DemandOrderPriority
from ..domain.machines import MachineState
from ..agents.base_agent import BaseAgent
from ..agents.planning_agent import PlanningAgent
from ..domain.manufacturing_env import ManufacturingEnvironment
from ..scenario.loader import ScenarioConfig
from ..core import logger
from ..protocol.agent_protocol import run_cycle_with_router

log = logging.getLogger(__name__)

STATION_SHORT = {
    "WC-01": "블랭킹", "WC-02": "포밍", "WC-03": "용접",
    "WC-04": "열처리", "WC-05": "CNC", "WC-06": "조립",
}

DEFAULT_AGENT_INTERVALS = {"EA": 2, "QA": 3, "SA": 5, "DA": 4, "IA": 3, "PA": 2}
CUSTOMERS = ["현대자동차", "기아자동차", "GM코리아", "르노코리아", "한국GM"]


class AgentRuntime:
    """시나리오 기반 6공정 × 6에이전트 배치 런타임."""

    def __init__(
        self,
        env: ManufacturingEnvironment,
        broker,
        agents: List[BaseAgent],
        llm=None,
        mqtt=None,
        tool_registry=None,
        decision_router=None,
        scenario: Optional[ScenarioConfig] = None,
    ):
        self.env = env
        self.factory = env.factory
        self.broker = broker
        self.agents = {a.agent_id: a for a in agents}
        self.llm = llm
        self.mqtt = mqtt
        self.tool_registry = tool_registry
        self.decision_router = decision_router
        self.scenario = scenario or env.scenario

        self._running = False
        self._lock = threading.Lock()
        self._snapshot: Optional[Dict] = None

        self._log_buffer: List[Tuple[str, str, str, str]] = []
        self._log_lock = threading.Lock()

        self.total_cycles = 0
        self.total_events = 0
        self.cnp_count = 0
        self._cnp_in_progress = False
        self.start_time = 0.0
        self._ss_breach_cycles = 0

    def _agent_interval(self, agent_id: str) -> float:
        ai = self.scenario.agent_intervals or {}
        if agent_id in ai:
            return float(ai[agent_id])
        return float(DEFAULT_AGENT_INTERVALS.get(agent_id, 3))

    def _takt(self) -> float:
        return max(0.1, float(self.scenario.takt_sec))

    @property
    def uptime(self) -> float:
        return time.time() - self.start_time if self.start_time else 0

    def start(self):
        self._running = True
        self.start_time = time.time()
        logger.quiet = True

        threading.Thread(target=self._env_loop, daemon=True, name="SC-ENV").start()
        threading.Thread(target=self._event_loop, daemon=True, name="SC-EVENT").start()

        for aid in self.agents:
            threading.Thread(
                target=self._agent_loop, args=(aid,), daemon=True, name=f"SC-AGENT-{aid}"
            ).start()

    def stop(self):
        self._running = False

    def _log(self, aid: str, msg: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        with self._log_lock:
            self._log_buffer.append((ts, aid, msg, level))
            if len(self._log_buffer) > 500:
                self._log_buffer = self._log_buffer[-500:]

    def _env_loop(self):
        while self._running:
            result = self.factory.run_cycle()
            product = result.get("product")
            if product and product.status == ProductStatus.GOOD:
                self.env.on_good_finished_unit()

            self.env.process_shipments(self.factory.cycle)
            self.env.warehouse.record_snapshot()
            if self.env.warehouse.ss_breach:
                self._ss_breach_cycles += 1

            snap = self.env.get_merged_snapshot()
            with self._lock:
                self._snapshot = snap
            self.total_cycles = self.factory.cycle

            if product and product.status.value == "폐기":
                station = f"WC-{product.current_station + 1:02d}"
                self._log("QA", f"폐기: {product.serial} at {STATION_SHORT.get(station, station)}", "WARN")

            self._apply_dynamics()

            if self.mqtt:
                try:
                    self.mqtt.publish_dict("factory/sensors", {
                        "cycle": snap["cycle"],
                        "stations": {
                            sid: {n: s["value"] for n, s in sd.get("sensors", {}).items()}
                            for sid, sd in snap.get("stations", {}).items()
                        },
                    })
                except Exception as ex:
                    log.debug("mqtt publish: %s", ex)

            time.sleep(self._takt())

    def _apply_dynamics(self):
        for station in self.factory.line:
            for sensor in station.sensors.values():
                if random.random() < 0.05:
                    sensor.recover(random.uniform(0.01, 0.05))

            if station.state == MachineState.BREAKDOWN and random.random() < 0.1:
                station.complete_repair()
                self._log("EA", f"{STATION_SHORT.get(station.station_id, station.station_id)} 수리 완료", "SUCCESS")

        for mat in self.factory.materials.values():
            if mat.stock < mat.safety_stock and random.random() < 0.15:
                qty = random.randint(200, 600)
                mat.stock += qty
                self._log("SA", f"{mat.name} 입고 +{qty}", "EVENT")
                self.total_events += 1

    def _event_loop(self):
        lo, hi = self.scenario.event_interval_range
        order_counter = len(self.factory.orders)
        while self._running:
            time.sleep(random.uniform(lo, hi))
            if not self._running:
                break

            event = random.choices(
                ["breakdown", "new_order", "tool_wear_spike", "quality_drift",
                 "material_arrival", "speed_recovery", "ambient_change"],
                weights=[0.08, 0.18, 0.12, 0.15, 0.15, 0.12, 0.20],
            )[0]

            if event == "breakdown":
                station = random.choice(self.factory.line)
                if station.state == MachineState.RUNNING:
                    repair = random.uniform(300, 1200)
                    station.trigger_breakdown(repair)
                    name = STATION_SHORT.get(station.station_id, station.station_id)
                    self._log("EA", f"[정지] {name} 고장 발생 (예상복구 {repair / 60:.0f}분)", "ALERT")
                    self.total_events += 1

            elif event == "new_order":
                order_counter += 1
                customer = random.choice(CUSTOMERS)
                qty = random.randint(100, 500)
                pri = OrderPriority.URGENT if random.random() < 0.2 else OrderPriority.NORMAL
                self.factory.orders.append(CustomerOrder(
                    f"PO-NEW-{order_counter:03d}", customer, "BRK-PAD-2026A",
                    qty, "2026-04-15", pri,
                ))
                d_pri = (
                    DemandOrderPriority.URGENT
                    if pri == OrderPriority.URGENT
                    else DemandOrderPriority.NORMAL
                )
                self.env.demand.add_order(DemandCustomerOrder(
                    f"SIM-{order_counter:03d}", customer, qty, "2026-04-15", d_pri,
                ))
                pri_kr = "긴급" if pri == OrderPriority.URGENT else "일반"
                self._log("DA", f"신규 주문: {customer} +{qty}개 ({pri_kr})", "EVENT")
                self.total_events += 1

            elif event == "tool_wear_spike":
                station = random.choice(self.factory.line)
                spike = random.uniform(50, 200)
                station.tool.current_life += int(spike)
                name = STATION_SHORT.get(station.station_id, station.station_id)
                self._log("EA", f"{name} 공구 급마모 +{spike:.0f}회분", "WARN")
                self.total_events += 1

            elif event == "quality_drift":
                station = random.choice(self.factory.line)
                sensor = random.choice(list(station.sensors.values()))
                drift = random.uniform(0.1, 0.5)
                sensor.inject_shock(drift)
                name = STATION_SHORT.get(station.station_id, station.station_id)
                self._log("QA", f"{name} {sensor.name} 드리프트 +{drift:.2f}", "WARN")
                self.total_events += 1

            elif event == "material_arrival":
                mat = random.choice(list(self.factory.materials.values()))
                qty = random.randint(300, 800)
                mat.stock += qty
                self._log("SA", f"{mat.name} 입고 +{qty}", "EVENT")
                self.total_events += 1

            elif event == "speed_recovery":
                station = random.choice(self.factory.line)
                if station.speed_pct < 100:
                    old = station.speed_pct
                    station.set_speed(min(100, old + random.randint(5, 15)))
                    name = STATION_SHORT.get(station.station_id, station.station_id)
                    self._log("EA", f"{name} 속도복원 {old}%→{station.speed_pct}%", "EVENT")
                    self.total_events += 1

            elif event == "ambient_change":
                self.factory.ambient_temp += random.gauss(0, 1.5)
                self.factory.ambient_temp = max(15, min(38, self.factory.ambient_temp))
                self._log("SYS", f"환경온도 변화: {self.factory.ambient_temp:.1f}°C", "INFO")
                self.total_events += 1

    def _agent_loop(self, agent_id: str):
        agent = self.agents[agent_id]
        interval = self._agent_interval(agent_id)

        while self._running:
            time.sleep(interval)
            if not self._running:
                break

            with self._lock:
                snap = self._snapshot
            if not snap:
                continue

            try:
                if agent_id == "PA":
                    self._run_pa(agent, snap)
                else:
                    decision = run_cycle_with_router(
                        agent, snap,
                        decision_router=self.decision_router,
                        log_fn=self._log,
                        broker=self.broker,
                    )
                    if decision:
                        pri = decision.get("priority", "LOW")
                        if pri in ("CRITICAL", "HIGH"):
                            summary = decision.get("type", "")
                            self._log(agent_id, f"{summary} [{pri}]", "ALERT")
                        elif pri == "MEDIUM":
                            self._log(agent_id, agent.reasoning_log[-1] if agent.reasoning_log else "", "WARN")
                        else:
                            if agent.reasoning_log:
                                self._log(agent_id, agent.reasoning_log[-1], "INFO")
                    else:
                        if agent.reasoning_log:
                            self._log(agent_id, agent.reasoning_log[-1], "INFO")
            except Exception as e:
                log.exception("agent %s: %s", agent_id, e)
                self._log(agent_id, f"오류: {e}", "ERROR")

    def _run_pa(self, pa: PlanningAgent, snap: Dict):
        decision = run_cycle_with_router(
            pa, snap,
            decision_router=self.decision_router,
            log_fn=self._log,
            broker=self.broker,
        )

        if decision and decision.get("initiate_cnp") and not self._cnp_in_progress:
            self._cnp_in_progress = True
            self._log("PA", f"CNP #{pa.cnp_count + 1} 시작: {decision.get('cnp_reason', '')}", "CNP")

            agents_list = [a for a in self.agents.values() if a.agent_id != "PA"]
            strategy = pa.initiate_cnp(agents_list, enrich_snapshot_for_agents(dict(snap)))

            if strategy:
                self.cnp_count = pa.cnp_count
                speed = strategy.get("target_speed_pct", 100)
                for station in self.factory.line:
                    station.set_speed(speed)
                self._log("PA", f"[완료] CNP #{pa.cnp_count} — 속도 {speed}%", "SUCCESS")
            self._cnp_in_progress = False

        elif decision:
            if pa.reasoning_log:
                self._log("PA", pa.reasoning_log[-1], "INFO")
        else:
            if pa.reasoning_log:
                self._log("PA", pa.reasoning_log[-1], "INFO")

    def get_results(self) -> Dict[str, Any]:
        wh = self.env.warehouse
        broker_metrics = {}
        if self.broker and hasattr(self.broker, "metrics"):
            broker_metrics = self.broker.metrics.to_dict()

        tools_out: Dict[str, Any] = {}
        if self.tool_registry and hasattr(self.tool_registry, "get_metrics"):
            tools_out = self.tool_registry.get_metrics()

        dr_out: Dict[str, Any] = {}
        if self.decision_router and hasattr(self.decision_router, "metrics"):
            dr_out = self.decision_router.metrics.to_dict()

        return {
            "total_cycles": self.total_cycles,
            "total_events": self.total_events,
            "cnp_count": self.cnp_count,
            "uptime_sec": round(time.time() - self.start_time, 1) if self.start_time else 0.0,
            "warehouse": {
                "final_stock": wh.stock,
                "safety_stock": wh.safety_stock,
                "service_level": wh.service_level,
                "total_shipped": wh.total_shipped,
                "total_requested": wh.total_requested,
                "ss_breach_count": self._ss_breach_cycles,
            },
            "broker": {
                "total_published": broker_metrics.get("total_published", 0),
                "total_delivered": broker_metrics.get("total_delivered", 0),
                "avg_latency_ms": broker_metrics.get("avg_latency_ms", 0.0),
                "total_dlq": broker_metrics.get("total_dlq", 0),
            },
            "tools": tools_out,
            "decision_router": dr_out,
        }
