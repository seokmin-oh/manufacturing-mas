"""
비즈니스 이벤트 스트림 — 상태 스냅샷과 분리.

factory_tick 외 작업 완료·검사 판정 등 의미 있는 전이를 링 버퍼에 보관한다.
에이전트는 `snapshot["business_events"]` 최근 N건과 스냅샷을 함께 본다.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional


class BusinessEventType(str, Enum):
    FACTORY_TICK = "factory_tick"
    WORK_STARTED = "work_started"
    WORK_COMPLETE = "work_complete"
    INSPECTION_VERDICT = "inspection_verdict"
    QUALITY_ESCALATION = "quality_escalation"
    STATION_STATE_CHANGE = "station_state_change"
    MATERIAL_EVENT = "material_event"


@dataclass
class BusinessEvent:
    event_id: str
    event_type: str
    logical_cycle: int
    sim_time_sec: float
    event_time_wall_iso: str
    payload: Dict[str, Any] = field(default_factory=dict)
    station_id: Optional[str] = None
    lot_id: Optional[str] = None
    sku: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class BusinessEventStore:
    """메모리 링 버퍼 (추후 DB/큐로 대체 가능)."""

    def __init__(self, maxlen: int = 2500):
        self._q: Deque[BusinessEvent] = deque(maxlen=maxlen)

    def emit(
        self,
        event_type: BusinessEventType | str,
        logical_cycle: int,
        sim_time_sec: float,
        payload: Optional[Dict[str, Any]] = None,
        *,
        station_id: Optional[str] = None,
        lot_id: Optional[str] = None,
        sku: Optional[str] = None,
    ) -> BusinessEvent:
        et = event_type.value if isinstance(event_type, BusinessEventType) else str(event_type)
        ev = BusinessEvent(
            event_id=str(uuid.uuid4())[:12],
            event_type=et,
            logical_cycle=int(logical_cycle),
            sim_time_sec=float(sim_time_sec),
            event_time_wall_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            payload=dict(payload or {}),
            station_id=station_id,
            lot_id=lot_id,
            sku=sku,
        )
        self._q.append(ev)
        return ev

    def tail(self, n: int = 50) -> List[Dict[str, Any]]:
        items = list(self._q)
        return [e.to_dict() for e in items[-n:]]

    def __len__(self) -> int:
        return len(self._q)
