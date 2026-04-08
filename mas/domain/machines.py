"""
자동차 부품 공장 워크센터(공정) 모델
====================================

## 구성
- **WorkCenter**: `station_id`(WC-01…), `station_type`(PRESS/WELD/…), 센서 dict, OEE, 속도%, 공구.
- **SensorReading**: 값·단위·상태 — `inject_shock`, `recover` 등으로 시뮬 노이즈.
- **create_production_line()**: 6공정 리스트를 고정 순서로 생성. ID 는 `manufacturing_ids.STATION_IDS` 와 일치해야 함.

## PdM 과의 연결
`station_type` 이 `mas/intelligence/equipment_predictive_models.py` 의 키와 대응.
"""


from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── 상태 / 데이터 클래스 ──────────────────────────────────────────

class MachineState(Enum):
    RUNNING = "가동"
    IDLE = "대기"
    SETUP = "셋업"
    BREAKDOWN = "고장"
    MAINTENANCE = "정비"
    WARMUP = "워밍업"


@dataclass
class SensorReading:
    name: str
    value: float
    unit: str
    timestamp: float = field(default_factory=time.time)
    status: str = "NORMAL"  # NORMAL / WARNING / CRITICAL


@dataclass
class ToolWear:
    """공구 마모 모델 — 마모 커브는 실제 S-커브(초기안정→선형마모→급격마모)."""
    current_life: int = 0
    max_life: int = 5000
    wear_rate: float = 0.0
    region: str = "초기안정"

    def advance(self, cycles: int = 1):
        self.current_life += cycles
        ratio = self.current_life / self.max_life
        if ratio < 0.3:
            self.wear_rate = 0.2 + random.gauss(0, 0.02)
            self.region = "초기안정"
        elif ratio < 0.8:
            self.wear_rate = 0.5 + 0.3 * (ratio - 0.3) / 0.5 + random.gauss(0, 0.03)
            self.region = "선형마모"
        else:
            self.wear_rate = 0.8 + 1.5 * (ratio - 0.8) / 0.2 + random.gauss(0, 0.05)
            self.region = "급격마모"
        self.wear_rate = max(0, min(self.wear_rate, 2.5))

    @property
    def remaining_pct(self) -> float:
        return max(0, 1 - self.current_life / self.max_life) * 100

    def needs_change(self) -> bool:
        return self.current_life >= self.max_life * 0.9

    def reset(self):
        self.current_life = 0
        self.wear_rate = 0.0
        self.region = "초기안정"


# ── 현실적 센서 시뮬레이터 ─────────────────────────────────────────

class RealisticSensor:
    """
    현실적 센서 시뮬레이션:
    - 자기상관 (이전 값에 의존)
    - 워밍업 효과
    - 공구 마모 영향
    - 교대 근무 영향
    - 환경 영향 (온도/습도)
    """

    def __init__(
        self,
        name: str,
        baseline: float,
        noise_std: float,
        unit: str = "",
        warn_threshold: float = float("inf"),
        critical_threshold: float = float("inf"),
        autocorrelation: float = 0.85,
        drift_per_cycle: float = 0.0,
    ):
        self.name = name
        self.baseline = baseline
        self.noise_std = noise_std
        self.unit = unit
        self.warn_threshold = warn_threshold
        self.critical_threshold = critical_threshold
        self.autocorrelation = autocorrelation
        self.drift_per_cycle = drift_per_cycle

        self._value = baseline
        self._drift = 0.0
        self._warmup_factor = 1.0
        self._history: List[float] = []
        self._ma_window = 10

    def read(
        self,
        tool_wear_rate: float = 0.0,
        shift_factor: float = 1.0,
        ambient_temp: float = 22.0,
        is_warmup: bool = False,
    ) -> SensorReading:
        self._drift += self.drift_per_cycle

        if is_warmup:
            self._warmup_factor = max(0.7, self._warmup_factor - 0.05)
        else:
            self._warmup_factor = min(1.0, self._warmup_factor + 0.02)

        ambient_effect = (ambient_temp - 22.0) * 0.01
        wear_effect = tool_wear_rate * 0.3
        shift_noise = (shift_factor - 1.0) * self.noise_std * 0.5

        innovation = random.gauss(0, self.noise_std * self._warmup_factor)
        target = (
            self.baseline
            + self._drift
            + ambient_effect
            + wear_effect
            + shift_noise
            + innovation
        )

        self._value = (
            self.autocorrelation * self._value
            + (1 - self.autocorrelation) * target
        )

        self._history.append(self._value)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        status = "NORMAL"
        if abs(self._value) >= self.critical_threshold:
            status = "CRITICAL"
        elif abs(self._value) >= self.warn_threshold:
            status = "WARNING"

        return SensorReading(
            name=self.name,
            value=round(self._value, 3),
            unit=self.unit,
            status=status,
        )

    @property
    def ma(self) -> float:
        if not self._history:
            return self.baseline
        window = self._history[-self._ma_window:]
        return sum(window) / len(window)

    @property
    def slope(self) -> float:
        if len(self._history) < 5:
            return 0.0
        recent = self._history[-10:]
        n = len(recent)
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den > 0 else 0.0

    @property
    def std(self) -> float:
        if len(self._history) < 3:
            return 0.0
        recent = self._history[-20:]
        m = sum(recent) / len(recent)
        return (sum((v - m) ** 2 for v in recent) / len(recent)) ** 0.5

    def inject_shock(self, magnitude: float):
        self._drift += magnitude

    def recover(self, amount: float):
        self._drift = max(0, self._drift - amount)

    def reset_drift(self):
        self._drift = 0.0


