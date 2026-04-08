import json
from types import SimpleNamespace

from mas.agents.demand_agent import DemandAgent
from mas.agents.equipment_agent import EquipmentAgent
from mas.agents.inventory_agent import InventoryAgent
from mas.agents.planning_agent import PlanningAgent
from mas.agents.quality_agent import QualityAgent
from mas.agents.supply_agent import SupplyAgent
from mas.api.server import MASApiServer
from mas.domain import Factory
from mas.intelligence.decision_router import HybridDecisionRouter
from mas.intelligence.llm import LLMClient
from mas.messaging.broker import MessageBroker


def test_monitoring_payload_schema_smoke():
    env = Factory()
    env.run_cycle()

    broker = MessageBroker()
    llm = LLMClient(api_key="")
    router = HybridDecisionRouter(llm_client=llm)
    runtime = SimpleNamespace(uptime=1.0, total_events=0, cnp_count=0)

    agents = [
        EquipmentAgent(),
        QualityAgent(),
        SupplyAgent(),
        DemandAgent(),
        InventoryAgent(),
        PlanningAgent(llm_client=llm),
    ]
    for agent in agents:
        agent.broker = broker

    api = MASApiServer(port=8787)
    api.bind(
        broker=broker,
        llm=llm,
        env=env,
        agents=agents,
        runtime=runtime,
        decision_router=router,
    )

    payload = api._build_monitoring_payload()

    required_top_keys = {
        "timestamp",
        "manufacturing_context",
        "factory_coverage",
        "multi_agent_teams",
        "control_matrix",
        "factory",
        "agents",
        "broker",
        "llm",
        "decision_router",
        "external_connectors",
        "coordination_layer",
        "runtime",
    }
    assert required_top_keys.issubset(payload.keys())

    mctx = payload["manufacturing_context"]
    assert isinstance(mctx, dict)
    assert "contract_version" in mctx
    assert "identifiers" in mctx
    assert "kpi_slices" in mctx
    assert payload["manufacturing_context_validation"] == []

    factory = payload["factory"]
    assert isinstance(factory, dict)
    assert "cycle" in factory and factory["cycle"] >= 1
    assert "avg_oee" in factory

    agents_out = payload["agents"]
    assert isinstance(agents_out, dict)
    assert {"EA", "QA", "SA", "DA", "IA", "PA"}.issubset(agents_out.keys())

    connectors = payload["external_connectors"]
    assert connectors["mode"] in {"off", "sample", "file", "rest"}
    assert {"mes", "erp", "qms"}.issubset(connectors.keys())

    coordination = payload["coordination_layer"]
    assert isinstance(coordination, dict)
    assert "last_decision_packet" in coordination
    assert "pending_approval_packet" in coordination

    json.dumps(payload, allow_nan=False)
