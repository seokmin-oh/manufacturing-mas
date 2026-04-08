"""
시나리오 기반 제조 환경 — Factory + 완제품 창고 + 수요 모델을 한데 묶는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

from .environment import Factory
from .inventory import FinishedGoodsWarehouse
from .demand import DemandModel
from ..scenario.loader import ScenarioConfig
from .production import ProductionOrder

if TYPE_CHECKING:
    pass


class ManufacturingEnvironment:
    """
    YAML 시나리오로 파라미터가 주입된 공장 환경.
    - 생산 시뮬레이션: 기존 Factory
    - 납기/서비스레벨: FinishedGoodsWarehouse
    - 고객 주문: DemandModel
    """

    def __init__(self, scenario: ScenarioConfig):
        self.scenario = scenario
        self.factory = Factory()
        self.warehouse = FinishedGoodsWarehouse(
            stock=scenario.warehouse_stock,
            safety_stock=scenario.warehouse_safety_stock,
            service_level_target=scenario.service_level_target,
            demand_std=scenario.demand_std,
            leadtime_mean=scenario.leadtime_mean,
            leadtime_std=scenario.leadtime_std,
            avg_demand_per_cycle=scenario.avg_demand_per_cycle,
        )
        self.demand = DemandModel()
        self._production_order: Optional[ProductionOrder] = None

        self._apply_scenario_materials()
        self._apply_scenario_sensors()

    def _apply_scenario_materials(self) -> None:
        sc = self.scenario
        if "강판" in self.factory.materials:
            self.factory.materials["강판"].stock = sc.material_steel_stock

    def _apply_scenario_sensors(self) -> None:
        """프레스(1번 공정) 센서 기준값을 시나리오에 맞춘다."""
        if not self.factory.line:
            return
        press = self.factory.line[0]
        sc = self.scenario.press_sensors
        for name, cfg in sc.items():
            if name in press.sensors:
                s = press.sensors[name]
                s.baseline = cfg.baseline
                s._value = cfg.baseline

    def on_good_finished_unit(self) -> None:
        """양품 1단위 입고 — Factory fg와 창고 이중 집계를 맞춘다."""
        self.warehouse.receive(1)
        if self.factory.fg_stock > 0:
            self.factory.fg_stock -= 1

    def process_shipments(self, cycle: int) -> None:
        sc = self.scenario
        interval = max(1, int(sc.shipment_interval))
        if cycle % interval != 0:
            return
        for order in list(self.demand.open_orders):
            if order.remaining <= 0:
                continue
            qty = min(sc.shipment_batch_size, order.remaining)
            if qty <= 0:
                continue
            self.warehouse.ship(order.customer, qty, cycle)
            order.ship(qty)

    def load_order(self, order: ProductionOrder) -> None:
        """MES 연동용 작업지시서(시나리오 러너에서 참조)."""
        self._production_order = order

    @property
    def cycle(self) -> int:
        return self.factory.cycle

    def get_merged_snapshot(self) -> Dict:
        """에이전트용 스냅샷 — Factory KPI에 창고 재고를 반영."""
        snap = self.factory.get_snapshot()
        snap["fg_stock"] = self.warehouse.stock
        snap["warehouse"] = self.warehouse.get_snapshot()
        return snap