# ── 워크센터 (공정별 머신) ────────────────────────────────────────

class WorkCenter:
    """
    제조 라인의 개별 공정(워크센터).
    실제 PLC에서 올라오는 센서 데이터를 시뮬레이션한다.
    """

    def __init__(
        self,
        station_id: str,
        name: str,
        station_type: str,
        cycle_time_sec: float,
        sensors: Dict[str, RealisticSensor],
        tool: Optional[ToolWear] = None,
    ):
        self.station_id = station_id
        self.name = name
        self.station_type = station_type
        self.cycle_time_sec = cycle_time_sec
        self.design_cycle_time = cycle_time_sec
        self.sensors = sensors
        self.tool = tool or ToolWear()
        self.state = MachineState.IDLE

        # OEE 추적
        self.total_cycles = 0
        self.good_count = 0
        self.defect_count = 0
        self.planned_time_sec = 0.0
        self.run_time_sec = 0.0
        self.downtime_sec = 0.0
        self.setup_time_sec = 0.0
        self.idle_time_sec = 0.0

        # MTBF / MTTR
        self.failure_count = 0
        self.total_repair_sec = 0.0
        self._last_failure_cycle = 0
        self._uptime_since_repair = 0

        # 에너지
        self.power_kw = 0.0
        self.energy_kwh = 0.0

        # 속도 조정
        self.speed_pct = 100

    def execute_cycle(
        self,
        shift_factor: float = 1.0,
        ambient_temp: float = 22.0,
    ) -> Dict[str, SensorReading]:
        if self.state in (MachineState.BREAKDOWN, MachineState.MAINTENANCE, MachineState.SETUP):
            return {}

        is_warmup = self.state == MachineState.WARMUP
        self.state = MachineState.RUNNING

        self.tool.advance()
        wear_rate = self.tool.wear_rate

        readings = {}
        for name, sensor in self.sensors.items():
            readings[name] = sensor.read(
                tool_wear_rate=wear_rate,
                shift_factor=shift_factor,
                ambient_temp=ambient_temp,
                is_warmup=is_warmup,
            )

        actual_ct = self.cycle_time_sec * (100 / max(40, self.speed_pct))
        self.run_time_sec += actual_ct
        self.planned_time_sec += self.design_cycle_time
        self.total_cycles += 1
        self._uptime_since_repair += 1

        self.power_kw = self._calc_power(wear_rate)
        self.energy_kwh += self.power_kw * (actual_ct / 3600)

        return readings

    def record_quality(self, is_good: bool):
        if is_good:
            self.good_count += 1
        else:
            self.defect_count += 1

    def trigger_breakdown(self, repair_time_sec: float = 600):
        self.state = MachineState.BREAKDOWN
        self.failure_count += 1
        self.total_repair_sec += repair_time_sec
        self.downtime_sec += repair_time_sec
        self._last_failure_cycle = self.total_cycles
        self._uptime_since_repair = 0

    def complete_repair(self):
        self.state = MachineState.WARMUP

    def start_setup(self, duration_sec: float = 300):
        self.state = MachineState.SETUP
        self.setup_time_sec += duration_sec

    def complete_setup(self):
        self.state = MachineState.WARMUP
        self.tool.reset()

    def set_speed(self, pct: int):
        self.speed_pct = max(40, min(110, pct))

    def _calc_power(self, wear_rate: float) -> float:
        base = {"PRESS": 45, "WELD": 35, "HEAT": 80, "CNC": 25, "ASSY": 12}.get(
            self.station_type, 20
        )
        speed_factor = self.speed_pct / 100
        return base * speed_factor * (1 + wear_rate * 0.1) + random.gauss(0, base * 0.02)

    @property
    def oee(self) -> Dict[str, float]:
        availability = (
            self.run_time_sec / self.planned_time_sec
            if self.planned_time_sec > 0
            else 1.0
        )
        performance = (
            (self.total_cycles * self.design_cycle_time) / self.run_time_sec
            if self.run_time_sec > 0
            else 1.0
        )
        quality = (
            self.good_count / self.total_cycles if self.total_cycles > 0 else 1.0
        )
        return {
            "availability": round(min(1.0, availability), 4),
            "performance": round(min(1.0, performance), 4),
            "quality": round(min(1.0, quality), 4),
            "oee": round(min(1.0, availability * performance * quality), 4),
        }

    @property
    def mtbf(self) -> float:
        if self.failure_count == 0:
            return float("inf")
        return self.run_time_sec / self.failure_count

    @property
    def mttr(self) -> float:
        if self.failure_count == 0:
            return 0.0
        return self.total_repair_sec / self.failure_count

    @property
    def yield_rate(self) -> float:
        total = self.good_count + self.defect_count
        return self.good_count / total if total > 0 else 1.0

    def get_status(self) -> dict:
        # inf/nan 은 JSON(RFC) 비호환 — Starlette JSONResponse 가 거부함
        mtbf_raw = self.mtbf
        if not math.isfinite(mtbf_raw):
            mtbf_json = None
        else:
            mtbf_json = round(mtbf_raw, 1)
        return {
            "station_id": self.station_id,
            "name": self.name,
            "type": self.station_type,
            "state": self.state.value,
            "speed_pct": self.speed_pct,
            "total_cycles": self.total_cycles,
            "tool_life_pct": round(self.tool.remaining_pct, 1),
            "tool_region": self.tool.region,
            "oee": self.oee,
            "mtbf": mtbf_json,
            "mttr": round(self.mttr, 1),
            "yield": round(self.yield_rate, 4),
            "power_kw": round(self.power_kw, 1),
            "energy_kwh": round(self.energy_kwh, 2),
        }


