"""
완제품 재고 모델: 창고, 동적 안전재고, 서비스레벨 추적.
"""

from dataclasses import dataclass, field
from typing import List, Dict
import math


@dataclass
class ShipmentRecord:
    cycle: int
    customer: str
    requested: int
    shipped: int
    shortfall: int


@dataclass
class FinishedGoodsWarehouse:
    """완제품 창고 — 안전재고 관리 및 서비스레벨 추적."""

    stock: int = 50
    safety_stock: int = 45

    service_level_target: float = 0.95

    # 불확실성 파라미터 (에이전트가 갱신)
    demand_std: float = 0.5
    leadtime_mean: float = 3.0       # 사이클 단위
    leadtime_std: float = 0.5
    avg_demand_per_cycle: float = 1.0

    # 이력
    stock_history: List[int] = field(default_factory=list)
    ss_history: List[int] = field(default_factory=list)
    service_level_history: List[float] = field(default_factory=list)
    shipments: List[ShipmentRecord] = field(default_factory=list)

    # 집계
    total_requested: int = 0
    total_shipped: int = 0

    def receive(self, qty: int):
        """생산 완료품 입고."""
        self.stock += qty

    def ship(self, customer: str, qty: int, cycle: int) -> int:
        """출하 요청 처리. 실제 출하량 반환."""
        actual = min(qty, self.stock)
        self.stock -= actual
        shortfall = qty - actual
        self.total_requested += qty
        self.total_shipped += actual
        self.shipments.append(ShipmentRecord(
            cycle=cycle, customer=customer,
            requested=qty, shipped=actual, shortfall=shortfall,
        ))
        return actual

    @property
    def service_level(self) -> float:
        if self.total_requested == 0:
            return 1.0
        return round(self.total_shipped / self.total_requested, 4)

    @property
    def stock_above_ss(self) -> int:
        return self.stock - self.safety_stock

    @property
    def ss_breach(self) -> bool:
        return self.stock < self.safety_stock

    def recalculate_safety_stock(self) -> dict:
        """
        동적 안전재고 재계산.
        SS = z * sqrt(LT * sigma_D^2 + d_avg^2 * sigma_LT^2)
        """
        z = _z_score(self.service_level_target)
        lt = self.leadtime_mean
        sig_d = self.demand_std
        d_avg = self.avg_demand_per_cycle
        sig_lt = self.leadtime_std

        demand_component = lt * (sig_d ** 2)
        supply_component = (d_avg ** 2) * (sig_lt ** 2)
        ss_raw = z * math.sqrt(demand_component + supply_component)
        new_ss = max(5, round(ss_raw))

        old_ss = self.safety_stock
        self.safety_stock = new_ss

        return {
            "old_ss": old_ss,
            "new_ss": new_ss,
            "z_score": round(z, 3),
            "demand_component": round(demand_component, 3),
            "supply_component": round(supply_component, 3),
            "formula_inputs": {
                "service_level": self.service_level_target,
                "demand_std": round(sig_d, 3),
                "leadtime_mean": round(lt, 3),
                "leadtime_std": round(sig_lt, 3),
                "avg_demand": round(d_avg, 3),
            },
        }

    def record_snapshot(self):
        self.stock_history.append(self.stock)
        self.ss_history.append(self.safety_stock)
        self.service_level_history.append(self.service_level)

    def get_snapshot(self) -> dict:
        return {
            "stock": self.stock,
            "safety_stock": self.safety_stock,
            "service_level": self.service_level,
            "ss_breach": self.ss_breach,
            "stock_above_ss": self.stock_above_ss,
            "total_requested": self.total_requested,
            "total_shipped": self.total_shipped,
        }


def _z_score(service_level: float) -> float:
    """근사 z-score (scipy 없이)."""
    p = max(0.50, min(0.999, service_level))
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    return round(z, 4)
