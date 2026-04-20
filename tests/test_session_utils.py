import json

import pytest

from parser.session_manager import (
    SessionManager,
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
