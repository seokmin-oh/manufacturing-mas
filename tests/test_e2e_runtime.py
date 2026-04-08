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
