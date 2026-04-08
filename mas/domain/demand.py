"""
수요 모델: 고객 주문, 수요 예측, 긴급 주문 이벤트.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
import random
import math


class OrderPriority(Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class OrderStatus(Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FULFILLED = "FULFILLED"
    LATE = "LATE"


@dataclass
class CustomerOrder:
    order_id: str
    customer: str
    quantity: int
    due_date: str
    priority: OrderPriority = OrderPriority.NORMAL
    fulfilled: int = 0
    status: OrderStatus = OrderStatus.OPEN

    @property
    def remaining(self) -> int:
        return max(0, self.quantity - self.fulfilled)

    @property
    def fill_rate(self) -> float:
        return round(self.fulfilled / max(self.quantity, 1) * 100, 1)

    def ship(self, qty: int) -> int:
        actual = min(qty, self.remaining)
        self.fulfilled += actual
        if self.fulfilled >= self.quantity:
            self.status = OrderStatus.FULFILLED
        elif self.fulfilled > 0:
            self.status = OrderStatus.PARTIAL
        return actual


@dataclass
class DemandEvent:
    """시뮬레이션 중 발생하는 수요 이벤트."""
    trigger_cycle: int
    event_type: str          # "new_order", "quantity_change", "cancel"
    order: Optional[CustomerOrder] = None
    description: str = ""


class DemandModel:
    """수요 예측 및 변동성 추적."""

    def __init__(self):
        self.orders: List[CustomerOrder] = []
        self.events: List[DemandEvent] = []
        self.demand_history: List[float] = []
        self.forecast_history: List[float] = []
        self.forecast_errors: List[float] = []

        self._base_rate: float = 80.0  # 시간당 기본 수요(개)

    @property
    def total_demand(self) -> int:
        return sum(o.quantity for o in self.orders)

    @property
    def total_remaining(self) -> int:
        return sum(o.remaining for o in self.orders)

    @property
    def open_orders(self) -> List[CustomerOrder]:
        return [o for o in self.orders if o.status in (OrderStatus.OPEN, OrderStatus.PARTIAL)]

    def add_order(self, order: CustomerOrder):
        self.orders.append(order)

    def schedule_event(self, event: DemandEvent):
        self.events.append(event)

    def check_events(self, cycle: int) -> List[DemandEvent]:
        triggered = [e for e in self.events if e.trigger_cycle == cycle]
        self.events = [e for e in self.events if e.trigger_cycle != cycle]
        for ev in triggered:
            if ev.event_type == "new_order" and ev.order:
                self.add_order(ev.order)
        return triggered

    def record_actual_demand(self, qty_per_cycle: float):
        self.demand_history.append(qty_per_cycle)

    def forecast_demand_rate(self) -> float:
        """이동평균 기반 수요율 예측 (개/사이클)."""
        if len(self.demand_history) < 3:
            return self._base_rate / 80.0
        recent = self.demand_history[-5:]
        forecast = sum(recent) / len(recent)
        self.forecast_history.append(forecast)
        if len(self.demand_history) >= 5:
            actual = self.demand_history[-1]
            error = abs(actual - forecast)
            self.forecast_errors.append(error)
        return forecast

    @property
    def demand_std(self) -> float:
        """수요 변동성 (sigma_D) — 사이클 단위."""
        if len(self.demand_history) < 5:
            return 0.5
        recent = self.demand_history[-10:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        return max(0.1, math.sqrt(variance))

    @property
    def forecast_accuracy(self) -> float:
        if not self.forecast_errors or not self.forecast_history:
            return 0.85
        avg_error = sum(self.forecast_errors[-10:]) / len(self.forecast_errors[-10:])
        avg_forecast = sum(self.forecast_history[-10:]) / len(self.forecast_history[-10:])
        if avg_forecast < 0.01:
            return 0.85
        mape = avg_error / max(avg_forecast, 0.01)
        return round(max(0.5, min(0.99, 1.0 - mape)), 3)

    def get_avg_demand_per_cycle(self) -> float:
        if not self.demand_history:
            return 1.0
        return sum(self.demand_history[-10:]) / len(self.demand_history[-10:])

    def get_snapshot(self) -> dict:
        return {
            "total_demand": self.total_demand,
            "total_remaining": self.total_remaining,
            "open_orders": len(self.open_orders),
            "demand_std": round(self.demand_std, 3),
            "forecast_accuracy": self.forecast_accuracy,
            "avg_demand_per_cycle": round(self.get_avg_demand_per_cycle(), 3),
        }
