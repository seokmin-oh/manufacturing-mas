from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..core.config import Settings, get_settings
from .live_connectors import (
    FileERPConnector,
    FileMESConnector,
    FileQMSConnector,
    RestERPConnector,
    RestMESConnector,
    RestQMSConnector,
)
from .sample_connectors import SampleERPConnector, SampleMESConnector, SampleQMSConnector


def build_connector_suite(settings: Settings | None = None) -> Dict[str, Any]:
    settings = settings or get_settings()
    mode = settings.connector_mode

    if mode == "off":
        return {"mode": mode, "mes": None, "erp": None, "qms": None}
    if mode == "sample":
        return {
            "mode": mode,
            "mes": SampleMESConnector([]),
            "erp": SampleERPConnector([]),
            "qms": SampleQMSConnector([]),
        }
    if mode == "file":
        return {
            "mode": mode,
            "mes": FileMESConnector(settings.mes_file_path),
            "erp": FileERPConnector(settings.erp_file_path),
            "qms": FileQMSConnector(settings.qms_file_path),
        }
    return {
        "mode": "rest",
        "mes": RestMESConnector(settings.mes_base_url),
        "erp": RestERPConnector(settings.erp_base_url),
        "qms": RestQMSConnector(settings.qms_base_url),
    }


def build_connector_status(settings: Settings | None = None) -> Dict[str, Any]:
    settings = settings or get_settings()

    def _file_entry(path: str) -> Dict[str, Any]:
        if not path:
            return {"configured": False, "path": "", "exists": False}
        file_path = Path(path)
        return {
            "configured": True,
            "path": str(file_path),
            "exists": file_path.exists(),
        }

    def _rest_entry(url: str) -> Dict[str, Any]:
        return {
            "configured": bool(url),
            "base_url": url,
        }

    if settings.connector_mode == "file":
        mes = _file_entry(settings.mes_file_path)
        erp = _file_entry(settings.erp_file_path)
        qms = _file_entry(settings.qms_file_path)
    elif settings.connector_mode == "rest":
        mes = _rest_entry(settings.mes_base_url)
        erp = _rest_entry(settings.erp_base_url)
        qms = _rest_entry(settings.qms_base_url)
    elif settings.connector_mode == "sample":
        mes = {"configured": True, "source": "in_memory_sample"}
        erp = {"configured": True, "source": "in_memory_sample"}
        qms = {"configured": True, "source": "in_memory_sample"}
    else:
        mes = {"configured": False}
        erp = {"configured": False}
        qms = {"configured": False}

    return {
        "mode": settings.connector_mode,
        "mes": mes,
        "erp": erp,
        "qms": qms,
    }
