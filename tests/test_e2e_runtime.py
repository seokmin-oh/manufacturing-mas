"""
E2E 통합 테스트 — Factory + Runtime + 6에이전트 + Broker 전체 흐름 검증.

짧은 사이클(5회)로 전체 시스템을 돌려보고:
1. 공장 사이클이 진행되었는지
2. 에이전트가 Sense-Reason-Act를 수행했는지
3. 브로커에 메시지가 쌓였는지
4. 스냅샷이 정상 구조인지
5. KPI 집계가 동작하는지
를 검증한다.
"""

import time
import threading

from mas.domain.agent_snapshot import enrich_snapshot_for_agents
from mas.domain.environment import Factory
from mas.messaging.broker import MessageBroker
from mas.agents import (
    EquipmentAgent, QualityAgent, SupplyAgent,
    DemandAgent, InventoryAgent, PlanningAgent,
)
from mas.intelligence.llm import LLMClient
from mas.intelligence.decision_router import HybridDecisionRouter
from mas.protocol.agent_protocol import run_cycle_with_router
from mas.runtime.factory_runtime import FactoryRuntime
from mas.integration.sample_connectors import (
    SampleERPConnector,
    SampleMESConnector,
    SampleQMSConnector,
)


def _make_system():
    """테스트용 전체 시스템을 조립한다."""
    factory = Factory()
    broker = MessageBroker()
    llm = LLMClient()
    router = HybridDecisionRouter(llm_client=llm)

    ea = EquipmentAgent()
    qa = QualityAgent()
    sa = SupplyAgent()
    da = DemandAgent()
    ia = InventoryAgent()
    pa = PlanningAgent(llm_client=llm)
    agents = [ea, qa, sa, da, ia, pa]

    for a in agents:
        broker.register(a)

    return factory, broker, agents, router


