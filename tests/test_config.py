import os

import pytest

from config import Config


def test_config_defaults(monkeypatch):
    """Config имеет дефолты для опциональных полей."""
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    config = Config.from_env()

    assert config.filters_path == "/catalogMarkdown/markdown/products-filters/"
    assert config.products_path == "/catalogMarkdown/markdown/products/"
    assert config.use_platform_ua is False


def test_config_parse_interval_as_int(monkeypatch):
    """parse_interval парсится как int."""
    monkeypatch.setenv("PARSE_INTERVAL", "1800")

    config = Config.from_env()

    assert config.parse_interval == 1800
    assert isinstance(config.parse_interval, int)


def test_config_retry_delay_as_float(monkeypatch):
    """retry_delay парсится как float."""
    monkeypatch.setenv("RETRY_DELAY", "2.5")

    config = Config.from_env()

    assert config.retry_delay == 2.5
    assert isinstance(config.retry_delay, float)


def test_config_use_platform_ua_true(monkeypatch):
    """use_platform_ua=True при USE_PLATFORM_UA=true."""
    monkeypatch.setenv("USE_PLATFORM_UA", "true")

    config = Config.from_env()

    assert config.use_platform_ua is True


def test_config_api_base_url_strips_slash(monkeypatch):
    """api_base_url обрезает trailing slash."""
    monkeypatch.setenv("API_BASE_URL", "https://example.com/")

    config = Config.from_env()

    assert config.api_base_url == "https://example.com"


def test_config_telegram_optional(monkeypatch):
    """telegram_token и chat_id опциональны."""
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    config = Config.from_env()

    assert config.telegram_token == ""
    assert config.telegram_chat_id == ""


class TestProxyConfig:
    """Тесты для proxy конфигурации."""

    def test_proxy_config_defaults(self, monkeypatch):
        """Proxy поля имеют дефолты."""
        monkeypatch.delenv("PROXY_HOST", raising=False)
        monkeypatch.delenv("PROXY_PORT_START", raising=False)
        monkeypatch.delenv("PROXY_PORT_END", raising=False)
        monkeypatch.delenv("PROXY_USER", raising=False)
        monkeypatch.delenv("PROXY_PASSWORD", raising=False)
        monkeypatch.delenv("PROXY_CONCURRENCY", raising=False)

        config = Config.from_env()

        assert config.proxy_host == ""
        assert config.proxy_port_start == 0
        assert config.proxy_port_end == 10999
        assert config.proxy_user == ""
        assert config.proxy_password == ""
        assert config.proxy_concurrency == 100

    def test_proxy_enabled_returns_true_when_host_and_port_set(self, monkeypatch):
        """proxy_enabled() возвращает True когда host и port настроены."""
        monkeypatch.setenv("PROXY_HOST", "pool.proxy.market")
        monkeypatch.setenv("PROXY_PORT_START", "10000")

        config = Config.from_env()

        assert config.proxy_enabled() is True

    def test_proxy_enabled_returns_false_when_no_host(self, monkeypatch):
        """proxy_enabled() возвращает False когда host пустой."""
        monkeypatch.setenv("PROXY_HOST", "")
        monkeypatch.setenv("PROXY_PORT_START", "10000")

        config = Config.from_env()

        assert config.proxy_enabled() is False

    def test_proxy_enabled_returns_false_when_no_port(self, monkeypatch):
        """proxy_enabled() возвращает False когда port_start = 0."""
        monkeypatch.setenv("PROXY_HOST", "pool.proxy.market")
        monkeypatch.setenv("PROXY_PORT_START", "0")

        config = Config.from_env()

        assert config.proxy_enabled() is False

    def test_proxy_config_parsed_correctly(self, monkeypatch):
        """Proxy конфиг парсится корректно."""
        monkeypatch.setenv("PROXY_HOST", "pool.proxy.market")
        monkeypatch.setenv("PROXY_PORT_START", "10000")
        monkeypatch.setenv("PROXY_PORT_END", "10999")
        monkeypatch.setenv("PROXY_USER", "testuser")
        monkeypatch.setenv("PROXY_PASSWORD", "testpass")
        monkeypatch.setenv("PROXY_CONCURRENCY", "50")

        config = Config.from_env()

        assert config.proxy_host == "pool.proxy.market"
        assert config.proxy_port_start == 10000
        assert config.proxy_port_end == 10999
        assert config.proxy_user == "testuser"
        assert config.proxy_password == "testpass"
        assert config.proxy_concurrency == 50

    def test_proxy_enabled_with_all_values(self, monkeypatch):
        """proxy_enabled() True когда все значения заданы."""
        monkeypatch.setenv("PROXY_HOST", "proxy.example.com")
        monkeypatch.setenv("PROXY_PORT_START", "8080")
        monkeypatch.setenv("PROXY_USER", "user")
        monkeypatch.setenv("PROXY_PASSWORD", "pass")

        config = Config.from_env()

        assert config.proxy_enabled() is True
