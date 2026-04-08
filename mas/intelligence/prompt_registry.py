"""
프롬프트·프롬프트 스위트 버전 — 변경 시 추적·회귀 비교용.
LLM 응답과 무관하게 코드에 고정 버전을 둔다.
"""

from __future__ import annotations

# 스위트 단위(문서·로그에 노출)
PROMPT_SUITE_VERSION = "2026.04.07"

# 개별 프롬프트 ID (A/B 또는 모델별 분기 시 참조)
PROMPT_IDS = {
    "pa_system": "pa_system_v1",
    "strategy_user": "strategy_user_v1",
    "situation_user": "situation_user_v1",
    "cnp_rationale_user": "cnp_rationale_v1",
}


def prompt_metadata() -> dict:
    return {
        "suite": PROMPT_SUITE_VERSION,
        "ids": dict(PROMPT_IDS),
    }
