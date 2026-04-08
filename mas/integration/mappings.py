from __future__ import annotations

from typing import Any, Dict, List


def map_mes_work_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "work_order_id": str(payload.get("workOrderId", "")),
        "line_id": str(payload.get("lineCode", "")),
        "sku": str(payload.get("materialCode", "")),
        "planned_qty": int(payload.get("plannedQty", 0) or 0),
        "released_qty": int(payload.get("releasedQty", 0) or 0),
        "status": str(payload.get("status", "UNKNOWN")),
        "planned_start": payload.get("plannedStartTs"),
        "planned_end": payload.get("plannedEndTs"),
    }


def map_erp_sales_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order_id": str(payload.get("salesOrderNo", "")),
        "customer_id": str(payload.get("customerCode", "")),
        "sku": str(payload.get("itemCode", "")),
        "order_qty": int(payload.get("orderQty", 0) or 0),
        "due_date": payload.get("requestedDeliveryDate"),
        "priority": str(payload.get("priority", "NORMAL")),
    }


def map_qms_inspection_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    defects = payload.get("defects")
    if not isinstance(defects, list):
        defects = []
    return {
        "inspection_id": str(payload.get("inspectionLotId", "")),
        "lot_id": str(payload.get("lotId", "")),
        "sku": str(payload.get("itemCode", "")),
        "result": str(payload.get("judgement", "UNKNOWN")),
        "defect_count": int(payload.get("defectCount", 0) or 0),
        "defects": [str(item) for item in defects],
        "inspected_at": payload.get("inspectedAt"),
    }


def build_connector_payload_bundle(
    *,
    mes_rows: List[Dict[str, Any]],
    erp_rows: List[Dict[str, Any]],
    qms_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "mes_work_orders": [map_mes_work_order(row) for row in mes_rows],
        "erp_sales_orders": [map_erp_sales_order(row) for row in erp_rows],
        "qms_inspections": [map_qms_inspection_result(row) for row in qms_rows],
    }
