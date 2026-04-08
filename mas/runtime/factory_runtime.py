"""
공장 MAS 런타임 — 6공정 라인 + 6에이전트 실시간 구동
====================================================

## 스레드 모델 (daemon=True, 메인은 main.py 의 while 루프)
| 스레드명   | 역할 |
|------------|------|
| ENV-TICK   | `factory.run_cycle()` → `_snapshot` 갱신 → MQTT/API 푸시 → `_apply_dynamics` |
| EVENT-GEN  | 8~25초 간격 랜덤 이벤트(고장·신규주문·드리프트 등)로 시나리오 다양화 |
| AGENT-EA … PA | `AGENT_INTERVALS` 초마다 `run_cycle_with_router` (PA는 `_run_pa` 로 CNP 트리거) |

## 동시성
`_lock` 으로 스냅샷 읽기를 직렬화. 공장 객체 자체는 주로 ENV 스레드만 갱신하므로
에이전트는 스냅샷 **복사본**에 가까운 dict 를 읽는 패턴.

## 상수
`TAKT_SEC` — 설정 `MAS_TAKT_SEC`. `AGENT_INTERVALS` — 역할별 폴링 주기(초).
"""


from __future__ import annotations

import copy
import logging
import random
import threading
import time
from typing import Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

from ..domain.agent_snapshot import enrich_snapshot_for_agents
from ..domain.environment import Factory, CustomerOrder, OrderPriority
from ..domain.machines import MachineState
from ..agents.base_agent import BaseAgent
from ..agents.planning_agent import PlanningAgent
from ..messaging.message import Intent
from ..core import logger
from ..core.logger import C
from ..core.config import get_settings
from ..protocol.agent_protocol import run_cycle_with_router
from ..core.manufacturing_ids import AGENT_IDS

TAKT_SEC = get_settings().takt_sec
AGENT_INTERVALS = {"EA": 2, "QA": 3, "SA": 5, "DA": 4, "IA": 3, "PA": 2}
if set(AGENT_INTERVALS.keys()) != set(AGENT_IDS):
    raise RuntimeError("AGENT_INTERVALS keys must match manufacturing_ids.AGENT_IDS")
CUSTOMERS = ["현대자동차", "기아자동차", "GM코리아", "르노코리아", "한국GM"]

STATION_SHORT = {
    "WC-01": "블랭킹", "WC-02": "포밍", "WC-03": "용접",
    "WC-04": "열처리", "WC-05": "CNC", "WC-06": "조립",
}


