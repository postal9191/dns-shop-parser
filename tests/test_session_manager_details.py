"""
Тесты для SessionManager: непокрытые методы и ветви.
Покрываем _init_session с qrator retry, _resolve_qrator failure,
_build_headers, _extract_cookies_from_response, HTTPLogger.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
import aiohttp

from parser.session_manager import SessionManager, HTTPLogger


class TestSessionManagerInit:
    """Тесты инициализации SessionManager."""

    def test_default_init(self):
        sm = SessionManager()
        assert sm._initialized is False
        # city_slug по умолчанию → Krasnodar
        assert sm.city_slug == "krasnodar"
        # _city_cookies содержит городские куки для дефолтного города
        assert isinstance(sm._city_cookies, dict)

    def test_proxy_config_stored(self):
        with patch("parser.session_manager.config") as mock_cfg:
            mock_cfg.proxy_enabled.return_value = True
            mock_cfg.proxy_host = "proxy.example.com"
            mock_cfg.proxy_port = 8080
            mock_cfg.proxy_user = "user"
            mock_cfg.proxy_password = "pass"
            mock_cfg.parse_concurrency = 3

            sm = SessionManager()
            assert sm._proxy_pool is not None

    def test_no_proxy_when_disabled(self):
        with patch("parser.session_manager.config") as mock_cfg:
            mock_cfg.proxy_enabled.return_value = False
            sm = SessionManager()
            assert sm._proxy_pool is None


class TestBuildHeaders:
    """Тесты для _build_headers."""

    def test_includes_default_headers(self):
        sm = SessionManager()
        headers = sm._build_headers()
        assert "user-agent" in (k.lower() for k in headers)

    def test_adds_csrf_token(self):
        sm = SessionManager()
        sm.set_csrf("abc123")
        headers = sm._build_headers()
        assert headers.get("x-csrf-token") == "abc123"

    def test_adds_extra_headers(self):
        sm = SessionManager()
        headers = sm._build_headers({"X-Custom": "value"})
        assert "X-Custom" in headers
        assert headers["X-Custom"] == "value"


class TestExtractCookies:
    """Тесты для _extract_cookies_from_response."""

    def test_extracts_set_cookie_headers(self):
        sm = SessionManager()
        resp = Mock()
        resp.cookies = None
        resp.headers.getall.return_value = ["PHPSESSID=abc; Path=/", "_csrf=xyz; Path=/"]

        sm._extract_cookies_from_response(resp)
        assert sm._cookies.get("PHPSESSID") == "abc"
        assert sm._cookies.get("_csrf") == "xyz"

    def test_protected_city_cookies_not_overwritten(self):
        """city_path и current_path НЕ перезаписываются из Set-Cookie."""
        sm = SessionManager()
        sm._cookies["city_path"] = "old_value"
        sm._cookies["current_path"] = "old_cp"
        resp = Mock()
        resp.cookies = None
        resp.headers.getall.return_value = [
            "city_path=HACKED; Path=/",
            "some_cookie=val; Path=/",
        ]

        sm._extract_cookies_from_response(resp)
        assert sm._cookies["city_path"] == "old_value"
        assert sm._cookies["current_path"] == "old_cp"
        assert sm._cookies["some_cookie"] == "val"


class TestInitSessionSuccess:
    """Тесты для _init_session — успешный сценарий."""

    @pytest.mark.asyncio
    async def test_init_success(self):
        sm = SessionManager()
        with patch.object(sm, '_resolve_qrator', return_value=True):
            result = await sm._init_session()
            assert result is True
            assert sm._initialized is True


class TestInitSessionQratorFail:
    """Тесты для _init_session — Qrator не решается."""

    @pytest.mark.asyncio
    async def test_init_qrator_fails_on_first_try(self):
        sm = SessionManager()
        with patch.object(sm, '_resolve_qrator', return_value=False):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await sm._init_session()
                assert result is False

    @pytest.mark.asyncio
    async def test_init_qrator_fails_both_retries(self):
        sm = SessionManager()
        # Первый вызов: возвращает False → sleep → retry
        # Второй вызв: возвращает False → error log, returns False
        with patch.object(sm, '_resolve_qrator', return_value=False):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await sm._init_session()
                assert result is False


class TestInitSessionWithQratorRetry:
    """Тесты _init_session с retry Qrator."""

    @pytest.mark.asyncio
    async def test_qrator_succeeds_on_retry(self):
        sm = SessionManager()
        call_count = 0

        async def mock_resolve():
            nonlocal call_count
            call_count += 1
            return call_count >= 2  # Первый fail, второй success

        with patch.object(sm, '_resolve_qrator', side_effect=mock_resolve):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await sm._init_session()
                assert result is True
                assert call_count == 2


class TestResolveQrator:
    """Тесты для _resolve_qrator."""

    @pytest.mark.asyncio
    async def test_resolve_success(self):
        sm = SessionManager()
        with patch("parser.session_manager.resolve_qrator_cookies", new_callable=AsyncMock, return_value={"qrator_jsid2": "abc"}):
            result = await sm._resolve_qrator()
            assert result is True

    @pytest.mark.asyncio
    async def test_resolve_missing_jsid2(self):
        sm = SessionManager()
        with patch("parser.session_manager.resolve_qrator_cookies", new_callable=AsyncMock, return_value={}):
            result = await sm._resolve_qrator()
            assert result is False

    @pytest.mark.asyncio
    async def test_resolve_returns_none(self):
        sm = SessionManager()
        with patch("parser.session_manager.resolve_qrator_cookies", new_callable=AsyncMock, return_value=None):
            result = await sm._resolve_qrator()
            assert result is False


class TestSetCsrf:
    """Тесты для set_csrf."""

    def test_sets_token(self):
        sm = SessionManager()
        sm.set_csrf("token123")
        assert sm._csrf_token == "token123"


class TestCityCookiesInInitSession:
    """Тесты — городские куки применяются в _init_session."""

    @pytest.mark.asyncio
    async def test_city_cookies_applied_after_qrator(self):
        from data.cities import get_city_cookies
        expected = get_city_cookies("moscow")
        sm = SessionManager(city_slug="moscow")
        with patch.object(sm, '_resolve_qrator', return_value=True):
            await sm._init_session()
            assert sm._cookies["city_path"] == expected["city_path"]
            assert sm._cookies["current_path"] == expected["current_path"]


class TestInitSessionAlreadyInitialized:
    """Тесты edge cases для _init_session."""

    @pytest.mark.asyncio
    async def test_init_clears_cookies(self):
        sm = SessionManager()
        sm._cookies["old_cookie"] = "val"
        with patch.object(sm, '_resolve_qrator', return_value=True):
            await sm._init_session()
            # Куки очищаются в начале _init_session перед Qrator
            assert "old_cookie" not in sm._cookies


class TestHTTPLogger:
    """Тесты для HTTPLogger."""

    @pytest.mark.asyncio
    async def test_log_request(self):
        await HTTPLogger.log_request("GET", "http://example.com")

    @pytest.mark.asyncio
    async def test_log_request_with_params(self):
        await HTTPLogger.log_request("GET", "http://example.com", params={"q": "test"})

    @pytest.mark.asyncio
    async def test_log_response(self):
        await HTTPLogger.log_response(200, "http://example.com")

    @pytest.mark.asyncio
    async def test_log_cookies(self):
        await HTTPLogger.log_cookies({"a": "1", "b": "2"}, source="test")


class TestInitSessionForceQrator:
    """Тесты _init_session с force_qrator=True."""

    @pytest.mark.asyncio
    async def test_force_qrator_clears_profile(self):
        sm = SessionManager()
        mock_cleanup = Mock(return_value=True)
        with patch("parser.session_manager.cleanup_chromium_profile", mock_cleanup):
            with patch.object(sm, '_resolve_qrator', return_value=True):
                result = await sm._init_session(force_qrator=True)
                assert result is True
                mock_cleanup.assert_called_once()
