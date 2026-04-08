from __future__ import annotations

from typing import Any, Dict, List


class MockSensorAdapter:
    def __init__(self, station_payloads: Dict[str, Dict[str, Any]] | None = None):
        self.station_payloads = station_payloads or {}

    def fetch_station_tags(self, station_id: str) -> Dict[str, Any]:
        return dict(self.station_payloads.get(station_id, {}))


class MockMESAdapter:
    def __init__(self, work_orders_by_line: Dict[str, List[Dict[str, Any]]] | None = None):
        self.work_orders_by_line = work_orders_by_line or {}

    def fetch_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.work_orders_by_line.get(line_id, [])]


class MockERPOrderAdapter:
    def __init__(self, open_orders: List[Dict[str, Any]] | None = None):
        self.open_orders = open_orders or []

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.open_orders]


class MockQualityInspectionAdapter:
    def __init__(self, inspections_by_lot: Dict[str, List[Dict[str, Any]]] | None = None):
        self.inspections_by_lot = inspections_by_lot or {}

    def fetch_recent_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.inspections_by_lot.get(lot_id, [])]


class MockMaintenanceHistoryAdapter:
    def __init__(self, history_by_equipment: Dict[str, List[Dict[str, Any]]] | None = None):
        self.history_by_equipment = history_by_equipment or {}

    def fetch_recent_events(self, equipment_id: str) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.history_by_equipment.get(equipment_id, [])]


class MockSOPDocumentAdapter:
    def __init__(self, snippets: List[Dict[str, Any]] | None = None):
        self.snippets = snippets or []

    def search_snippets(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        matches = []
        for snippet in self.snippets:
            title = str(snippet.get("title", "")).lower()
            body = str(snippet.get("body", "")).lower()
            if query_lower in title or query_lower in body:
                matches.append(dict(snippet))
            if len(matches) >= limit:
                break
        return matches
