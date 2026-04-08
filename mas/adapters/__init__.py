"""
외부 시스템 어댑터 계층 — MAS 코어는 표준 컨텍스트만 소비.

구현체는 공장·사이트별로 교체 (센서/MES/ERP/품질/정비/SOP).
"""

from .base import (
    ERPOrderAdapter,
    MaintenanceHistoryAdapter,
    MESAdapter,
    QualityInspectionAdapter,
    SensorAdapter,
    SOPDocumentAdapter,
)

__all__ = [
    "SensorAdapter",
    "MESAdapter",
    "ERPOrderAdapter",
    "QualityInspectionAdapter",
    "MaintenanceHistoryAdapter",
    "SOPDocumentAdapter",
]
