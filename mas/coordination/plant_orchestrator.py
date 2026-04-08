from __future__ import annotations

from typing import Any, Dict, List, Optional

from .cell_coordinator import CellCoordinator
from .line_scheduler import LineScheduler


class PlantOrchestrator:
    """Top-level coordinator that combines line and cell views with CNP outputs."""

    def __init__(
        self,
        plant_id: str,
        *,
        line_scheduler: Optional[LineScheduler] = None,
        cell_coordinator: Optional[CellCoordinator] = None,
    ):
        self.plant_id = plant_id
        self.line_scheduler = line_scheduler or LineScheduler(line_id="LINE-UNKNOWN")
        self.cell_coordinator = cell_coordinator or CellCoordinator(cell_id="CELL-UNKNOWN")

    def build_coordination_snapshot(
        self,
        manufacturing_context: Dict[str, Any],
        *,
        agent_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        agent_statuses = agent_statuses or {}
        line_view = self.line_scheduler.build_schedule_view(manufacturing_context)
        cell_view = self.cell_coordinator.build_status(manufacturing_context)
        return {
            "plant_id": self.plant_id,
            "line_schedule": line_view,
            "cell_status": cell_view,
            "local_actions": self.cell_coordinator.collect_local_actions(agent_statuses),
        }

    def issue_decision_packet(
        self,
        strategy: Dict[str, Any],
        *,
        proposals: Optional[List[Dict[str, Any]]] = None,
        manufacturing_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        schedule = self.line_scheduler.plan_from_strategy(strategy, proposals)
        return {
            "plant_id": self.plant_id,
            "decision": strategy.get("decision", "rule_based"),
            "best_agent": strategy.get("best_agent", ""),
            "schedule": schedule,
            "context_ref": (
                (manufacturing_context or {}).get("identifiers", {}).get("line_id")
                if isinstance(manufacturing_context, dict)
                else None
            ),
            "requires_approval": bool(strategy.get("approval_required")),
        }
