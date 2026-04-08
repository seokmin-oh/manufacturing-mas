from mas.coordination import CellCoordinator, LineScheduler, PlantOrchestrator


def _context():
    return {
        "identifiers": {
            "plant_id": "P1",
            "line_id": "L1",
            "cell_id": "C1",
            "shift_code": "DAY",
        },
        "summary": {
            "avg_oee": 0.82,
            "fg_stock": 12,
            "total_produced": 144,
            "shift": "DAY",
        },
        "kpi_slices": {
            "line": {"avg_oee": 0.82, "fg_stock": 12, "total_produced": 144},
            "by_station": {
                "WC-01": {"state": "RUNNING"},
                "WC-02": {"state": "BREAKDOWN"},
            },
            "by_shift": {"shift_code": "DAY"},
            "by_sku": {},
        },
    }


def test_cell_coordinator_builds_risk_status():
    coordinator = CellCoordinator("C1")
    out = coordinator.build_status(_context())
    assert out["cell_id"] == "C1"
    assert out["risk_level"] == "HIGH"
    assert "WC-02" in out["risk_stations"]


def test_line_scheduler_builds_schedule_and_plan():
    scheduler = LineScheduler("L1")
    view = scheduler.build_schedule_view(_context())
    assert view["line_id"] == "L1"
    assert view["avg_oee"] == 0.82

    plan = scheduler.plan_from_strategy(
        {
            "target_speed_pct": 78,
            "inspection_mode": "전수",
            "best_agent": "QA",
            "approval_required": True,
            "proposals_count": 3,
        }
    )
    assert plan["target_speed_pct"] == 78
    assert plan["approval_required"] is True


def test_plant_orchestrator_builds_packet():
    orchestrator = PlantOrchestrator(
        "P1",
        line_scheduler=LineScheduler("L1"),
        cell_coordinator=CellCoordinator("C1"),
    )
    snap = orchestrator.build_coordination_snapshot(
        _context(),
        agent_statuses={"EA": {"recent_decisions": [{"type": "maintenance"}]}},
    )
    assert snap["plant_id"] == "P1"
    assert snap["local_actions"]

    packet = orchestrator.issue_decision_packet(
        {
            "decision": "rule_based",
            "best_agent": "QA",
            "target_speed_pct": 78,
            "inspection_mode": "전수",
            "approval_required": True,
            "proposals_count": 3,
        },
        manufacturing_context=_context(),
    )
    assert packet["requires_approval"] is True
    assert packet["schedule"]["best_agent"] == "QA"
