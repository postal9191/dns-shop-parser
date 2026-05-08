import pytest

from data.cities import CITIES, CITY_COOKIES, DEFAULT_CITY_SLUG, get_city_cookies
from parser.session_manager import SessionManager


def test_only_three_supported_cities_are_enabled():
    assert CITIES == {
        "Москва": "moscow",
        "Санкт-Петербург": "spb",
        "Краснодар": "krasnodar",
    }
    assert set(CITY_COOKIES) == {"moscow", "spb", "krasnodar"}
    assert DEFAULT_CITY_SLUG == "krasnodar"


def test_get_city_cookies_returns_city_path_and_current_path():
    cookies = get_city_cookies("spb")

    assert cookies["city_path"] == "spb"
    assert cookies["current_path"].startswith("2833842207c764")


def test_get_city_cookies_rejects_unknown_slug():
    with pytest.raises(ValueError, match="Unsupported city slug"):
        get_city_cookies("novosibirsk")


def test_session_manager_rejects_unknown_city_before_init():
    with pytest.raises(ValueError, match="Unsupported city slug"):
        SessionManager(city_slug="novosibirsk")


@pytest.mark.asyncio
async def test_session_manager_applies_selected_city_cookies():
    session_mgr = SessionManager(city_slug="moscow")

    async def fake_qrator():
        return True

    session_mgr._resolve_qrator = fake_qrator

    result = await session_mgr._init_session()

    assert result is True
    assert session_mgr._cookies["city_path"] == "moscow"
    assert session_mgr._cookies["current_path"] == get_city_cookies("moscow")["current_path"]
