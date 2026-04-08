from mas.intelligence.monitoring_qa import _heuristic_answer


def test_heuristic_status_question():
    ctx = {
        "factory": {
            "cycle": 10,
            "clock": "08:30:00",
            "shift": "주간",
            "avg_oee": 0.82,
            "fg_stock": 100,
            "total_produced": 500,
            "scrap_count": 2,
        },
        "agents": {"EA": {"state": "활성"}, "PA": {"state": "대기"}},
        "broker": {"published": 1000, "avg_latency_ms": 1.2},
        "runtime": {"cnp_rounds_total": 3, "events": 50},
        "router_snapshot": {},
    }
    a = _heuristic_answer("현재 상태가 어때?", ctx)
    assert "OEE" in a or "82" in a or "0.82" in a or "스냅샷" in a
