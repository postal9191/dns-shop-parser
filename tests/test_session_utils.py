import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from dns_shop_parser.parser.session_manager import (
    SessionManager,
    ProxyPool,
    _get_base_headers,
    _parse_cookie_str,
)


class TestParseCookieStr:
    def test_parse_cookie_str_valid(self):
        """_parse_cookie_str - парсит валидную строку кук."""
        cookie_str = "key1=value1; key2=value2; key3=value3"

        result = _parse_cookie_str(cookie_str)

        assert result == {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        }

    def test_parse_cookie_str_empty_string(self):
        """_parse_cookie_str - пустая строка."""
        result = _parse_cookie_str("")

        assert result == {}

    def test_parse_cookie_str_single_cookie(self):
        """_parse_cookie_str - одна кука."""
        result = _parse_cookie_str("session=abc123")

        assert result == {"session": "abc123"}

    def test_parse_cookie_str_ignores_invalid_tokens(self):
        """_parse_cookie_str - игнорирует токены без =."""
        cookie_str = "key1=value1; invalid_token; key2=value2"

        result = _parse_cookie_str(cookie_str)

        assert "key1" in result
        assert "key2" in result
        assert "invalid_token" not in result

    def test_parse_cookie_str_strips_whitespace(self):
        """_parse_cookie_str - обрезает пробелы."""
        cookie_str = "  key1=value1  ;  key2=value2  "

        result = _parse_cookie_str(cookie_str)

        assert result == {"key1": "value1", "key2": "value2"}

    def test_parse_cookie_str_value_with_equals(self):
        """_parse_cookie_str - значение может содержать =."""
        cookie_str = "data=key=value; other=test"

        result = _parse_cookie_str(cookie_str)

        assert result["data"] == "key=value"
        assert result["other"] == "test"


class TestGetBaseHeaders:
    def test_get_base_headers_contains_user_agent(self):
        """_get_base_headers - содержит user-agent (lowercase)."""
        headers = _get_base_headers()

        assert "user-agent" in headers
        assert len(headers["user-agent"]) > 0

    def test_get_base_headers_contains_accept(self):
        """_get_base_headers - содержит accept (lowercase)."""
        headers = _get_base_headers()

        assert "accept" in headers

    def test_get_base_headers_contains_referer(self):
        """_get_base_headers - содержит referer (lowercase)."""
        headers = _get_base_headers()

        assert "referer" in headers

    def test_get_base_headers_is_dict(self):
        """_get_base_headers - возвращает dict."""
        headers = _get_base_headers()

        assert isinstance(headers, dict)
        assert all(isinstance(k, str) for k in headers.keys())
        assert all(isinstance(v, str) for v in headers.values())


