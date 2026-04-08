"""collaboration_view 페이로드 스모크 테스트."""

from mas.intelligence.collaboration_view import build_collaboration_payload


def test_build_collaboration_payload_shape():
    p = build_collaboration_payload(broker=None)
    assert "summary" in p
    assert "nodes" in p and "PA" in p["nodes"]
    assert "edges" in p and len(p["edges"]) >= 10
    assert p["nodes"]["EA"]["x"] > 0
    e0 = p["edges"][0]
    assert "from" in e0 and "to" in e0 and "recent_count" in e0
