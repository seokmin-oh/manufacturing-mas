"""
실제 자동차 부품 공장 환경 시뮬레이션
=====================================

## 책임
- **생산 흐름**: `WorkCenter` 6개( `create_production_line` ) + 공정 간 `WIPBuffer`.
- **제품 엔티티**: `Product` — 공정 인덱스·측정값·불량 코드 추적.
- **자재·주문**: `Material`, `CustomerOrder` — SA/DA/IA/PA 판단의 입력.
- **시간·교대**: `ShiftManager` — 스킬·피로 계수로 간접적으로 품질/속도에 영향(시뮬).
- **스냅샷**: `get_snapshot()` 이 에이전트·API가 보는 **단일 진실 소스** 역할.

## 호출 패턴
`FactoryRuntime._env_loop` 가 `TAKT_SEC` 마다 `run_cycle()` 을 호출하고,
직후 `get_snapshot()` 으로 캐시를 갱신한다. 에이전트는 그 캐시만 읽는다(동시성은 런타임 락).
"""


from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .machines import (
    WorkCenter, MachineState, create_production_line, SensorReading,
)
from .business_events import BusinessEventStore, BusinessEventType
from .plant_data_model import (
    DEFAULT_CELL_ID,
    DEFAULT_LINE_ID,
    DEFAULT_PLANT_ID,
    DEFAULT_SITE_ID,
    enrich_station_sensors,
    make_resource_id,
    plant_header,
)


# ── 교대 근무 ─────────────────────────────────────────────────────

class Shift(Enum):
    DAY_A = "주간A"
    DAY_B = "주간B"
    NIGHT = "야간"


@dataclass
class ShiftInfo:
    shift: Shift
    operator_skill: float  # 0.8 ~ 1.2 (1.0 = 표준)
    fatigue_factor: float  # 시간 경과에 따른 피로도
    hour_in_shift: int = 0

    @property
    def effective_factor(self) -> float:
        fatigue = 1.0 + self.fatigue_factor * (self.hour_in_shift / 8)
        return self.operator_skill * fatigue


SHIFT_PROFILES = {
    Shift.DAY_A: {"skill": 1.05, "fatigue": 0.03},
    Shift.DAY_B: {"skill": 0.95, "fatigue": 0.05},
    Shift.NIGHT: {"skill": 0.90, "fatigue": 0.08},
}


class ShiftManager:
    def __init__(self):
        self._shifts = list(Shift)
        self._current_idx = 0
        self._hour_in_shift = 0
        self._shift_cycle_count = 0
        self.shift_changes = 0

    @property
    def current(self) -> ShiftInfo:
        s = self._shifts[self._current_idx]
        p = SHIFT_PROFILES[s]
        return ShiftInfo(s, p["skill"], p["fatigue"], self._hour_in_shift)

    def advance(self, cycles_per_hour: float = 40):
        self._shift_cycle_count += 1
        self._hour_in_shift = int(self._shift_cycle_count / cycles_per_hour)
        if self._hour_in_shift >= 8:
            self._current_idx = (self._current_idx + 1) % len(self._shifts)
            self._hour_in_shift = 0
            self._shift_cycle_count = 0
            self.shift_changes += 1


# ── 자재 관리 ─────────────────────────────────────────────────────

@dataclass
class Material:
    name: str
    stock: int
    safety_stock: int
    consumption_per_unit: float
    lead_time_days: float
    unit_cost: float
    supplier: str
    on_order: int = 0

    @property
    def days_of_supply(self) -> float:
        daily_usage = self.consumption_per_unit * 400  # 약 400개/일
        return self.stock / daily_usage if daily_usage > 0 else float("inf")

    @property
    def needs_reorder(self) -> bool:
        return self.stock <= self.safety_stock * 1.5


# ── 수요 & 주문 ───────────────────────────────────────────────────

class OrderPriority(Enum):
    URGENT = "긴급"
    NORMAL = "일반"
    LOW = "저"


@dataclass
class CustomerOrder:
    order_id: str
    customer: str
    part: str
    quantity: int
    due_date: str
    priority: OrderPriority
    delivered: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.quantity - self.delivered)

    @property
    def is_complete(self) -> bool:
        return self.delivered >= self.quantity


# ── 제품 (다공정 추적) ────────────────────────────────────────────

class ProductStatus(Enum):
    IN_PROCESS = "가공중"
    GOOD = "양품"
    REWORK = "재작업"
    SCRAP = "폐기"
    HOLD = "보류"


@dataclass
class Product:
    serial: str
    lot: str
    current_station: int = 0  # 0~5 (공정 인덱스)
    status: ProductStatus = ProductStatus.IN_PROCESS
    measurements: Dict[str, Dict[str, float]] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    defect_codes: List[str] = field(default_factory=list)


