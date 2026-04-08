from __future__ import annotations

from typing import Any, Dict, List

from .mappings import (
    build_connector_payload_bundle,
    map_erp_sales_order,
    map_mes_work_order,
    map_qms_inspection_result,
)


class SampleMESConnector:
    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows = rows or []

    def fetch_raw_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.rows
            if str(row.get("lineCode", "")) == line_id
        ]

    def fetch_mapped_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return [map_mes_work_order(row) for row in self.fetch_raw_work_orders(line_id)]


class SampleERPConnector:
    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows = rows or []

    def fetch_raw_sales_orders(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.rows]

    def fetch_mapped_sales_orders(self) -> List[Dict[str, Any]]:
        return [map_erp_sales_order(row) for row in self.fetch_raw_sales_orders()]


class SampleQMSConnector:
    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows = rows or []

    def fetch_raw_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.rows
            if str(row.get("lotId", "")) == lot_id
        ]

    def fetch_mapped_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return [map_qms_inspection_result(row) for row in self.fetch_raw_inspections(lot_id)]


def sample_bundle(
    *,
    mes_connector: SampleMESConnector,
    erp_connector: SampleERPConnector,
    qms_connector: SampleQMSConnector,
    line_id: str,
    lot_id: str,
) -> Dict[str, Any]:
    return build_connector_payload_bundle(
        mes_rows=mes_connector.fetch_raw_work_orders(line_id),
        erp_rows=erp_connector.fetch_raw_sales_orders(),
        qms_rows=qms_connector.fetch_raw_inspections(lot_id),
    )