class TestSessionManager:
    def test_session_manager_build_headers_with_cookies(self):
        """SessionManager._build_headers - включает cookie если есть куки."""
        sm = SessionManager()
        sm._cookies = {"session": "abc123", "user": "test"}

        headers = sm._build_headers()

        assert "cookie" in headers

    def test_session_manager_build_headers_without_cookies(self):
        """SessionManager._build_headers - не включает cookie если нет кук."""
        sm = SessionManager()
        sm._cookies = {}

        headers = sm._build_headers()

        assert "cookie" not in headers

    def test_session_manager_build_headers_with_csrf(self):
        """SessionManager._build_headers - включает x-csrf-token если задан."""
        sm = SessionManager()
        sm._csrf_token = "csrf-token-123"

        headers = sm._build_headers()

        assert "x-csrf-token" in headers
        assert headers["x-csrf-token"] == "csrf-token-123"

    def test_session_manager_build_headers_without_csrf(self):
        """SessionManager._build_headers - не включает x-csrf-token если не задан."""
        sm = SessionManager()
        sm._csrf_token = ""

        headers = sm._build_headers()

        assert "x-csrf-token" not in headers

    def test_session_manager_build_headers_with_extra(self):
        """SessionManager._build_headers - объединяет extra заголовки."""
        sm = SessionManager()
        sm._csrf_token = ""
        sm._cookies = {}

        headers = sm._build_headers({"X-Custom": "custom-value"})

        assert "X-Custom" in headers
        assert headers["X-Custom"] == "custom-value"

    def test_session_manager_set_csrf(self):
        """SessionManager.set_csrf - устанавливает CSRF токен."""
        sm = SessionManager()

        sm.set_csrf("token-123")

        assert sm._csrf_token == "token-123"

    @pytest.mark.asyncio
    async def test_proxy_request_passes_proxy_and_keeps_session_open(self):
        sm = SessionManager()
        sm._proxy_pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )
        sm._proxy_semaphore = asyncio.Semaphore(1)

        response = object()
        fake_session = MagicMock()
        fake_session.request = AsyncMock(return_value=response)
        fake_session.close = AsyncMock()
        sm.get_session = AsyncMock(return_value=fake_session)

        result = await sm._request_with_proxy_fallback(
            "GET",
            "https://example.com/catalog",
            {"x-test": "1"},
            timeout=10,
        )

        assert result is response
        fake_session.request.assert_awaited_once_with(
            "GET",
            "https://example.com/catalog",
            headers={"x-test": "1"},
            proxy="http://user:pass@proxy.example.com:10000",
            timeout=10,
        )
        fake_session.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proxy_request_uses_sticky_start_port_for_qrator_cookies(self):
        sm = SessionManager()
        sm._proxy_pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )
        sm._proxy_semaphore = asyncio.Semaphore(1)

        fake_session = MagicMock()
        fake_session.request = AsyncMock(return_value=object())
        sm.get_session = AsyncMock(return_value=fake_session)

        await sm._request_with_proxy_fallback("GET", "https://example.com/one", None)
        await sm._request_with_proxy_fallback("GET", "https://example.com/two", None)

        proxies = [call.kwargs["proxy"] for call in fake_session.request.await_args_list]
        assert proxies == [
            "http://user:pass@proxy.example.com:10000",
            "http://user:pass@proxy.example.com:10000",
        ]


class TestProxyPool:
    """Тесты для single-port ProxyPool."""

    def test_proxy_pool_initialization(self):
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="testuser",
            password="testpass",
            concurrency=50,
        )

        assert pool._host == "proxy.example.com"
        assert pool._user == "testuser"
        assert pool._password == "testpass"
        assert pool.concurrency == 50
        assert pool._sticky_port == 10000
        assert len(pool._failed) == 0

    def test_proxy_pool_proxy_url_format(self):
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )

        assert pool.proxy_url(10000) == "http://user:pass@proxy.example.com:10000"

    def test_proxy_pool_sticky_rotate_and_random_return_same_port(self):
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )

        expected = "http://user:pass@proxy.example.com:10000"
        assert pool.sticky() == expected
        assert pool.rotate() == expected
        assert pool.random_port() == expected

    def test_proxy_pool_mark_failed_disables_single_port(self):
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )

        pool.mark_failed(10000)

        assert pool.all_failed() is True
        assert pool.sticky() is None
        assert pool.rotate() is None
        assert pool.random_port() is None

    def test_proxy_pool_reset(self):
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )

        pool.mark_failed(10000)
        pool.using_native = True

        pool.reset()

        assert len(pool._failed) == 0
        assert pool.using_native is False
        assert pool._rotate_idx == 0
        assert pool.sticky() == "http://user:pass@proxy.example.com:10000"

    def test_proxy_pool_using_native_property(self):
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            user="user",
            password="pass",
        )

        assert pool.using_native is False
        pool.using_native = True
        assert pool.using_native is True

    def test_proxy_pool_non_positive_port_raises(self):
        with pytest.raises(ValueError, match="port must be positive"):
            ProxyPool(
                host="proxy.example.com",
                port_start=0,
                user="user",
                password="pass",
            )
