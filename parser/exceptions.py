class CookiesExpiredError(Exception):
    """Куки DNS устарели: получена Qrator-challenge или 401/403."""
