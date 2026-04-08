"""
시나리오 설정 시스템: YAML 파일에서 시뮬레이션 파라미터를 로드하여
environment, machines, runtime에 주입한다.
코드 변경 없이 다양한 제조 환경을 재현할 수 있다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def _get(d: dict, *keys, default=None):
    """Nested dict safe getter."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is default:
            return default
    return cur


@dataclass
class SensorConfig:
    baseline: float
    noise_std: float
    drift_rate: float = 0.0

    @classmethod
    def from_dict(cls, d: dict, defaults: "SensorConfig") -> "SensorConfig":
        return cls(
            baseline=d.get("baseline", defaults.baseline),
            noise_std=d.get("noise_std", defaults.noise_std),
            drift_rate=d.get("drift_rate", defaults.drift_rate),
        )


@dataclass
class EventProbabilities:
    new_order: float = 0.20
    vibration_spike: float = 0.15
    equipment_stabilize: float = 0.15
    material_arrival: float = 0.10
    agv_change: float = 0.10
    speed_recovery: float = 0.10
    drift_recovery_prob: float = 0.10
    drift_spike_prob: float = 0.05
    urgent_order_ratio: float = 0.40
    spike_magnitude: Tuple[float, float] = (0.3, 1.2)

    @classmethod
    def from_dict(cls, d: dict) -> "EventProbabilities":
        if not d:
            return cls()
        mag = d.get("spike_magnitude", [0.3, 1.2])
        return cls(
            new_order=d.get("new_order", 0.20),
            vibration_spike=d.get("vibration_spike", 0.15),
            equipment_stabilize=d.get("equipment_stabilize", 0.15),
            material_arrival=d.get("material_arrival", 0.10),
            agv_change=d.get("agv_change", 0.10),
            speed_recovery=d.get("speed_recovery", 0.10),
            drift_recovery_prob=d.get("drift_recovery_prob", 0.10),
            drift_spike_prob=d.get("drift_spike_prob", 0.05),
            urgent_order_ratio=d.get("urgent_order_ratio", 0.40),
            spike_magnitude=tuple(mag) if isinstance(mag, (list, tuple)) else (0.3, 1.2),
        )

    def cumulative_thresholds(self) -> List[Tuple[str, float]]:
        """이벤트 루프에서 사용할 누적 확률 임계값 목록."""
        events = [
            ("new_order", self.new_order),
            ("vibration_spike", self.vibration_spike),
            ("equipment_stabilize", self.equipment_stabilize),
            ("material_arrival", self.material_arrival),
            ("agv_change", self.agv_change),
            ("speed_recovery", self.speed_recovery),
        ]
        result = []
        cumulative = 0.0
        for name, prob in events:
            cumulative += prob
            result.append((name, cumulative))
        return result


@dataclass
class InitialOrder:
    order_id: str
    customer: str
    quantity: int
    due_date: str
    priority: str = "NORMAL"


