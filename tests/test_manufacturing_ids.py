"""표준 제조 식별자 단일 출처."""

import pytest

from mas.core.manufacturing_ids import AGENT_IDS, PROFILE_SCHEMA_VERSION, STATION_IDS


def test_station_count_and_format():
    assert len(STATION_IDS) == 6
    assert STATION_IDS[0] == "WC-01"
    assert STATION_IDS[-1] == "WC-06"


def test_agent_roster():
    assert len(AGENT_IDS) == 6
    assert "PA" in AGENT_IDS
    assert "EA" in AGENT_IDS


def test_profile_schema_version():
    assert PROFILE_SCHEMA_VERSION.startswith("mas.")


def test_api_manufacturing_profile():
    pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from mas.api.server import MASApiServer

    srv = MASApiServer(port=59998)
    if not srv.enabled:
        pytest.skip("FastAPI 미설치")
    client = TestClient(srv.app)
    r = client.get("/api/manufacturing/profile")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == PROFILE_SCHEMA_VERSION
    assert data["agent_ids"] == list(AGENT_IDS)
    assert data["station_ids"] == list(STATION_IDS)

