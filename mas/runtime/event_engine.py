from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any, Deque, Dict, Iterable, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RuntimeEvent:
    event_id: str
    event_type: str
    source: str
    severity: str
    timestamp_utc: str
    payload: Dict[str, Any] = field(default_factory=dict)
    requires_ack: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventStore:
    def __init__(self, max_events: int = 300, persist_path: str | None = None):
        self.max_events = max_events
        self._events: Deque[RuntimeEvent] = deque(maxlen=max_events)
        self._next_id = 1
        self.persist_path = Path(persist_path) if persist_path else None

    def append(
        self,
        *,
        event_type: str,
        source: str,
        severity: str = "INFO",
        payload: Optional[Dict[str, Any]] = None,
        requires_ack: bool = False,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            event_id=f"EVT-{self._next_id:06d}",
            event_type=event_type,
            source=source,
            severity=severity,
            timestamp_utc=utc_now_iso(),
            payload=dict(payload or {}),
            requires_ack=requires_ack,
        )
        self._next_id += 1
        self._events.append(event)
        self._persist_event(event)
        return event

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return [event.to_dict() for event in list(self._events)[-limit:]]

    def latest(self) -> Optional[Dict[str, Any]]:
        if not self._events:
            return None
        return self._events[-1].to_dict()

    def summary(self) -> Dict[str, Any]:
        by_severity: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for event in self._events:
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
        return {
            "total_retained": len(self._events),
            "latest_event": self.latest(),
            "by_severity": by_severity,
            "by_type": by_type,
            "persist_path": str(self.persist_path) if self.persist_path else "",
        }

    def replay(self, limit: int | None = None) -> List[Dict[str, Any]]:
        if not self.persist_path or not self.persist_path.exists():
            return []
        lines = self.persist_path.read_text(encoding="utf-8").splitlines()
        if limit is not None and limit > 0:
            lines = lines[-limit:]
        out: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def _persist_event(self, event: RuntimeEvent) -> None:
        if not self.persist_path:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self.persist_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ExecutionCommand:
    command_id: str
    command_type: str
    actor: str
    created_at_utc: str
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "QUEUED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionCommandQueue:
    def __init__(self, max_commands: int = 200):
        self.max_commands = max_commands
        self._commands: Deque[ExecutionCommand] = deque(maxlen=max_commands)
        self._next_id = 1

    def enqueue(
        self,
        *,
        command_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        command = ExecutionCommand(
            command_id=f"CMD-{self._next_id:06d}",
            command_type=command_type,
            actor=actor,
            created_at_utc=utc_now_iso(),
            payload=dict(payload or {}),
        )
        self._next_id += 1
        self._commands.append(command)
        return command.to_dict()

    def mark_status(
        self,
        command_id: str,
        status: str,
        *,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        updated: Deque[ExecutionCommand] = deque(maxlen=self.max_commands)
        target: Optional[Dict[str, Any]] = None
        for command in self._commands:
            if command.command_id == command_id:
                payload = dict(command.payload)
                if result:
                    payload["result"] = dict(result)
                command = ExecutionCommand(
                    command_id=command.command_id,
                    command_type=command.command_type,
                    actor=command.actor,
                    created_at_utc=command.created_at_utc,
                    payload=payload,
                    status=status,
                )
                target = command.to_dict()
            updated.append(command)
        self._commands = updated
        return target

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return [command.to_dict() for command in list(self._commands)[-limit:]]

    def latest(self) -> Optional[Dict[str, Any]]:
        if not self._commands:
            return None
        return self._commands[-1].to_dict()

    def summary(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for command in self._commands:
            by_status[command.status] = by_status.get(command.status, 0) + 1
        return {
            "total_retained": len(self._commands),
            "latest_command": self.latest(),
            "by_status": by_status,
        }

    def next_queued(self) -> Optional[Dict[str, Any]]:
        for command in self._commands:
            if command.status == "QUEUED":
                return command.to_dict()
        return None


class ManufacturingStateStore:
    def __init__(self):
        self._latest_snapshot: Dict[str, Any] = {}
        self._external_context: Dict[str, Any] = {
            "mes_work_orders": [],
            "erp_sales_orders": [],
            "qms_inspections": [],
        }
        self._audit_trail: Deque[Dict[str, Any]] = deque(maxlen=200)

    def update_snapshot(self, snapshot: Dict[str, Any]) -> None:
        self._latest_snapshot = dict(snapshot)

    def latest_snapshot(self) -> Dict[str, Any]:
        return dict(self._latest_snapshot)

    def update_external_context(self, payload: Dict[str, Any]) -> None:
        merged = dict(self._external_context)
        for key in ("mes_work_orders", "erp_sales_orders", "qms_inspections"):
            value = payload.get(key)
            merged[key] = list(value) if isinstance(value, list) else []
        self._external_context = merged

    def external_context(self) -> Dict[str, Any]:
        return {
            key: list(value) if isinstance(value, list) else []
            for key, value in self._external_context.items()
        }

    def record_audit(
        self,
        *,
        action: str,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "actor": actor,
                "timestamp_utc": utc_now_iso(),
                "details": dict(details or {}),
            }
        )

    def audit_trail(self, limit: int = 20) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self._audit_trail)[-limit:]

    def build_runtime_view(
        self,
        recent_events: Iterable[Dict[str, Any]],
        recent_commands: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return {
            "external_context": self.external_context(),
            "recent_events": list(recent_events),
            "recent_commands": list(recent_commands or []),
            "audit_trail": self.audit_trail(),
        }
