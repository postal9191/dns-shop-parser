class CookiesExpiredError(Exception):
    """Куки DNS устарели: получена Qrator-challenge или 401/403."""

class NetworkError(Exception):
    """Ошибка сети при обращении к DNS API."""

class ParsingError(Exception):
    """Ошибка разбора ответа DNS API."""

class RateLimitError(Exception):
    """DNS API вернул 429 Too Many Requests."""