# ── 공정별 워크센터 팩토리 ────────────────────────────────────────

def create_blanking_press(station_id: str = "WC-01") -> WorkCenter:
    """1공정: 블랭킹 프레스 — 강판 절단."""
    sensors = {
        "vibration": RealisticSensor("진동", 2.1, 0.25, "mm/s", 3.8, 5.0, 0.88, 0.003),
        "tonnage": RealisticSensor("프레스압", 150.0, 3.0, "ton", 170, 180, 0.90),
        "oil_temp": RealisticSensor("유압유온", 42.0, 1.2, "°C", 55, 65, 0.92),
        "die_clearance": RealisticSensor("금형간극", 0.15, 0.008, "mm", 0.22, 0.28, 0.85, 0.0002),
        "noise_db": RealisticSensor("소음", 85.0, 2.0, "dB", 95, 105, 0.80),
    }
    tool = ToolWear(max_life=8000)
    return WorkCenter(station_id, "블랭킹 프레스", "PRESS", 4.5, sensors, tool)


def create_forming_press(station_id: str = "WC-02") -> WorkCenter:
    """2공정: 포밍 프레스 — 브래킷 성형."""
    sensors = {
        "vibration": RealisticSensor("진동", 1.8, 0.20, "mm/s", 3.5, 4.8, 0.87, 0.002),
        "tonnage": RealisticSensor("프레스압", 120.0, 2.5, "ton", 140, 155, 0.91),
        "springback": RealisticSensor("스프링백", 0.8, 0.06, "mm", 1.2, 1.5, 0.83, 0.0003),
        "oil_temp": RealisticSensor("유압유온", 40.0, 1.0, "°C", 52, 62, 0.92),
        "stroke_position": RealisticSensor("스트로크위치", 180.0, 0.3, "mm", 182, 184, 0.95),
    }
    tool = ToolWear(max_life=6000)
    return WorkCenter(station_id, "포밍 프레스", "PRESS", 5.0, sensors, tool)


