from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

_VALID_LLM_ROUTER_SCOPES = frozenset({"pa_only", "all_gated"})
_VALID_CONNECTOR_MODES = frozenset({"off", "sample", "file", "rest"})


def _resolve_dotenv_path() -> Optional[Path]:
    here = Path(__file__).resolve()
    for depth in (2, 1):
        if len(here.parents) <= depth:
            continue
        candidate = here.parents[depth] / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv() -> None:
    env_path = _resolve_dotenv_path()
    if not env_path:
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    if text.startswith("\ufeff"):
        text = text[1:]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        current = os.environ.get(key)
        if current is None or (isinstance(current, str) and current.strip() == ""):
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    api_host: str
    api_port: int
    takt_sec: float
    llm_model: str
    llm_domain_model: str
    log_level: str
    api_bearer_token: str
    cors_origins: str
    llm_router_scope: str
    llm_per_agent_assist: bool
    connector_mode: str
    mes_file_path: str
    erp_file_path: str
    qms_file_path: str
    mes_base_url: str
    erp_base_url: str
    qms_base_url: str

    def cors_origin_list(self) -> List[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _get_env_int(key: str, default: int) -> int:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _build_settings() -> Settings:
    _load_dotenv()
    prefix = "MAS_"
    scope = (os.environ.get(prefix + "LLM_ROUTER_SCOPE", "pa_only") or "pa_only").strip().lower()
    if scope not in _VALID_LLM_ROUTER_SCOPES:
        scope = "pa_only"
    connector_mode = (os.environ.get(prefix + "CONNECTOR_MODE", "sample") or "sample").strip().lower()
    if connector_mode not in _VALID_CONNECTOR_MODES:
        connector_mode = "sample"
    return Settings(
        api_host=(os.environ.get(prefix + "API_HOST", "127.0.0.1") or "127.0.0.1").strip(),
        api_port=_get_env_int(prefix + "API_PORT", 8787),
        takt_sec=_get_env_float(prefix + "TAKT_SEC", 2.0),
        llm_model=os.environ.get(prefix + "LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        llm_domain_model=os.environ.get(prefix + "LLM_DOMAIN_MODEL", "").strip(),
        log_level=os.environ.get(prefix + "LOG_LEVEL", "INFO").strip() or "INFO",
        api_bearer_token=os.environ.get(prefix + "API_BEARER_TOKEN", "").strip(),
        cors_origins=os.environ.get(prefix + "CORS_ORIGINS", "*").strip() or "*",
        llm_router_scope=scope,
        llm_per_agent_assist=_get_env_bool(prefix + "LLM_PER_AGENT_ASSIST", False),
        connector_mode=connector_mode,
        mes_file_path=os.environ.get(prefix + "MES_FILE_PATH", "").strip(),
        erp_file_path=os.environ.get(prefix + "ERP_FILE_PATH", "").strip(),
        qms_file_path=os.environ.get(prefix + "QMS_FILE_PATH", "").strip(),
        mes_base_url=os.environ.get(prefix + "MES_BASE_URL", "").strip(),
        erp_base_url=os.environ.get(prefix + "ERP_BASE_URL", "").strip(),
        qms_base_url=os.environ.get(prefix + "QMS_BASE_URL", "").strip(),
    )


@lru_cache
def get_settings() -> Settings:
    return _build_settings()
