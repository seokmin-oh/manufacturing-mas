"""설정 로드 및 기본값."""

from mas.core.config import Settings, get_settings


def test_settings_cors_methods():
    s = Settings("127.0.0.1", 8787, 2.0, "gpt-4o-mini", "", "INFO", "", "*", "pa_only", False)
    assert s.cors_origin_list() == ["*"]
    s2 = Settings(
        "127.0.0.1", 8787, 2.0, "gpt-4o-mini", "", "INFO", "",
        "http://a.com, http://b.com", "pa_only", False,
    )
    assert "http://a.com" in s2.cors_origin_list()


def test_get_settings_cache():
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
