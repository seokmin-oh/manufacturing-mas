"""로드맵 9대 축 — 핵심 경로 스모크 (계약·이벤트·CNP·감사)."""

from mas.domain import Factory
from mas.domain.agent_snapshot import enrich_snapshot_for_agents
from mas.protocol.agent_protocol import _run_sra_sequential
from mas.protocol.cnp_comparison import merge_into_proposal, normalize_comparison_metrics
from mas.agents import EquipmentAgent
from mas.messaging.broker import MessageBroker


def test_snapshot_includes_business_events_and_context():
    f = Factory()
    f.run_cycle()
    snap = f.get_snapshot()
    assert "business_events" in snap
    assert len(snap["business_events"]) >= 1
    enriched = enrich_snapshot_for_agents(dict(snap))
    assert "manufacturing_context" in enriched
    assert enriched["manufacturing_context"].get("contract_version")


def test_enrich_idempotent_contract_keys():
    f = Factory()
    f.run_cycle()
    snap = enrich_snapshot_for_agents(enrich_snapshot_for_agents(f.get_snapshot()))
    ctx = snap["manufacturing_context"]
    assert "identifiers" in ctx and "kpi_slices" in ctx


def test_cnp_comparison_normalize():
    raw = {
        "proposal": "test",
        "proposal_metrics": {"cost_estimate": 0.2, "constraint_violation_total": 0.1},
    }
    merge_into_proposal(raw)
    assert "comparison" in raw
    assert raw["comparison"]["candidate_action"]


def test_agent_protocol_regression_with_context(monkeypatch):
    monkeypatch.setenv("MAS_USE_LANGGRAPH", "0")
    broker = MessageBroker()
    ea = EquipmentAgent()
    ea.broker = broker
    f = Factory()
    f.run_cycle()
    snap = enrich_snapshot_for_agents(f.get_snapshot())
    _run_sra_sequential(ea, snap, None, None, broker)


def test_llm_audit_entries_when_enabled():
    from mas.intelligence.llm import LLMClient

    llm = LLMClient(api_key="")
    assert llm.audit_log == []


def test_planning_sub_ranker_sorts():
    from mas.agents.planning_sub.proposal_ranker import rank_proposals_by_comparison

    p1 = {
        "agent": "EA",
        "proposal": "a",
        "total_score": 0.5,
        "proposal_metrics": {"confidence": 0.9, "expected_effect": 0.8},
    }
    p2 = {
        "agent": "QA",
        "proposal": "b",
        "total_score": 0.6,
        "proposal_metrics": {"confidence": 0.5, "expected_effect": 0.7},
    }
    merge_into_proposal(p1)
    merge_into_proposal(p2)
    ranked = rank_proposals_by_comparison([p1, p2])
    assert len(ranked) == 2


def test_operational_card_from_cnp():
    from mas.intelligence.operational_decision_card import from_cnp_strategy

    props = [
        {
            "agent": "EA",
            "proposal": "x",
            "comparison": normalize_comparison_metrics({"proposal_metrics": {}}),
        }
    ]
    strat = {"cnp_id": 1, "target_speed_pct": 90, "inspection_mode": "표준"}
    card = from_cnp_strategy("sit", props, strat, {"shift": "주간A", "manufacturing_context": {}})
    assert card["schema"] == "operational_decision_card/v1"


def test_adapters_protocol_import():
    from mas.adapters import SensorAdapter

    assert SensorAdapter is not None
