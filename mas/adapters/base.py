"""어댑터 프로토콜 — typing.Protocol 로 경계만 고정 (기본 구현은 시뮬에서 생략 가능)."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class SensorAdapter(Protocol):
    def fetch_station_tags(self, station_id: str) -> Dict[str, Any]: ...


@runtime_checkable
class MESAdapter(Protocol):
    def fetch_work_orders(self, line_id: str) -> List[Dict[str, Any]]: ...


@runtime_checkable
class ERPOrderAdapter(Protocol):
    def fetch_open_orders(self) -> List[Dict[str, Any]]: ...


@runtime_checkable
class QualityInspectionAdapter(Protocol):
    def fetch_recent_inspections(self, lot_id: str) -> List[Dict[str, Any]]: ...


@runtime_checkable
class MaintenanceHistoryAdapter(Protocol):
    def fetch_recent_events(self, equipment_id: str) -> List[Dict[str, Any]]: ...


@runtime_checkable
class SOPDocumentAdapter(Protocol):
    def search_snippets(self, query: str, limit: int = 5) -> List[Dict[str, Any]]: ...
