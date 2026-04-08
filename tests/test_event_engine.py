from mas.runtime.event_engine import EventStore, ExecutionCommandQueue, ManufacturingStateStore


def test_event_store_retains_recent_events():
    store = EventStore(max_events=2)
    store.append(event_type="a", source="SYS")
    store.append(event_type="b", source="SYS", severity="HIGH")
    store.append(event_type="c", source="SYS")

    events = store.recent(limit=5)
    assert len(events) == 2
    assert events[0]["event_type"] == "b"
    assert events[1]["event_type"] == "c"
    assert store.summary()["by_severity"]["HIGH"] == 1


def test_event_store_persists_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    store = EventStore(max_events=3, persist_path=str(path))
    store.append(event_type="connector.snapshot_ingested", source="INT")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "connector.snapshot_ingested" in lines[0]


def test_execution_command_queue_tracks_status():
    queue = ExecutionCommandQueue()
    command = queue.enqueue(command_type="apply_orchestration_packet", actor="PA")
    assert command["status"] == "QUEUED"
    assert queue.next_queued()["command_id"] == command["command_id"]

    updated = queue.mark_status(command["command_id"], "COMPLETED", result={"applied": True})
    assert updated["status"] == "COMPLETED"
    assert updated["payload"]["result"]["applied"] is True
    assert queue.summary()["by_status"]["COMPLETED"] == 1


def test_state_store_tracks_external_context_and_audit():
    store = ManufacturingStateStore()
    store.update_snapshot({"cycle": 1})
    store.update_external_context(
        {
            "mes_work_orders": [{"work_order_id": "WO-1"}],
            "erp_sales_orders": [],
            "qms_inspections": [],
        }
    )
    store.record_audit(action="approval_pending", actor="PA", details={"packet": {"x": 1}})

    runtime_view = store.build_runtime_view(recent_events=[{"event_type": "approval.pending"}])
    assert runtime_view["external_context"]["mes_work_orders"][0]["work_order_id"] == "WO-1"
    assert runtime_view["audit_trail"][0]["action"] == "approval_pending"
    assert runtime_view["recent_events"][0]["event_type"] == "approval.pending"