def create_spot_welder(station_id: str = "WC-03") -> WorkCenter:
    """3공정: 스팟 용접 — 부품 접합."""
    sensors = {
        "weld_current": RealisticSensor("용접전류", 8500, 120, "A", 9200, 9800, 0.86),
        "weld_force": RealisticSensor("가압력", 3.2, 0.08, "kN", 3.8, 4.2, 0.88),
        "nugget_dia": RealisticSensor("너겟직경", 5.5, 0.15, "mm", 4.5, 4.0, 0.82, -0.001),
        "electrode_tip": RealisticSensor("전극팁마모", 0.0, 0.02, "mm", 0.8, 1.2, 0.90, 0.005),
        "spatter_rate": RealisticSensor("스패터율", 2.0, 0.8, "%", 5.0, 8.0, 0.75),
    }
    tool = ToolWear(max_life=3000)
    return WorkCenter(station_id, "스팟 용접", "WELD", 6.0, sensors, tool)


def create_heat_treatment(station_id: str = "WC-04") -> WorkCenter:
    """4공정: 열처리 — 경도 확보."""
    sensors = {
        "furnace_temp": RealisticSensor("노내온도", 850.0, 5.0, "°C", 880, 900, 0.95, 0.01),
        "quench_temp": RealisticSensor("냉각수온", 35.0, 1.5, "°C", 45, 55, 0.93),
        "hardness": RealisticSensor("경도(HRC)", 58.0, 0.8, "HRC", 54, 50, 0.88),
        "atmosphere": RealisticSensor("분위기가스", 0.3, 0.05, "%C", 0.5, 0.7, 0.90),
        "energy_rate": RealisticSensor("에너지소비", 75.0, 3.0, "kW", 90, 100, 0.85),
    }
    tool = ToolWear(max_life=15000)
    return WorkCenter(station_id, "열처리", "HEAT", 15.0, sensors, tool)


def create_cnc_machine(station_id: str = "WC-05") -> WorkCenter:
    """5공정: CNC 가공 — 정밀 가공."""
    sensors = {
        "spindle_vib": RealisticSensor("스핀들진동", 0.5, 0.08, "mm/s", 1.2, 2.0, 0.86, 0.001),
        "spindle_load": RealisticSensor("스핀들부하", 45.0, 2.0, "%", 75, 90, 0.88),
        "coolant_temp": RealisticSensor("절삭유온", 24.0, 0.8, "°C", 30, 35, 0.91),
        "surface_ra": RealisticSensor("표면거칠기", 1.6, 0.12, "μm", 2.5, 3.2, 0.84, 0.002),
        "dimension_dev": RealisticSensor("치수편차", 0.0, 0.005, "mm", 0.03, 0.05, 0.87, 0.0001),
    }
    tool = ToolWear(max_life=2000)
    return WorkCenter(station_id, "CNC 가공", "CNC", 8.0, sensors, tool)


def create_assembly_station(station_id: str = "WC-06") -> WorkCenter:
    """6공정: 조립 & 최종검사."""
    sensors = {
        "torque": RealisticSensor("체결토크", 25.0, 0.5, "Nm", 28, 32, 0.89),
        "force": RealisticSensor("조립압입력", 1.8, 0.06, "kN", 2.2, 2.5, 0.87),
        "vision_score": RealisticSensor("비전점수", 95.0, 1.5, "점", 88, 80, 0.82),
        "leak_rate": RealisticSensor("기밀검사", 0.0, 0.003, "cc/min", 0.01, 0.02, 0.90),
        "final_weight": RealisticSensor("중량", 2450.0, 3.0, "g", 2480, 2500, 0.93),
    }
    tool = ToolWear(max_life=20000)
    return WorkCenter(station_id, "조립/검사", "ASSY", 10.0, sensors, tool)


def create_production_line() -> List[WorkCenter]:
    """6공정 생산 라인 전체 생성."""
    return [
        create_blanking_press("WC-01"),
        create_forming_press("WC-02"),
        create_spot_welder("WC-03"),
        create_heat_treatment("WC-04"),
        create_cnc_machine("WC-05"),
        create_assembly_station("WC-06"),
    ]
