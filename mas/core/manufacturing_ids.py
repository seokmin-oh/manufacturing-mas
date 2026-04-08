"""
기본 제조 라인·에이전트 식별자 (단일 출처)
========================================

- **AGENT_IDS**: EA, QA, SA, DA, IA, PA 순서 고정 — 브로커·런타임·테스트가 동일 튜플을 가정.
- **STATION_IDS**: WC-01 … WC-06 — `mas/domain/machines.create_production_line` 과 반드시 일치.
- **PROFILE_SCHEMA_VERSION**: 외부 대시보드·통합 시 “이 ID 집합의 버전”으로 사용.

확장 시 체크리스트: `create_production_line`, `AGENT_DEFAULT_TOPICS`, `AGENT_INTERVALS`,
대시보드 HTML(또는 `/api/manufacturing/profile` 소비 코드)를 함께 수정.
"""

from __future__ import annotations

# 표준 6역할 — main.py / run_scenario / 브로커 기본 토픽과 동일 순서·ID
AGENT_IDS: tuple[str, ...] = ("EA", "QA", "SA", "DA", "IA", "PA")

# 표준 워크센터 (6공정) — `create_production_line()` 과 ID 일치
STATION_IDS: tuple[str, ...] = tuple(f"WC-{i:02d}" for i in range(1, 7))

PROFILE_SCHEMA_VERSION = "mas.manufacturing.v1"