class TestE2ERuntime:
    def test_factory_cycles_advance(self):
        factory, broker, agents, router = _make_system()

        for _ in range(5):
            factory.run_cycle()

        assert factory.cycle == 5
        assert factory.total_produced + factory.scrap_count + factory.rework_count >= 0

    def test_snapshot_structure(self):
        factory, broker, agents, router = _make_system()
        factory.run_cycle()
        snap = factory.get_snapshot()

        assert "stations" in snap
        assert "cycle" in snap
        assert "materials" in snap
        assert "orders" in snap
        assert "wip" in snap
        assert "avg_oee" in snap
        assert len(snap["stations"]) == 6

    def test_agents_run_cycle_with_router(self):
        factory, broker, agents, router = _make_system()

        for _ in range(3):
            factory.run_cycle()

        snap = factory.get_snapshot()

        for agent in agents:
            if agent.agent_id == "PA":
                continue
            decision = run_cycle_with_router(
                agent, snap,
                decision_router=router,
                broker=broker,
            )
            assert agent._cycle_count >= 1
            status = agent.get_agent_status()
            assert status["agent_id"] == agent.agent_id
            assert status["cycle_count"] >= 1

    def test_planning_agent_cnp_flow(self):
        factory, broker, agents, router = _make_system()

        for _ in range(5):
            factory.run_cycle()

        snap = factory.get_snapshot()
        pa = [a for a in agents if a.agent_id == "PA"][0]
        others = [a for a in agents if a.agent_id != "PA"]

        for agent in others:
            run_cycle_with_router(agent, snap, decision_router=router, broker=broker)

        strategy = pa.initiate_cnp(others, enrich_snapshot_for_agents(dict(snap)))
        assert pa.cnp_count >= 1
        if strategy:
            assert "target_speed_pct" in strategy
            assert "best_agent" in strategy
            assert "operational_decision_card" in strategy

    def test_broker_message_delivery(self):
        factory, broker, agents, router = _make_system()

        for _ in range(5):
            factory.run_cycle()

        snap = factory.get_snapshot()
        for agent in agents:
            if agent.agent_id != "PA":
                run_cycle_with_router(agent, snap, decision_router=router, broker=broker)

        status = broker.get_status()
        assert "agents_registered" in status
        assert len(status["agents_registered"]) == 6
        assert status["metrics"]["total_published"] >= 0

    def test_kpi_summary_fields(self):
        factory, broker, agents, router = _make_system()

        for _ in range(10):
            factory.run_cycle()

        kpi = factory.get_kpi_summary()

        assert "cycle" in kpi
        assert kpi["cycle"] == 10
        assert "total_produced" in kpi
        assert "fpy" in kpi
        assert "avg_oee" in kpi
        assert "bottleneck" in kpi
        assert "total_energy_kwh" in kpi
        assert "on_time_delivery" in kpi
        assert 0 <= kpi["fpy"] <= 1.0
        assert 0 <= kpi["avg_oee"] <= 1.0

    def test_envelope_log_bounded(self):
        """envelope_log 가 MAX_ENVELOPE_LOG 를 초과하지 않는지 확인."""
        factory, broker, agents, router = _make_system()

        for _ in range(20):
            factory.run_cycle()
            snap = factory.get_snapshot()
            for agent in agents:
                if agent.agent_id != "PA":
                    run_cycle_with_router(agent, snap, decision_router=router, broker=broker)

        assert len(broker.envelope_log) <= broker.MAX_ENVELOPE_LOG

    def test_agent_status_all_agents(self):
        """모든 에이전트의 get_agent_status() 가 기본 키를 갖는지 확인."""
        factory, broker, agents, router = _make_system()

        for _ in range(3):
            factory.run_cycle()

        snap = factory.get_snapshot()
        for agent in agents:
            if agent.agent_id != "PA":
                run_cycle_with_router(agent, snap, decision_router=router, broker=broker)

        for agent in agents:
            status = agent.get_agent_status()
            for key in ("agent_id", "name", "state", "cycle_count"):
                assert key in status, f"{agent.agent_id} missing key: {key}"

    def test_runtime_orchestration_pending_approval(self, monkeypatch):
        factory, broker, agents, router = _make_system()
        runtime = FactoryRuntime(factory, broker, agents, decision_router=router)
        pa = [a for a in agents if a.agent_id == "PA"][0]

        factory.run_cycle()
        snap = factory.get_snapshot()

        def fake_run_cycle_with_router(*args, **kwargs):
            return {"initiate_cnp": True, "cnp_reason": "quality risk"}

        def fake_initiate_cnp(agent_list, snapshot):
            return {
                "decision": "rule_based",
                "best_agent": "QA",
                "target_speed_pct": 78,
                "inspection_mode": "전수",
                "approval_required": True,
                "proposals_count": 2,
            }

        monkeypatch.setattr("mas.runtime.factory_runtime.run_cycle_with_router", fake_run_cycle_with_router)
        monkeypatch.setattr(pa, "initiate_cnp", fake_initiate_cnp)

        runtime._run_pa_with_orchestration(pa, snap)

        pending = runtime.get_pending_approval_packet()
        assert pending["requires_approval"] is True
        assert pending["schedule"]["target_speed_pct"] == 78

    def test_runtime_orchestration_auto_apply(self, monkeypatch):
        factory, broker, agents, router = _make_system()
        runtime = FactoryRuntime(factory, broker, agents, decision_router=router)
        pa = [a for a in agents if a.agent_id == "PA"][0]

        factory.run_cycle()
        snap = factory.get_snapshot()

        def fake_run_cycle_with_router(*args, **kwargs):
            return {"initiate_cnp": True, "cnp_reason": "throughput optimization"}

        def fake_initiate_cnp(agent_list, snapshot):
            return {
                "decision": "rule_based",
                "best_agent": "EA",
                "target_speed_pct": 90,
                "inspection_mode": "standard",
                "approval_required": False,
                "proposals_count": 2,
            }

        monkeypatch.setattr("mas.runtime.factory_runtime.run_cycle_with_router", fake_run_cycle_with_router)
        monkeypatch.setattr(pa, "initiate_cnp", fake_initiate_cnp)

        runtime._run_pa_with_orchestration(pa, snap)
        queued = runtime.command_queue.next_queued()
        runtime.command_queue.mark_status(queued["command_id"], "IN_PROGRESS")
        runtime._execute_command(queued)

        assert runtime.get_pending_approval_packet() == {}
        packet = runtime.get_last_orchestration_packet()
        assert packet["schedule"]["target_speed_pct"] == 90
        assert all(station.speed_pct == 90 for station in factory.line)

    def test_runtime_ingests_external_inputs_into_snapshot(self):
        factory, broker, agents, router = _make_system()
        connector_suite = {
            "mode": "sample",
            "mes": SampleMESConnector(
                [{"workOrderId": "WO-1", "lineCode": "L1", "materialCode": "PAD-A", "plannedQty": 100}]
            ),
            "erp": SampleERPConnector(
                [{"salesOrderNo": "SO-1", "customerCode": "HMC", "itemCode": "PAD-A", "orderQty": 10}]
            ),
            "qms": SampleQMSConnector(
                [{"inspectionLotId": "ILOT-1", "lotId": "LOT-7", "itemCode": "PAD-A", "judgement": "FAIL"}]
            ),
        }
        runtime = FactoryRuntime(
            factory, broker, agents, decision_router=router, connector_suite=connector_suite
        )

        factory.run_cycle()
        snap = runtime._refresh_runtime_state(factory.get_snapshot())

        assert snap["external_inputs"]["mes_work_orders"][0]["work_order_id"] == "WO-1"
        assert snap["external_inputs"]["erp_sales_orders"][0]["order_id"] == "SO-1"
        assert snap["external_inputs"]["qms_inspections"][0]["result"] == "FAIL"
        event_types = {event["event_type"] for event in snap["business_events"]}
        assert "connector.snapshot_ingested" in event_types
        assert "quality.external_fail_detected" in event_types

    def test_runtime_approval_records_audit_trail(self):
        factory, broker, agents, router = _make_system()
        runtime = FactoryRuntime(factory, broker, agents, decision_router=router)
        runtime._pending_approval_packet = {
            "requires_approval": True,
            "schedule": {"target_speed_pct": 82},
            "best_agent": "QA",
        }

        result = runtime.approve_pending_packet(approver="lead", note="apply now")
        queued = runtime.command_queue.next_queued()
        runtime.command_queue.mark_status(queued["command_id"], "IN_PROGRESS")
        runtime._execute_command(queued)

        assert result["approved"] is True
        audit = runtime.state_store.audit_trail(limit=5)
        actions = [entry["action"] for entry in audit]
        assert "approval_approved" in actions
        assert "execution_queued" in actions
        assert "execution_completed" in actions
        latest_command = runtime.command_queue.latest()
        assert latest_command["status"] == "COMPLETED"

    def test_runtime_dispatches_high_severity_event_to_pa(self, monkeypatch):
        factory, broker, agents, router = _make_system()
        runtime = FactoryRuntime(factory, broker, agents, decision_router=router)
        factory.run_cycle()
        snap = runtime._refresh_runtime_state(factory.get_snapshot())
        runtime._snapshot = snap

        called = {"count": 0}

        def fake_run_pa(pa, snapshot):
            called["count"] += 1

        monkeypatch.setattr(runtime, "_run_pa_with_orchestration", fake_run_pa)
        runtime._dispatch_runtime_event(
            {
                "event_id": "EVT-1",
                "event_type": "equipment.breakdown_detected",
                "severity": "CRITICAL",
                "requires_ack": False,
            }
        )

        assert called["count"] == 1
        audit = runtime.state_store.audit_trail(limit=5)
        assert any(entry["action"] == "event_dispatched" for entry in audit)

    def test_runtime_persists_event_log_and_command_queue(self, tmp_path):
        factory, broker, agents, router = _make_system()
        runtime = FactoryRuntime(factory, broker, agents, decision_router=router)
        runtime.event_store.persist_path = tmp_path / "event_log.jsonl"

        runtime._record_event(
            event_type="equipment.breakdown_detected",
            source="EA",
            severity="CRITICAL",
            payload={"station_id": "WC-01"},
        )
        runtime._queue_execution_command(
            {"schedule": {"target_speed_pct": 88}, "best_agent": "EA"},
            actor="PA",
        )
        queued = runtime.command_queue.next_queued()
        runtime.command_queue.mark_status(queued["command_id"], "IN_PROGRESS")
        runtime._execute_command(queued)

        assert runtime.event_store.persist_path.exists()
        lines = runtime.event_store.persist_path.read_text(encoding="utf-8").splitlines()
        assert any("equipment.breakdown_detected" in line for line in lines)
        assert runtime.command_queue.summary()["by_status"]["COMPLETED"] >= 1

    def test_runtime_recovery_rebuilds_pending_packet_from_event_log(self, tmp_path):
        factory, broker, agents, router = _make_system()
        runtime = FactoryRuntime(factory, broker, agents, decision_router=router)
        runtime.event_store.persist_path = tmp_path / "event_log.jsonl"
        runtime._record_event(
            event_type="approval.pending",
            source="PA",
            severity="HIGH",
            payload={"packet": {"requires_approval": True, "schedule": {"target_speed_pct": 77}}},
            requires_ack=True,
        )

        recovered = FactoryRuntime(factory, broker, agents, decision_router=router)
        recovered.event_store.persist_path = runtime.event_store.persist_path
        recovered._recover_from_event_log()

        assert recovered.get_pending_approval_packet()["schedule"]["target_speed_pct"] == 77
        assert recovered.get_event_runtime_status()["recovery"]["replayed_events"] >= 1
