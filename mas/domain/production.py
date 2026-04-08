"""
생산 관리: 작업지시서(Production Order), 제품(Product), LOT, 측정값(Measurement).
MES(Manufacturing Execution System) 데이터 구조를 모방한다.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class ProductStatus(Enum):
    QUEUED = "대기"
    PRESSING = "프레스중"
    WELDING = "용접중"
    INSPECTING = "검사중"
    PASS = "양품"
    FAIL = "불량"
    SUSPECT = "보류"


@dataclass
class Measurement:
    name: str
    value: float
    unit: str
    nominal: float
    usl: float  # Upper Spec Limit
    lsl: float  # Lower Spec Limit

    @property
    def in_spec(self) -> bool:
        return self.lsl <= self.value <= self.usl

    @property
    def deviation(self) -> float:
        return round(self.value - self.nominal, 4)

    @property
    def margin_pct(self) -> float:
        """규격 여유율: 가장 가까운 규격 한계까지의 거리 비율."""
        tol_range = self.usl - self.lsl
        if tol_range < 1e-9:
            return 100.0 if self.in_spec else 0.0
        dist_to_upper = self.usl - self.value
        dist_to_lower = self.value - self.lsl
        nearest = min(dist_to_upper, dist_to_lower)
        return round(max(0, nearest / (tol_range / 2)) * 100, 1)


@dataclass
class Product:
    serial: str
    lot_id: str
    part_number: str
    cycle_num: int
    status: ProductStatus = ProductStatus.QUEUED
    measurements: Dict[str, Measurement] = field(default_factory=dict)
    press_sensors: Dict[str, float] = field(default_factory=dict)
    weld_sensors: Dict[str, float] = field(default_factory=dict)
    vision_confidence: float = 0.0
    defect_type: Optional[str] = None


@dataclass
class ProductionOrder:
    order_id: str
    part_number: str
    part_name: str
    target_qty: int
    material_spec: str
    material_lot: str
    customer: str
    due_date: str

    produced: int = 0
    good: int = 0
    defect: int = 0
    suspect: int = 0

    @property
    def completion_pct(self) -> float:
        return round(self.produced / max(self.target_qty, 1) * 100, 1)

    @property
    def yield_rate(self) -> float:
        return round(self.good / max(self.produced, 1) * 100, 2)

    @property
    def remaining(self) -> int:
        return max(0, self.target_qty - self.produced)


# 측정 규격 정의 (자동차 브레이크 패드 브래킷)
MEASUREMENT_SPECS = {
    "thickness": {
        "name": "두께",
        "unit": "mm",
        "nominal": 2.300,
        "usl": 2.350,
        "lsl": 2.250,
    },
    "burr_height": {
        "name": "버 높이",
        "unit": "mm",
        "nominal": 0.000,
        "usl": 0.150,
        "lsl": 0.000,
    },
    "flatness": {
        "name": "평탄도",
        "unit": "mm",
        "nominal": 0.000,
        "usl": 0.100,
        "lsl": 0.000,
    },
}
