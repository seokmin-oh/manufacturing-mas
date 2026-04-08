from __future__ import annotations

from typing import Any, Dict, List


class LineScheduler:
    """Line-level coordinator that turns context and proposals into schedule guidance."""

    def __init__(self, line_id: str):
        self.line_id = line_id

    def build_schedule_view(self, manufacturing_context: Dict[str, Any]) -> Dict[str, Any]:
        identifiers = manufacturing_context.get("identifiers") if isinstance(manufacturing_context, dict) else {}
        summary = manufacturing_context.get("summary") if isinstance(manufacturing_context, dict) else {}
        line_kpi = (
            manufacturing_context.get("kpi_slices", {}).get("line", {})
            if isinstance(manufacturing_context, dict)
            else {}
        )
        return {
            "line_id": identifiers.get("line_id", self.line_id),
            "shift_code": identifiers.get("shift_code", summary.get("shift")),
            "avg_oee": line_kpi.get("avg_oee", summary.get("avg_oee")),
            "fg_stock": line_kpi.get("fg_stock", summary.get("fg_stock")),
            "total_produced": line_kpi.get("total_produced", summary.get("total_produced")),
        }

    def plan_from_strategy(
        self,
        strategy: Dict[str, Any],
        proposals: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        proposals = proposals or []
        return {
            "line_id": self.line_id,
            "target_speed_pct": strategy.get("target_speed_pct", 100),
            "inspection_mode": strategy.get("inspection_mode", "standard"),
            "best_agent": strategy.get("best_agent", ""),
            "approval_required": bool(strategy.get("approval_required")),
            "proposal_count": len(proposals) or strategy.get("proposals_count", 0),
        }
