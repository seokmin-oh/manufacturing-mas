from fastapi.testclient import TestClient

from mas.agents import (
    DemandAgent,
    EquipmentAgent,
    InventoryAgent,
    PlanningAgent,
    QualityAgent,
    SupplyAgent,
)
from mas.api.server import MASApiServer
from mas.domain import Factory
from mas.intelligence.decision_router import HybridDecisionRouter
from mas.intelligence.llm import LLMClient
from mas.messaging.broker import MessageBroker
from mas.runtime.factory_runtime import FactoryRuntime


def _make_api_with_runtime():
    env = Factory()
    broker = MessageBroker()
    llm = LLMClient(api_key="")
    router = HybridDecisionRouter(llm_client=llm)
    agents = [
        EquipmentAgent(),
        QualityAgent(),
        SupplyAgent(),
        DemandAgent(),
        InventoryAgent(),
        PlanningAgent(llm_client=llm),
    ]
    for agent in agents:
        broker.register(agent)
    runtime = FactoryRuntime(env, broker, agents, llm=llm, decision_router=router)
    api = MASApiServer(port=8787)
    api.bind(
        broker=broker,
        llm=llm,
        env=env,
        agents=agents,
        runtime=runtime,
        decision_router=router,
    )
    return api, runtime


def test_approve_pending_packet_endpoint():
    api, runtime = _make_api_with_runtime()
    runtime._pending_approval_packet = {
        "best_agent": "QA",
        "requires_approval": True,
        "schedule": {"target_speed_pct": 78},
    }

    client = TestClient(api.app)
    response = client.post("/api/approvals/approve", json={"approver": "lead", "note": "approved"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["approved"] is True
    assert runtime.get_pending_approval_packet() == {}
    assert runtime.get_last_orchestration_packet()["approval"]["status"] == "APPROVED"


def test_reject_pending_packet_endpoint():
    api, runtime = _make_api_with_runtime()
    runtime._pending_approval_packet = {
        "best_agent": "QA",
        "requires_approval": True,
        "schedule": {"target_speed_pct": 78},
    }

    client = TestClient(api.app)
    response = client.post("/api/approvals/reject", json={"approver": "lead", "reason": "wait for sample check"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["rejected"] is True
    assert runtime.get_pending_approval_packet() == {}
    assert runtime.get_last_orchestration_packet()["approval"]["status"] == "REJECTED"
