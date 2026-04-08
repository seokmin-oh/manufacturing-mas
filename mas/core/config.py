"""
환경 변수 및 선택적 .env 기반 설정
================================

- 모든 공개 설정 키는 접두사 **MAS_** (예: `MAS_API_PORT`, `MAS_LLM_MODEL`).
- **python-dotenv 패키지 없이** 프로젝트 루트 `.env` 를 직접 읽어 `os.environ` 에만 채운다.
  → 이미 셸에 설정된 값은 덮어쓰지 않음(빈 문자열만 채움).
- `get_settings()` 는 `@lru_cache` 로 **프로세스당 한 번** 빌드된다. 테스트에서 환경을 바꾼 뒤
  설정을 다시 읽으려면 `get_settings.cache_clear()` 가 필요할 수 있다.

관련: 루트 `.env.example` — 변수 설명과 기본값 예시.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

# LLM 라우터 범위: pa_only(기본) | all_gated(게이트된 전 에이전트 후보)
_VALID_LLM_ROUTER_SCOPES = frozenset({"pa_only", "all_gated"})


def _resolve_dotenv_path() -> Optional[Path]:
    """`mas/core/config.py` 기준 프로젝트 루트는 parents[2]. (예전 `mas/config.py`는 parents[1])"""
    here = Path(__file__).resolve()
    for depth in (2, 1):
        if len(here.parents) <= depth:
            continue
        p = here.parents[depth] / ".env"
        if p.is_file():
            return p
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
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        cur = os.environ.get(key)
        if cur is None or (isinstance(cur, str) and cur.strip() == ""):
            os.environ[key] = val


@dataclass(frozen=True)
class Settings:
    """런타임에서 읽기 전용으로 쓰는 설정 스냅샷. 필드 추가 시 `_build_settings` 도 같이 수정."""

    api_host: str  # FastAPI/uvicorn 바인딩 호스트 (기본 127.0.0.1, 외부 노출 시 0.0.0.0)
    api_port: int  # FastAPI/uvicorn 바인딩 포트
    takt_sec: float  # Factory.run_cycle 호출 간격(초) — 생산 시뮬 “한 틱” 길이
    llm_model: str  # OpenAI 호환 API 기본 모델명 (PA 전략·라우터 등)
    llm_domain_model: str  # 도메인 보조 모델(선택, 빈 문자열이면 미사용)
    log_level: str  # logging 레벨 문자열
    api_bearer_token: str  # 비어 있으면 /api/* 에 Bearer 검사 안 함(대시보드 로컬 편의)
    cors_origins: str  # 쉼표 구분 출처 또는 "*"
    llm_router_scope: str  # pa_only | all_gated — LLM을 라우터가 어디까지 쓸지
    llm_per_agent_assist: bool  # True면 게이트 조건에서 에이전트별 LLM 보조 허용

    def cors_origin_list(self) -> List[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


def _get_env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _build_settings() -> Settings:
    _load_dotenv()
    p = "MAS_"
    scope = (os.environ.get(p + "LLM_ROUTER_SCOPE", "pa_only") or "pa_only").strip().lower()
    if scope not in _VALID_LLM_ROUTER_SCOPES:
        scope = "pa_only"
    return Settings(
        api_host=(os.environ.get(p + "API_HOST", "127.0.0.1") or "127.0.0.1").strip(),
        api_port=_get_env_int(p + "API_PORT", 8787),
        takt_sec=_get_env_float(p + "TAKT_SEC", 2.0),
        llm_model=os.environ.get(p + "LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        llm_domain_model=os.environ.get(p + "LLM_DOMAIN_MODEL", "").strip(),
        log_level=os.environ.get(p + "LOG_LEVEL", "INFO").strip() or "INFO",
        api_bearer_token=os.environ.get(p + "API_BEARER_TOKEN", "").strip(),
        cors_origins=os.environ.get(p + "CORS_ORIGINS", "*").strip() or "*",
        llm_router_scope=scope,
        llm_per_agent_assist=_get_env_bool(p + "LLM_PER_AGENT_ASSIST", False),
    )


@lru_cache
def get_settings() -> Settings:
    """프로세스 전역 단일 Settings. 최초 호출 시 .env 로드 후 `Settings` 인스턴스 생성."""
    return _build_settings()

