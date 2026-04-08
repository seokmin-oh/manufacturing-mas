"""PA 내부 역할 분리 — 수집·랭킹·제약·리포트 (단일 프로세스 내 모듈)."""

from .alert_collector import collect_inbox_alerts
from .constraint_evaluator import score_against_constraints
from .proposal_ranker import rank_proposals_by_comparison
from .strategy_reporter import build_pa_report_lines

__all__ = [
    "collect_inbox_alerts",
    "score_against_constraints",
    "rank_proposals_by_comparison",
    "build_pa_report_lines",
]