class FactoryRuntime:
    """
    6공정 × 6에이전트 실시간 런타임.

    `start()` 이후 백그라운드 스레드가 돌고, `pop_logs()` 로 메인 스레드가
    터미널용 로그 버퍼를 비운다.
    """


    def __init__(
        self,
        factory: Factory,
        broker,
        agents: List[BaseAgent],
        llm=None,
        mqtt=None,
        api=None,
        decision_router=None,
    ):
        self.factory = factory
        self.broker = broker
        self.agents = {a.agent_id: a for a in agents}
        self.llm = llm
        self.mqtt = mqtt
        self.api = api
        self.decision_router = decision_router

        self._running = False
        self._lock = threading.Lock()
        self._snapshot: Optional[Dict] = None

        self._log_buffer: List[Tuple[str, str, str, str]] = []
        self._log_lock = threading.Lock()

        self.total_events = 0
        self.cnp_count = 0
        self._cnp_in_progress = False
        self.start_time = 0.0
        self._last_monitor_push = 0.0

    @property
    def uptime(self) -> float:
        return time.time() - self.start_time if self.start_time else 0

    def start(self):
        self._running = True
        self.start_time = time.time()
        logger.quiet = True

        threading.Thread(target=self._env_loop, daemon=True, name="ENV-TICK").start()
        threading.Thread(target=self._event_loop, daemon=True, name="EVENT-GEN").start()

        for aid in self.agents:
            threading.Thread(
                target=self._agent_loop, args=(aid,), daemon=True, name=f"AGENT-{aid}"
            ).start()

    def stop(self):
        self._running = False

    def _log(self, aid: str, msg: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        with self._log_lock:
            self._log_buffer.append((ts, aid, msg, level))
            if len(self._log_buffer) > 500:
                self._log_buffer = self._log_buffer[-500:]

    def pop_logs(self) -> List[Tuple[str, str, str, str]]:
        with self._log_lock:
            logs = list(self._log_buffer)
            self._log_buffer.clear()
        return logs

    # ── 환경 루프 ──────────────────────────────────────────

    def _env_loop(self):
        """생산 시뮬 한 스텝 + 스냅샷 캐시 + (옵션) SSE용 factory_tick 이벤트."""
        while self._running:
            result = self.factory.run_cycle()
            snap = copy.deepcopy(self.factory.get_snapshot())
            with self._lock:
                self._snapshot = snap


            if self.api and getattr(self.api, "push_event", None):
                t0 = time.time()
                if t0 - self._last_monitor_push >= 1.5:
                    self._last_monitor_push = t0
                    try:
                        self.api.push_event(
                            "factory_tick",
                            {
                                "cycle": snap.get("cycle"),
                                "clock": snap.get("clock"),
                                "avg_oee": snap.get("avg_oee"),
                                "fg_stock": snap.get("fg_stock"),
                                "shift": snap.get("shift"),
                            },
                        )
                    except Exception as e:
                        _log.debug("SSE push_event 실패: %s", e)

            product = result.get("product")
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
                except Exception as e:
                    _log.debug("MQTT publish 실패: %s", e)

            time.sleep(TAKT_SEC)

    def _apply_dynamics(self):
        """틱마다 소프트한 물리: 센서 회복, 고장 수리 확률, 자재 자동 보충 등."""
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

    # ── 이벤트 루프 ────────────────────────────────────────

    def _event_loop(self):
        """운영 드라마용 확률 이벤트. 가중치로 '정상보다 자주' 위기가 나오게 조정됨."""
        order_counter = len(self.factory.orders)

        while self._running:
            time.sleep(random.uniform(8, 25))
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

    # ── 에이전트 루프 ──────────────────────────────────────

    def _agent_loop(self, agent_id: str):
        """역할별 주기로 스냅샷 소비. PA 만 CNP 플래그 등 별도 처리(`_run_pa`)."""
        agent = self.agents[agent_id]

        interval = AGENT_INTERVALS.get(agent_id, 3)

        while self._running:
            time.sleep(interval)
            if not self._running:
                break

            with self._lock:
                snap = copy.copy(self._snapshot) if self._snapshot else None
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
                self._log(agent_id, f"오류: {e}", "ERROR")

    def _run_pa(self, pa: PlanningAgent, snap: Dict):
        """
        PA 전용 루프 한 번: 라우터+reason/act 후 `initiate_cnp` 가 True 이면
        `PlanningAgent.initiate_cnp` 로 타 에이전트 제안을 수집하고 라인 속도 등을 반영.
        `_cnp_in_progress` 로 CNP 중첩 호출을 막는다.
        """
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


# ── MES 스타일 터미널 디스플레이 ──────────────────────────────────

AGENT_KR = {"EA": "설비", "QA": "품질", "SA": "자재", "DA": "수요", "IA": "재고", "PA": "계획", "SYS": "시스템"}

LEVEL_ICON = {
    "ALERT": f"{C.RD}[!]", "EVENT": f"{C.MG}[*]", "CNP": f"{C.HD}[C]",
    "WARN": f"{C.YL}[!]", "SUCCESS": f"{C.GR}[+]", "ERROR": f"{C.RD}[X]",
    "INFO": f"{C.DM}[i]",
}


def print_factory_header():
    print(f"\n{C.BD}{C.CY}{'═' * 120}{C.RS}")
    print(f"  {C.BD}제조 MES 실시간 모니터링 — Multi AI Agent System{C.RS}  {C.DM}(Ctrl+C 종료){C.RS}")
    print(f"{C.BD}{C.CY}{'═' * 120}{C.RS}")
    print(f"  {C.BD}  시간   사이클 │ 블랭킹 포밍  용접  열처리 CNC  조립 │ "
          f"OEE  수율  │ 완성 폐기 │ 에이전트 활동{C.RS}")
    print(f"  {C.DM}{'─' * 115}{C.RS}")


def print_factory_row(rt: FactoryRuntime, logs: List):
    f = rt.factory
    snap = f.get_snapshot()
    if not snap:
        return

    cycle = f.cycle
    clock = snap.get("clock", "")
    shift = snap.get("shift", "")

    states = []
    for s in f.line:
        st = s.state.value
        if s.state == MachineState.RUNNING:
            oee_val = s.oee["oee"]
            if oee_val >= 0.85:
                states.append(f"{C.GR}{'●':>2}{C.RS}")
            elif oee_val >= 0.65:
                states.append(f"{C.YL}{'◐':>2}{C.RS}")
            else:
                states.append(f"{C.RD}{'○':>2}{C.RS}")
        elif s.state == MachineState.BREAKDOWN:
            states.append(f"{C.RD}{C.BD}{'X':>2}{C.RS}")
        elif s.state == MachineState.MAINTENANCE:
            states.append(f"{C.YL}{'M':>2}{C.RS}")
        elif s.state == MachineState.SETUP:
            states.append(f"{C.CY}{'S':>2}{C.RS}")
        else:
            states.append(f"{C.DM}{'·':>2}{C.RS}")

    station_str = " ".join(f"{s:>5}" for s in states)

    oees = [s.oee["oee"] for s in f.line]
    avg_oee = sum(oees) / len(oees)
    oee_c = C.GR if avg_oee >= 0.85 else (C.YL if avg_oee >= 0.65 else C.RD)

    total = f.total_produced + f.scrap_count
    fpy = f.total_produced / total if total > 0 else 1.0
    fpy_c = C.GR if fpy >= 0.95 else (C.YL if fpy >= 0.90 else C.RD)

    fg_c = C.GR if f.fg_stock > 20 else (C.YL if f.fg_stock > 5 else C.RD)
    scrap_c = C.GR if f.scrap_count < 10 else (C.YL if f.scrap_count < 30 else C.RD)

    print(
        f"  {C.DM}{clock}{C.RS} #{cycle:<5}│ "
        f"{station_str} │ "
        f"{oee_c}{avg_oee:5.1%}{C.RS} {fpy_c}{fpy:5.1%}{C.RS} │ "
        f"{fg_c}{f.fg_stock:4d}{C.RS} {scrap_c}{f.scrap_count:4d}{C.RS} │",
        end=""
    )

    if logs:
        ts, aid, msg, level = logs[0]
        ac = logger.AGENT_COLORS.get(aid, "")
        icon = LEVEL_ICON.get(level, f"{C.DM}[i]")
        name = AGENT_KR.get(aid, aid)
        print(f" {ac}{C.BD}[{name}]{C.RS}{icon}{C.RS} {msg[:55]}")
    else:
        print()

    for ts, aid, msg, level in logs[1:4]:
        ac = logger.AGENT_COLORS.get(aid, "")
        icon = LEVEL_ICON.get(level, f"{C.DM}[i]")
        name = AGENT_KR.get(aid, aid)
        print(f"  {' ' * 40}│ {' ' * 14}│ {' ' * 11}│ "
              f"{ac}{C.BD}[{name}]{C.RS}{icon}{C.RS} {msg[:55]}")


def print_factory_summary(rt: FactoryRuntime):
    f = rt.factory
    kpi = f.get_kpi_summary()

    print(f"\n  {C.BD}{C.CY}┌───────────────────────────────────────────────────────────────────────────────────┐{C.RS}")
    print(f"  {C.BD}{C.CY}│{C.RS}  {C.BD}공장 요약{C.RS} — "
          f"사이클 #{f.cycle} │ {f.shift_mgr.current.shift.value} │ "
          f"가동 {rt.uptime:.0f}초 │ 이벤트 {rt.total_events}건 │ CNP {rt.cnp_count}회"
          f"     {C.BD}{C.CY}│{C.RS}")
    print(f"  {C.BD}{C.CY}├───────────────────────────────────────────────────────────────────────────────────┤{C.RS}")

    print(f"  {C.BD}{C.CY}│{C.RS}  "
          f"생산: {C.BD}{kpi['total_produced']}{C.RS}개 │ "
          f"폐기: {C.BD}{kpi['scrap_count']}{C.RS}개 │ "
          f"재작업: {C.BD}{kpi['rework_count']}{C.RS}개 │ "
          f"FPY: {C.BD}{kpi['fpy']:.1%}{C.RS} │ "
          f"OEE: {C.BD}{kpi['avg_oee']:.1%}{C.RS} │ "
          f"납기율: {C.BD}{kpi['on_time_delivery']:.1%}{C.RS}"
          f"      {C.BD}{C.CY}│{C.RS}")

    bn = kpi.get("bottleneck", "")
    bn_name = STATION_SHORT.get(bn, bn)
    bn_oee = kpi.get("bottleneck_oee", 0)
    print(f"  {C.BD}{C.CY}│{C.RS}  "
          f"병목: {C.BD}{bn_name}{C.RS}(OEE {bn_oee:.1%}) │ "
          f"에너지: {C.BD}{kpi['total_energy_kwh']:.0f}{C.RS}kWh │ "
          f"단위에너지: {C.BD}{kpi['energy_per_unit']:.2f}{C.RS}kWh/개"
          f"                        {C.BD}{C.CY}│{C.RS}")

    print(f"  {C.BD}{C.CY}│{C.RS}  공정별 OEE: ", end="")
    for sid, oee_data in kpi.get("station_oee", {}).items():
        oee_val = oee_data.get("oee", 0)
        oc = C.GR if oee_val >= 0.85 else (C.YL if oee_val >= 0.65 else C.RD)
        name = STATION_SHORT.get(sid, sid)
        print(f"{oc}{name}:{oee_val:.0%}{C.RS} ", end="")
    print(f"  {C.BD}{C.CY}│{C.RS}")

    print(f"  {C.BD}{C.CY}└───────────────────────────────────────────────────────────────────────────────────┘{C.RS}")
