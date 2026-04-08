from mas.intelligence.mas_overview import build_mas_overview_payload


def test_mas_overview_payload():
    p = build_mas_overview_payload()
    assert "headline" in p and "lead" in p
    assert len(p["roles"]) == 6
    assert p["roles"][0]["id"] in ("EA", "QA", "SA", "DA", "IA", "PA")
    assert "collaboration" in p and len(p["collaboration"]["points"]) >= 3