@dataclass
class ScenarioConfig:
    """YAML 시나리오 파일 하나를 파싱한 설정 객체."""

    name: str = "default"
    description: str = ""

    # ── 센서 설정 ──
    press_sensors: Dict[str, SensorConfig] = field(default_factory=dict)
    weld_sensors: Dict[str, SensorConfig] = field(default_factory=dict)

    # ── 창고 & 재고 ──
    warehouse_stock: int = 120
    warehouse_safety_stock: int = 45
    service_level_target: float = 0.95
    demand_std: float = 8.0
    leadtime_mean: float = 4.5
    leadtime_std: float = 2.0
    avg_demand_per_cycle: float = 4.0

    # ── 자재 ──
    material_steel_stock: int = 850
    material_weld_wire: float = 12.5
    material_shield_gas: float = 95.0
    material_restock_threshold: int = 50

    # ── 수요 ──
    initial_orders: List[InitialOrder] = field(default_factory=list)
    order_quantities: List[int] = field(default_factory=lambda: [30, 50, 80, 100, 150])
    shipment_interval: int = 2
    shipment_batch_size: int = 3

    # ── 런타임 ──
    takt_sec: float = 2.5
    agent_intervals: Dict[str, float] = field(default_factory=dict)
    event_interval_range: Tuple[float, float] = (10, 30)

    # ── 이벤트 확률 ──
    events: EventProbabilities = field(default_factory=EventProbabilities)

    # ── 실행 제어 ──
    max_cycles: int = 0
    summary_interval: int = 20

    @classmethod
    def load(cls, path: str | Path) -> "ScenarioConfig":
        """YAML 파일에서 ScenarioConfig를 로드한다."""
        if yaml is None:
            raise ImportError("pyyaml이 필요합니다: pip install pyyaml")

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"시나리오 파일 없음: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw: dict = yaml.safe_load(f) or {}

        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict) -> "ScenarioConfig":
        cfg = cls()
        cfg.name = raw.get("name", "default")
        cfg.description = raw.get("description", "")

        # ── 센서 ──
        press_defaults = {
            "vibration": SensorConfig(1.80, 0.15, 0.10),
            "oil_temp": SensorConfig(42.0, 0.5, 0.03),
            "hydraulic_pressure": SensorConfig(180.0, 2.0, -0.08),
            "motor_current": SensorConfig(45.0, 1.0, 0.02),
        }
        press_raw = _get(raw, "sensors", "press") or {}
        for name, defaults in press_defaults.items():
            if name in press_raw:
                cfg.press_sensors[name] = SensorConfig.from_dict(press_raw[name], defaults)
            else:
                cfg.press_sensors[name] = defaults

        weld_defaults = {
            "weld_current": SensorConfig(280.0, 5.0, 0.0),
            "weld_voltage": SensorConfig(28.0, 0.3, 0.0),
            "wire_feed": SensorConfig(12.0, 0.2, 0.0),
            "gas_flow": SensorConfig(18.0, 0.5, 0.0),
        }
        weld_raw = _get(raw, "sensors", "weld") or {}
        for name, defaults in weld_defaults.items():
            if name in weld_raw:
                cfg.weld_sensors[name] = SensorConfig.from_dict(weld_raw[name], defaults)
            else:
                cfg.weld_sensors[name] = defaults

        # ── 창고 ──
        wh = raw.get("warehouse", {}) or {}
        cfg.warehouse_stock = wh.get("stock", 120)
        cfg.warehouse_safety_stock = wh.get("safety_stock", 45)
        cfg.service_level_target = wh.get("service_level_target", 0.95)
        cfg.demand_std = wh.get("demand_std", 8.0)
        cfg.leadtime_mean = wh.get("leadtime_mean", 4.5)
        cfg.leadtime_std = wh.get("leadtime_std", 2.0)
        cfg.avg_demand_per_cycle = wh.get("avg_demand_per_cycle", 4.0)

        # ── 자재 ──
        mat = raw.get("materials", {}) or {}
        cfg.material_steel_stock = mat.get("steel_stock", 850)
        cfg.material_weld_wire = mat.get("weld_wire", 12.5)
        cfg.material_shield_gas = mat.get("shield_gas", 95.0)
        cfg.material_restock_threshold = mat.get("restock_threshold", 50)

        # ── 수요 ──
        dem = raw.get("demand", {}) or {}
        cfg.shipment_interval = dem.get("shipment_interval", 2)
        cfg.shipment_batch_size = dem.get("shipment_batch_size", 3)
        cfg.order_quantities = dem.get("order_quantities", [30, 50, 80, 100, 150])

        orders_raw = dem.get("initial_orders", [])
        cfg.initial_orders = []
        for o in orders_raw:
            cfg.initial_orders.append(InitialOrder(
                order_id=o["order_id"],
                customer=o["customer"],
                quantity=o["quantity"],
                due_date=o.get("due_date", "2026-04-05"),
                priority=o.get("priority", "NORMAL"),
            ))

        if not cfg.initial_orders:
            cfg.initial_orders = [
                InitialOrder("CO-001", "현대자동차", 500, "2026-04-04", "NORMAL"),
                InitialOrder("CO-002", "기아자동차", 300, "2026-04-05", "NORMAL"),
            ]

        # ── 런타임 ──
        rt = raw.get("runtime", {}) or {}
        cfg.takt_sec = rt.get("takt_sec", 2.5)
        cfg.summary_interval = rt.get("summary_interval", 20)
        eir = rt.get("event_interval_range", [10, 30])
        cfg.event_interval_range = tuple(eir) if isinstance(eir, (list, tuple)) else (10, 30)

        ai = rt.get("agent_intervals", {}) or {}
        cfg.agent_intervals = {
            "EA": ai.get("EA", 2.0),
            "QA": ai.get("QA", 3.0),
            "SA": ai.get("SA", 5.0),
            "DA": ai.get("DA", 4.0),
            "IA": ai.get("IA", 3.0),
            "PA": ai.get("PA", 2.0),
        }

        # ── 이벤트 확률 ──
        cfg.events = EventProbabilities.from_dict(raw.get("events", {}))

        # ── 실행 제어 ──
        ex = raw.get("execution", {}) or {}
        cfg.max_cycles = ex.get("max_cycles", 0)

        return cfg

    def to_dict(self) -> dict:
        """JSON 직렬화용 딕셔너리 변환."""
        return {
            "name": self.name,
            "description": self.description,
            "warehouse_stock": self.warehouse_stock,
            "warehouse_safety_stock": self.warehouse_safety_stock,
            "service_level_target": self.service_level_target,
            "demand_std": self.demand_std,
            "leadtime_mean": self.leadtime_mean,
            "leadtime_std": self.leadtime_std,
            "takt_sec": self.takt_sec,
            "max_cycles": self.max_cycles,
            "event_interval_range": list(self.event_interval_range),
            "events": {
                "new_order": self.events.new_order,
                "vibration_spike": self.events.vibration_spike,
                "urgent_order_ratio": self.events.urgent_order_ratio,
                "spike_magnitude": list(self.events.spike_magnitude),
            },
        }


def list_scenarios(directory: str | Path = "scenarios") -> List[Dict[str, str]]:
    """scenarios/ 디렉터리의 YAML 파일 목록 반환."""
    if yaml is None:
        return []
    d = Path(directory)
    if not d.exists():
        return []
    result = []
    for f in sorted(d.glob("*.yaml")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            result.append({
                "file": f.name,
                "path": str(f),
                "name": raw.get("name", f.stem),
                "description": raw.get("description", ""),
            })
        except Exception:
            result.append({"file": f.name, "path": str(f), "name": f.stem, "description": "(파싱 오류)"})
    return result
