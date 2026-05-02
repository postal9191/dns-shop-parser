import pytest

from parser.session_manager import (
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


class TestProxyPool:
    """Тесты для ProxyPool."""

    def test_proxy_pool_initialization(self):
        """ProxyPool инициализируется с корректными параметрами."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10005,
            user="testuser",
            password="testpass",
            concurrency=50,
        )

        assert pool._host == "proxy.example.com"
        assert pool._user == "testuser"
        assert pool._password == "testpass"
        assert pool.concurrency == 50
        assert pool._ports == [10000, 10001, 10002, 10003, 10004, 10005]
        assert len(pool._failed) == 0

    def test_proxy_pool_proxy_url_format(self):
        """proxy_url() возвращает корректный формат URL."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10005,
            user="user",
            password="pass",
        )

        url = pool.proxy_url(10000)

        assert url == "http://user:pass@proxy.example.com:10000"

    def test_proxy_pool_rotate_returns_different_ports(self):
        """rotate() возвращает разные порты при последовательных вызовах."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10002,
            user="user",
            password="pass",
        )

        ports = set()
        for _ in range(6):
            url = pool.rotate()
            assert url is not None
            # Извлекаем порт из URL
            port = int(url.rsplit(":", 1)[-1])
            ports.add(port)

        # После 6 вызовов должны были пройти все 3 порта
        assert len(ports) == 3

    def test_proxy_pool_random_port(self):
        """random_port() возвращает валидный порт."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10010,
            user="user",
            password="pass",
        )

        url = pool.random_port()
        assert url is not None
        port = int(url.rsplit(":", 1)[-1])
        assert 10000 <= port <= 10010

    def test_proxy_pool_mark_failed(self):
        """mark_failed() добавляет порт в failed set."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10002,
            user="user",
            password="pass",
        )

        pool.mark_failed(10001)

        assert 10001 in pool._failed
        assert 10000 not in pool._failed
        assert 10002 not in pool._failed

    def test_proxy_pool_rotate_skips_failed(self):
        """rotate() пропускает failed порты."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10002,
            user="user",
            password="pass",
        )

        pool.mark_failed(10001)

        # Первый вызов rotate должен вернуть один из живых портов
        url = pool.rotate()
        assert url is not None
        port = int(url.rsplit(":", 1)[-1])
        assert port in [10000, 10002]

    def test_proxy_pool_random_port_skips_failed(self):
        """random_port() не возвращает failed порты."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10001,
            user="user",
            password="pass",
        )

        pool.mark_failed(10000)

        url = pool.random_port()
        assert url is not None
        port = int(url.rsplit(":", 1)[-1])
        assert port == 10001

    def test_proxy_pool_all_failed_true(self):
        """all_failed() возвращает True когда все порты failed."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10001,
            user="user",
            password="pass",
        )

        assert pool.all_failed() is False
        pool.mark_failed(10000)
        assert pool.all_failed() is False
        pool.mark_failed(10001)
        assert pool.all_failed() is True

    def test_proxy_pool_rotate_returns_none_when_all_failed(self):
        """rotate() возвращает None когда все порты failed."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10001,
            user="user",
            password="pass",
        )

        pool.mark_failed(10000)
        pool.mark_failed(10001)

        assert pool.rotate() is None

    def test_proxy_pool_random_port_returns_none_when_all_failed(self):
        """random_port() возвращает None когда все порты failed."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10001,
            user="user",
            password="pass",
        )

        pool.mark_failed(10000)
        pool.mark_failed(10001)

        assert pool.random_port() is None

    def test_proxy_pool_reset(self):
        """reset() очищает failed и сбрасывает состояние."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10002,
            user="user",
            password="pass",
        )

        pool.mark_failed(10001)
        pool.using_native = True

        pool.reset()

        assert len(pool._failed) == 0
        assert pool.using_native is False
        assert pool._rotate_idx == 0

    def test_proxy_pool_using_native_property(self):
        """using_native property работает корректно."""
        pool = ProxyPool(
            host="proxy.example.com",
            port_start=10000,
            port_end=10001,
            user="user",
            password="pass",
        )

        assert pool.using_native is False

        pool.using_native = True
        assert pool.using_native is True

    def test_proxy_pool_empty_range_raises(self):
        """Пустой диапазон портов вызывает ValueError."""
        with pytest.raises(ValueError, match="port range is empty"):
            ProxyPool(
                host="proxy.example.com",
                port_start=100,
                port_end=50,
                user="user",
                password="pass",
            )
