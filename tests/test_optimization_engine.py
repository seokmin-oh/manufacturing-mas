"""수치 솔버·컨텍스트 빌드·LLM 병합."""

from mas.intelligence.optimization_engine import (
    build_llm_context,
    cnp_numeric_strategy,
    merge_numeric_and_rationale,
)


def test_cnp_numeric_strategy_picks_highest_score():
    props = [
        {"agent": "EA", "total_score": 0.5, "speed_recommendation": 80, "inspection_mode": "standard"},
        {"agent": "QA", "total_score": 0.82, "speed_recommendation": 70, "inspection_mode": "enhanced"},
    ]
    n = cnp_numeric_strategy(props)
    assert n["best_agent"] == "QA"
    assert n["target_speed_pct"] == 70
    assert n["inspection_mode"] == "enhanced"


def test_merge_keeps_numeric_over_llm_speed():
    numeric = {"target_speed_pct": 70, "best_agent": "QA", "best_score": 0.8, "decision": "solver_first"}
    llm_part = {"target_speed_pct": 99, "rationale": ["QA 중심"], "risk_assessment": "낮음"}
    m = merge_numeric_and_rationale(numeric, llm_part)
    assert m["target_speed_pct"] == 70
    assert m["rationale"] == ["QA 중심"]


def test_build_llm_context_fills_warehouse_fallback():
    snap = {"fg_stock": 12, "stations": {"WC-01": {"sensors": {"vibration": {"value": 2.1, "ma": 2.0, "slope": 0.01}}}}}
    ctx = build_llm_context(snap)
    assert ctx["warehouse"]["stock"] == 12
    assert "domain_signals" in ctx