# ── WIP 버퍼 ──────────────────────────────────────────────────────

@dataclass
class WIPBuffer:
    """공정 간 WIP 버퍼."""
    station_from: int
    station_to: int
    items: List[Product] = field(default_factory=list)
    max_capacity: int = 50

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def utilization(self) -> float:
        return self.count / self.max_capacity if self.max_capacity > 0 else 0

    def push(self, product: Product):
        if self.count < self.max_capacity:
            self.items.append(product)

    def pop(self) -> Optional[Product]:
        return self.items.pop(0) if self.items else None


# ── 공장 환경 (메인 클래스) ────────────────────────────────────────

class Factory:
    """
    자동차 부품 공장 전체 시뮬레이션.
    6공정 라인 + 교대근무 + 자재 + 수요 + WIP + KPI.

    OEE·스크랩·출하 등 KPI 집계는 주로 `run_cycle` 및 보조 메서드에서 누적된다.
    """

    def __init__(self):
        # 생산 라인 (6공정) — WC-01..06, 유형은 machines 모듈 참고
        self.line: List[WorkCenter] = create_production_line()


        # WIP 버퍼 (공정 간 5개)
        self.wip_buffers: List[WIPBuffer] = [
            WIPBuffer(i, i + 1, max_capacity=30) for i in range(5)
        ]

        # 완제품 창고
        self.finished_goods: List[Product] = []
        self.fg_stock = 0
        self.scrap_count = 0
        self.rework_count = 0
        self.total_produced = 0

        # 교대근무
        self.shift_mgr = ShiftManager()

        # 자재
        self.materials: Dict[str, Material] = {
            "강판": Material("SPCC 강판 2.3t", 5000, 1000, 1.0, 3.0, 2500, "포스코"),
            "용접봉": Material("용접봉 Φ1.2", 8000, 2000, 4.0, 2.0, 150, "대동금속"),
            "볼트": Material("M8 볼트 세트", 12000, 3000, 6.0, 1.5, 80, "삼성볼트"),
            "도장": Material("전착 도료 15L", 200, 40, 0.05, 5.0, 45000, "KCC"),
            "절삭유": Material("수용성 절삭유", 500, 100, 0.02, 4.0, 12000, "한화솔루션"),
        }

        # 수요
        self.orders: List[CustomerOrder] = []
        self._init_orders()

        # 환경 변수
        self.ambient_temp = 22.0 + random.gauss(0, 1)
        self.humidity = 55.0 + random.gauss(0, 5)

        # 카운터
        self.cycle = 0
        self.sim_time_sec = 0.0
        self.start_ts = time.time()

        # 품질 이력
        self.hourly_yield: List[float] = []
        self.hourly_oee: List[float] = []
        self.hourly_throughput: List[int] = []

        # 현재 사이클 제품
        self._current_product: Optional[Product] = None
        self._product_counter = 0
        self._lot_counter = 1

        # 비즈니스 이벤트 (스냅샷과 분리된 전이 로그)
        self.event_store = BusinessEventStore()

    def _init_orders(self):
        customers = [
            ("현대자동차", "HMC"), ("기아자동차", "KIA"),
            ("GM코리아", "GMK"), ("르노코리아", "RNK"),
        ]
        for i, (name, code) in enumerate(customers):
            pri = OrderPriority.URGENT if i == 0 else OrderPriority.NORMAL
            self.orders.append(CustomerOrder(
                f"PO-{code}-{2026:04d}-{i + 1:03d}",
                name, "BRK-PAD-2026A",
                random.randint(300, 800),
                f"2026-04-{10 + i * 3:02d}",
                pri,
            ))

    # ── 메인 사이클 ──────────────────────────────────────────

    def run_cycle(self) -> Dict:
        """한 사이클 실행: 6공정 순차 통과 + 품질 판정."""
        self.cycle += 1
        self.sim_time_sec += self.line[0].cycle_time_sec
        shift = self.shift_mgr.current
        self.shift_mgr.advance()

        self._update_ambient()

        self.event_store.emit(
            BusinessEventType.FACTORY_TICK,
            self.cycle,
            self.sim_time_sec,
            {"cycle": self.cycle},
        )

        self._product_counter += 1
        if self._product_counter % 200 == 1:
            self._lot_counter += 1
        product = Product(
            serial=f"SN-{self._product_counter:06d}",
            lot=f"LOT-{self._lot_counter:04d}",
        )
        self.event_store.emit(
            BusinessEventType.WORK_STARTED,
            self.cycle,
            self.sim_time_sec,
            {"serial": product.serial, "lot": product.lot},
            lot_id=product.lot,
        )

        all_readings: Dict[str, Dict[str, SensorReading]] = {}

        for idx, station in enumerate(self.line):
            if station.state in (MachineState.BREAKDOWN, MachineState.MAINTENANCE):
                product.status = ProductStatus.HOLD
                product.defect_codes.append(f"{station.station_id}_정지")
                break

            readings = station.execute_cycle(
                shift_factor=shift.effective_factor,
                ambient_temp=self.ambient_temp,
            )
            all_readings[station.station_id] = readings

            product.measurements[station.station_id] = {
                name: r.value for name, r in readings.items()
            }
            product.current_station = idx

            is_good = self._judge_quality(station, readings, product)
            station.record_quality(is_good)
            self.event_store.emit(
                BusinessEventType.INSPECTION_VERDICT,
                self.cycle,
                self.sim_time_sec,
                {
                    "serial": product.serial,
                    "station": station.station_id,
                    "pass": is_good,
                },
                station_id=station.station_id,
                lot_id=product.lot,
            )

            if not is_good and product.status == ProductStatus.IN_PROCESS:
                if random.random() < 0.3:
                    product.status = ProductStatus.REWORK
                    self.rework_count += 1
                    product.defect_codes.append(f"{station.station_id}_재작업")
                else:
                    product.status = ProductStatus.SCRAP
                    self.scrap_count += 1
                    product.defect_codes.append(f"{station.station_id}_폐기")
                self.event_store.emit(
                    BusinessEventType.QUALITY_ESCALATION,
                    self.cycle,
                    self.sim_time_sec,
                    {
                        "serial": product.serial,
                        "status": product.status.value,
                        "defect_codes": list(product.defect_codes),
                    },
                    station_id=station.station_id,
                    lot_id=product.lot,
                )
                break

        if product.status == ProductStatus.IN_PROCESS:
            product.status = ProductStatus.GOOD
            product.end_time = time.time()
            self.fg_stock += 1
            self.total_produced += 1
            self.finished_goods.append(product)
            self.event_store.emit(
                BusinessEventType.WORK_COMPLETE,
                self.cycle,
                self.sim_time_sec,
                {"serial": product.serial, "lot": product.lot, "status": "GOOD"},
                lot_id=product.lot,
            )
            self._process_shipments()

        self._consume_materials()
        self._current_product = product

        self._record_hourly()

        return {
            "cycle": self.cycle,
            "product": product,
            "readings": all_readings,
            "shift": shift,
        }

    def _judge_quality(
        self, station: WorkCenter, readings: Dict[str, SensorReading], product: Product
    ) -> bool:
        """공정별 품질 판정 — 센서 값 기반 확률적 불량 생성."""
        bad_count = sum(1 for r in readings.values() if r.status == "CRITICAL")
        warn_count = sum(1 for r in readings.values() if r.status == "WARNING")

        defect_prob = bad_count * 0.4 + warn_count * 0.08
        defect_prob += station.tool.wear_rate * 0.05
        defect_prob = min(0.8, defect_prob)

        return random.random() > defect_prob

    def _consume_materials(self):
        for mat in self.materials.values():
            consumed = int(mat.consumption_per_unit)
            remainder = mat.consumption_per_unit - consumed
            if random.random() < remainder:
                consumed += 1
            mat.stock = max(0, mat.stock - consumed)

    def _process_shipments(self):
        for order in self.orders:
            if order.is_complete:
                continue
            if self.fg_stock > 0:
                ship = min(random.randint(1, 3), self.fg_stock, order.remaining)
                order.delivered += ship
                self.fg_stock -= ship

    def _update_ambient(self):
        self.ambient_temp += random.gauss(0, 0.1)
        self.ambient_temp = max(15, min(35, self.ambient_temp))
        self.humidity += random.gauss(0, 0.5)
        self.humidity = max(30, min(80, self.humidity))

    def _record_hourly(self):
        if self.cycle % 40 == 0:
            total = sum(s.good_count + s.defect_count for s in self.line)
            good = sum(s.good_count for s in self.line)
            self.hourly_yield.append(good / total if total > 0 else 1.0)

            oees = [s.oee["oee"] for s in self.line]
            self.hourly_oee.append(sum(oees) / len(oees))
            self.hourly_throughput.append(self.total_produced)

    # ── 스냅샷 (에이전트용) ──────────────────────────────────

    def get_snapshot(self) -> Dict:
        """에이전트가 참조할 공장 전체 스냅샷."""
        shift = self.shift_mgr.current
        hours = int(self.sim_time_sec / 3600)
        minutes = int((self.sim_time_sec % 3600) / 60)
        clock = f"{8 + hours:02d}:{minutes:02d}:{int(self.sim_time_sec % 60):02d}"

        stations = {}
        for s in self.line:
            station_data = s.get_status()
            sensor_data = {}
            for name, sensor in s.sensors.items():
                sensor_data[name] = {
                    "value": sensor._value,
                    "ma": sensor.ma,
                    "slope": sensor.slope,
                    "std": sensor.std,
                    "unit": sensor.unit,
                }
            station_data["sensors"] = enrich_station_sensors(
                s.station_id,
                sensor_data,
                cycle=self.cycle,
                sim_time_sec=self.sim_time_sec,
                site_id=DEFAULT_SITE_ID,
                line_id=DEFAULT_LINE_ID,
            )
            station_data["resource_id"] = make_resource_id(
                s.station_id, site_id=DEFAULT_SITE_ID, line_id=DEFAULT_LINE_ID
            )
            stations[s.station_id] = station_data

        total_demand = sum(o.remaining for o in self.orders)
        total_delivered = sum(o.delivered for o in self.orders)

        materials_snap = {}
        for name, m in self.materials.items():
            ds = m.days_of_supply
            days_supply_json = None if not math.isfinite(ds) else round(ds, 1)
            materials_snap[name] = {
                "sku": name,
                "uom": "EA",
                "stock": m.stock,
                "safety_stock": m.safety_stock,
                "days_supply": days_supply_json,
                "needs_reorder": m.needs_reorder,
                "on_order": m.on_order,
                "supplier_id": m.supplier,
            }

        wip = [{"from": b.station_from, "to": b.station_to,
                 "count": b.count, "util": round(b.utilization, 2)}
               for b in self.wip_buffers]

        line_oee = [s.oee for s in self.line]
        avg_oee = sum(o["oee"] for o in line_oee) / len(line_oee)

        return {
            "plant": plant_header(
                sim_time_sec=self.sim_time_sec,
                cycle=self.cycle,
                site_id=DEFAULT_SITE_ID,
                plant_id=DEFAULT_PLANT_ID,
                line_id=DEFAULT_LINE_ID,
                cell_id=DEFAULT_CELL_ID,
            ),
            "cycle": self.cycle,
            "clock": clock,
            "shift": shift.shift.value,
            "shift_skill": round(shift.effective_factor, 3),
            "ambient_temp": round(self.ambient_temp, 1),
            "humidity": round(self.humidity, 1),
            "stations": stations,
            "fg_stock": self.fg_stock,
            "total_produced": self.total_produced,
            "scrap_count": self.scrap_count,
            "rework_count": self.rework_count,
            "total_demand": total_demand,
            "total_delivered": total_delivered,
            "materials": materials_snap,
            "wip": wip,
            "line_oee": line_oee,
            "avg_oee": round(avg_oee, 4),
            "orders": [
                {
                    "id": o.order_id,
                    "customer": o.customer,
                    "part": o.part,
                    "qty": o.quantity,
                    "delivered": o.delivered,
                    "remaining": o.remaining,
                    "priority": o.priority.value,
                    "due_date": o.due_date,
                }
                for o in self.orders
            ],
            "business_events": self.event_store.tail(48),
        }

    # ── 공장 KPI 요약 ────────────────────────────────────────

    def get_kpi_summary(self) -> Dict:
        total_items = sum(s.good_count + s.defect_count for s in self.line)
        total_good = sum(s.good_count for s in self.line)
        fpy = total_good / total_items if total_items > 0 else 1.0

        oees = [s.oee for s in self.line]
        bottleneck = min(self.line, key=lambda s: s.oee["oee"])

        total_energy = sum(s.energy_kwh for s in self.line)
        energy_per_unit = total_energy / self.total_produced if self.total_produced > 0 else 0

        total_demand = sum(o.quantity for o in self.orders)
        total_delivered = sum(o.delivered for o in self.orders)
        on_time_rate = total_delivered / total_demand if total_demand > 0 else 1.0

        return {
            "cycle": self.cycle,
            "total_produced": self.total_produced,
            "fg_stock": self.fg_stock,
            "scrap_count": self.scrap_count,
            "rework_count": self.rework_count,
            "fpy": round(fpy, 4),
            "avg_oee": round(sum(o["oee"] for o in oees) / len(oees), 4),
            "bottleneck": bottleneck.station_id,
            "bottleneck_oee": bottleneck.oee["oee"],
            "total_energy_kwh": round(total_energy, 1),
            "energy_per_unit": round(energy_per_unit, 3),
            "on_time_delivery": round(on_time_rate, 4),
            "station_oee": {s.station_id: s.oee for s in self.line},
            "shift_changes": self.shift_mgr.shift_changes,
        }


def __getattr__(name: str):
    if name == "ManufacturingEnvironment":
        from .manufacturing_env import ManufacturingEnvironment
        return ManufacturingEnvironment
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
