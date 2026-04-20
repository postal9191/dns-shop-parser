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
    assert config.chrome_headless is False
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


def test_config_chrome_headless_true(monkeypatch):
    """chrome_headless=True при CHROME_HEADLESS=true."""
    monkeypatch.setenv("CHROME_HEADLESS", "true")

    config = Config.from_env()

    assert config.chrome_headless is True


def test_config_chrome_headless_false(monkeypatch):
    """chrome_headless=False при CHROME_HEADLESS=false."""
    monkeypatch.setenv("CHROME_HEADLESS", "false")

    config = Config.from_env()

    assert config.chrome_headless is False


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
