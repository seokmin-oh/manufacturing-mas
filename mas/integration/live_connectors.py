from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlencode
from urllib.request import urlopen

from .mappings import map_erp_sales_order, map_mes_work_order, map_qms_inspection_result


def _read_json_file(path: str) -> List[Dict[str, Any]]:
    if not path:
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        rows = raw.get("items")
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _read_json_url(url: str, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    if not url:
        return []
    full_url = url
    if params:
        full_url = f"{url}?{urlencode(params)}"
    with urlopen(full_url) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("items")
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    return []


class FileMESConnector:
    def __init__(self, path: str):
        self.path = path

    def fetch_raw_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return [row for row in _read_json_file(self.path) if str(row.get("lineCode", "")) == line_id]

    def fetch_mapped_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return [map_mes_work_order(row) for row in self.fetch_raw_work_orders(line_id)]


class FileERPConnector:
    def __init__(self, path: str):
        self.path = path

    def fetch_raw_sales_orders(self) -> List[Dict[str, Any]]:
        return _read_json_file(self.path)

    def fetch_mapped_sales_orders(self) -> List[Dict[str, Any]]:
        return [map_erp_sales_order(row) for row in self.fetch_raw_sales_orders()]


class FileQMSConnector:
    def __init__(self, path: str):
        self.path = path

    def fetch_raw_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return [row for row in _read_json_file(self.path) if str(row.get("lotId", "")) == lot_id]

    def fetch_mapped_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return [map_qms_inspection_result(row) for row in self.fetch_raw_inspections(lot_id)]


class RestMESConnector:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def fetch_raw_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return _read_json_url(f"{self.base_url}/work-orders", {"line_id": line_id})

    def fetch_mapped_work_orders(self, line_id: str) -> List[Dict[str, Any]]:
        return [map_mes_work_order(row) for row in self.fetch_raw_work_orders(line_id)]


class RestERPConnector:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def fetch_raw_sales_orders(self) -> List[Dict[str, Any]]:
        return _read_json_url(f"{self.base_url}/sales-orders")

    def fetch_mapped_sales_orders(self) -> List[Dict[str, Any]]:
        return [map_erp_sales_order(row) for row in self.fetch_raw_sales_orders()]


class RestQMSConnector:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def fetch_raw_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return _read_json_url(f"{self.base_url}/inspections", {"lot_id": lot_id})

    def fetch_mapped_inspections(self, lot_id: str) -> List[Dict[str, Any]]:
        return [map_qms_inspection_result(row) for row in self.fetch_raw_inspections(lot_id)]
