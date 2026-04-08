from __future__ import annotations

from typing import Any, Dict, List


def build_pa_report_lines(strategy: Dict[str, Any], proposals: List[Dict[str, Any]]) -> List[str]:
    """사람이 읽기 위한 요약 줄 (로그·대시보드)."""
    lines = [
        f"결정: {strategy.get('decision', 'n/a')}",
        f"목표속도: {strategy.get('target_speed_pct', '-')}%",
        f"검사모드: {strategy.get('inspection_mode', '-')}",
        f"제안 수: {len(proposals)}",
    ]
    best = proposals[0] if proposals else {}
    if best.get("comparison"):
        c = best["comparison"]
        lines.append(
            f"최우선 대안: {c.get('candidate_action', '')} "
            f"(신뢰도 {c.get('confidence', 0):.2f})"
        )
    return lines
