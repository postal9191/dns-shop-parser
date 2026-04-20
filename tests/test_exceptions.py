import pytest

from parser.exceptions import CookiesExpiredError


def test_cookies_expired_error_is_exception():
    """CookiesExpiredError является подклассом Exception."""
    assert issubclass(CookiesExpiredError, Exception)


def test_cookies_expired_error_can_be_raised_and_caught():
    """CookiesExpiredError можно raise и catch."""
    with pytest.raises(CookiesExpiredError):
        raise CookiesExpiredError("Куки истекли")


def test_cookies_expired_error_preserves_message():
    """CookiesExpiredError сохраняет сообщение."""
    message = "Куки DNS истекли (401/403)"

    with pytest.raises(CookiesExpiredError) as exc_info:
        raise CookiesExpiredError(message)

    assert str(exc_info.value) == message
