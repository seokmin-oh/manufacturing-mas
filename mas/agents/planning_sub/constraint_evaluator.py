from __future__ import annotations

from typing import Any, Dict, Tuple


def score_against_constraints(
    proposal: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Tuple[float, str]:
    """
    제약 위반량을 0~1 로 환산한 페널티와 한 줄 설명.
    constraints: speed_min_pct, speed_max_pct 등
    """
    sp = int(proposal.get("speed_recommendation") or proposal.get("target_speed_pct") or 100)
    smin = int(constraints.get("speed_min_pct") or 40)
    smax = int(constraints.get("speed_max_pct") or 100)
    viol = 0.0
    notes = []
    if sp < smin:
        viol += 0.4
        notes.append(f"속도<{smin}%")
    if sp > smax:
        viol += 0.4
        notes.append(f"속도>{smax}%")
    comp = proposal.get("comparison") or {}
    viol += float(comp.get("constraint_violation") or 0.0) * 0.2
    return min(1.0, viol), "; ".join(notes) if notes else "ok"
