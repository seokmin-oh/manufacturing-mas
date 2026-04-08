from __future__ import annotations

from typing import Any, Dict, List


class CellCoordinator:
    """Local coordinator for station-level risk and action aggregation."""

    def __init__(self, cell_id: str):
        self.cell_id = cell_id

    def build_status(self, manufacturing_context: Dict[str, Any]) -> Dict[str, Any]:
        kpi_slices = manufacturing_context.get("kpi_slices") if isinstance(manufacturing_context, dict) else {}
        by_station = kpi_slices.get("by_station") if isinstance(kpi_slices, dict) else {}
        station_states: Dict[str, str] = {}
        risk_stations: List[str] = []
        for station_id, row in by_station.items():
            if not isinstance(row, dict):
                continue
            state = str(row.get("state", "UNKNOWN"))
            station_states[station_id] = state
            if state.upper() not in {"RUN", "RUNNING", "IDLE"}:
                risk_stations.append(station_id)
        return {
            "cell_id": self.cell_id,
            "stations": station_states,
            "risk_stations": risk_stations,
            "risk_level": "HIGH" if risk_stations else "LOW",
        }

    def collect_local_actions(
        self,
        agent_statuses: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        for agent_id, status in agent_statuses.items():
            if not isinstance(status, dict):
                continue
            recent = status.get("recent_decisions") or []
            if recent:
                actions.append(
                    {
                        "agent_id": agent_id,
                        "decision_count": len(recent),
                        "latest": recent[-1],
                    }
                )
        return actions
