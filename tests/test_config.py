from mas.core.config import Settings, get_settings


def _build_settings(**overrides):
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


def test_settings_cors_methods():
    s = _build_settings()
    assert s.cors_origin_list() == ["*"]

    s2 = _build_settings(cors_origins="http://a.com, http://b.com")
    assert s2.cors_origin_list() == ["http://a.com", "http://b.com"]


def test_settings_exposes_connector_fields():
    s = _build_settings(
        connector_mode="file",
        mes_file_path="data/mes.json",
        erp_file_path="data/erp.json",
        qms_file_path="data/qms.json",
    )
    assert s.connector_mode == "file"
    assert s.mes_file_path.endswith("mes.json")
    assert s.erp_file_path.endswith("erp.json")
    assert s.qms_file_path.endswith("qms.json")


def test_get_settings_cache():
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
