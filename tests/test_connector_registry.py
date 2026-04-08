from mas.core.config import Settings
from mas.integration import build_connector_status, build_connector_suite
from mas.integration.live_connectors import FileERPConnector, FileMESConnector, FileQMSConnector
from mas.integration.sample_connectors import SampleERPConnector, SampleMESConnector, SampleQMSConnector


def _settings(**overrides):
    data = {
        "api_host": "127.0.0.1",
        "api_port": 8787,
        "takt_sec": 2.0,
        "llm_model": "gpt-4o-mini",
        "llm_domain_model": "",
        "log_level": "INFO",
        "api_bearer_token": "",
        "cors_origins": "*",
        "llm_router_scope": "pa_only",
        "llm_per_agent_assist": False,
        "connector_mode": "sample",
        "mes_file_path": "",
        "erp_file_path": "",
        "qms_file_path": "",
        "mes_base_url": "",
        "erp_base_url": "",
        "qms_base_url": "",
    }
    data.update(overrides)
    return Settings(**data)


def test_connector_suite_builds_sample_connectors():
    suite = build_connector_suite(_settings(connector_mode="sample"))
    assert isinstance(suite["mes"], SampleMESConnector)
    assert isinstance(suite["erp"], SampleERPConnector)
    assert isinstance(suite["qms"], SampleQMSConnector)


def test_connector_suite_builds_file_connectors():
    suite = build_connector_suite(
        _settings(
            connector_mode="file",
            mes_file_path="mes.json",
            erp_file_path="erp.json",
            qms_file_path="qms.json",
        )
    )
    assert isinstance(suite["mes"], FileMESConnector)
    assert isinstance(suite["erp"], FileERPConnector)
    assert isinstance(suite["qms"], FileQMSConnector)


def test_connector_status_reports_file_configuration(tmp_path):
    mes = tmp_path / "mes.json"
    mes.write_text("[]", encoding="utf-8")
    status = build_connector_status(
        _settings(
            connector_mode="file",
            mes_file_path=str(mes),
            erp_file_path=str(tmp_path / "erp.json"),
            qms_file_path=str(tmp_path / "qms.json"),
        )
    )
    assert status["mode"] == "file"
    assert status["mes"]["configured"] is True
    assert status["mes"]["exists"] is True
    assert status["erp"]["exists"] is False


def test_connector_status_reports_rest_configuration():
    status = build_connector_status(
        _settings(
            connector_mode="rest",
            mes_base_url="http://mes.local",
            erp_base_url="http://erp.local",
            qms_base_url="http://qms.local",
        )
    )
    assert status["mode"] == "rest"
    assert status["mes"]["base_url"] == "http://mes.local"
    assert status["erp"]["configured"] is True
    assert status["qms"]["configured"] is True
