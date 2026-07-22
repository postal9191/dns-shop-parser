"""Тесты для redaction секретов в логах."""
import logging
import pytest

from dns_shop_parser.utils.logger import (
    SecretRedactionFilter,
    _fingerprint,
    redact_cookie_value,
)


class TestFingerprint:
    def test_returns_hex_string(self):
        fp = _fingerprint("test_value")
        assert len(fp) == 8
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic(self):
        assert _fingerprint("same") == _fingerprint("same")

    def test_different_values_differ(self):
        assert _fingerprint("value1") != _fingerprint("value2")


class TestRedactCookieValue:
    def test_format(self):
        result = redact_cookie_value("PHPSESSID", "abc123secret")
        assert result.startswith("PHPSESSID=")
        assert "abc123secret" not in result
        # Формат: name=sha256[:8]
        fp = result.split("=", 1)[1]
        assert len(fp) == 8

    def test_different_cookies_different_fingerprints(self):
        r1 = redact_cookie_value("PHPSESSID", "value1")
        r2 = redact_cookie_value("PHPSESSID", "value2")
        assert r1 != r2


class TestSecretRedactionFilter:
    def test_redacts_cookie_header(self):
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0,
            "Cookie: PHPSESSID=supersecret123; qrator_jsid=anothersecret",
            (), None
        )
        f.filter(record)
        assert "supersecret123" not in record.msg
        assert "anothersecret" not in record.msg

    def test_redacts_authorization(self):
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0,
            "authorization: Bearer my_super_secret_token_here",
            (), None
        )
        f.filter(record)
        assert "my_super_secret_token_here" not in record.msg

    def test_redacts_csrf_token(self):
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0,
            "csrf_token=abcdef1234567890",
            (), None
        )
        f.filter(record)
        assert "abcdef1234567890" not in record.msg

    def test_redacts_telegram_token(self):
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0,
            "Using token 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ12345678",
            (), None
        )
        f.filter(record)
        assert "ABCdefGHIjklMNOpqrSTUvwxYZ12345678" not in record.msg

    def test_passes_normal_messages(self):
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0,
            "Normal log message without secrets",
            (), None
        )
        assert f.filter(record) is True
        assert record.msg == "Normal log message without secrets"

    def test_redacts_in_args(self):
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0,
            "Headers: %s",
            ("Cookie: PHPSESSID=secretvalue123",),
            None
        )
        f.filter(record)
        # Args should also be redacted
        assert isinstance(record.args, tuple)
        assert "secretvalue123" not in record.args[0]
