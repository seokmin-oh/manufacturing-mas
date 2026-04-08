"""SRA LangGraph 경로와 순차 폴백 동등성."""

import pytest

from mas.protocol.agent_protocol import AGENT_PROTOCOL_ID, _run_sra_sequential, run_cycle_with_router
from mas.agents.base_agent import BaseAgent

pytest.importorskip("langgraph")


class _StubAgent(BaseAgent):
    def __init__(self):
        super().__init__("STUB", "stub")

    def sense(self, snapshot: dict) -> dict:
        return {"alerts": [], "cycle": snapshot.get("cycle", 0)}

    def reason(self, observations: dict):
        return {"type": "stub", "action": "monitor"}

    def act(self, decision):
        return []

    def handle_cfp(self, cfp_data):
        return None

    def execute_accepted_proposal(self, proposal):
        pass


def test_agent_protocol_id():
    assert "sra" in AGENT_PROTOCOL_ID


def test_langgraph_matches_sequential(monkeypatch):
    from mas.protocol.sra_langgraph import clear_sra_graph_cache, invoke_sra_graph

    clear_sra_graph_cache()
    monkeypatch.setenv("MAS_USE_LANGGRAPH", "1")

    agent = _StubAgent()
    snap = {"cycle": 1, "stations": {}}

    d_graph = invoke_sra_graph(agent, snap, None, None, None)
    agent2 = _StubAgent()
    d_seq = _run_sra_sequential(agent2, snap, None, None, None)

    assert d_graph == d_seq


def test_run_cycle_with_router_uses_graph_when_enabled(monkeypatch):
    from mas.protocol.sra_langgraph import clear_sra_graph_cache

    clear_sra_graph_cache()
    monkeypatch.setenv("MAS_USE_LANGGRAPH", "1")

    agent = _StubAgent()
    snap = {"cycle": 2, "stations": {}}
    out = run_cycle_with_router(agent, snap, None, None, None)
    assert out is not None
    assert out.get("type") == "stub"


def test_fallback_when_disabled(monkeypatch):
    from mas.protocol.sra_langgraph import clear_sra_graph_cache

    clear_sra_graph_cache()
    monkeypatch.setenv("MAS_USE_LANGGRAPH", "0")

    agent = _StubAgent()
    snap = {"cycle": 3, "stations": {}}
    out = run_cycle_with_router(agent, snap, None, None, None)
    assert out.get("type") == "stub"


def test_langgraph_runtime_error_falls_back_to_sequential(monkeypatch):
    """그래프 invoke 실패 시 순차 SRA 로 동일 결과 보장."""
    import mas.protocol.sra_langgraph as lg

    clear = lg.clear_sra_graph_cache
    clear()
    monkeypatch.setenv("MAS_USE_LANGGRAPH", "1")

    def _broken_invoke(*args, **kwargs):
        raise RuntimeError("simulated graph failure")

    monkeypatch.setattr(lg, "invoke_sra_graph", _broken_invoke)

    agent = _StubAgent()
    snap = {"cycle": 4, "stations": {}}
    out = run_cycle_with_router(agent, snap, None, None, None)
    assert out is not None
    assert out.get("type") == "stub"
