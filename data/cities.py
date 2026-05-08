"""Supported DNS city metadata and regional cookies."""

DEFAULT_CITY_SLUG = "krasnodar"

CITIES: dict[str, str] = {
    "Москва": "moscow",
    "Санкт-Петербург": "spb",
    "Краснодар": "krasnodar",
}

CITY_COOKIES: dict[str, dict[str, str]] = {
    "moscow": {
        "city_path": "moscow",
        "current_path": "75a2da2a93c8cd1c2e00f91901d024508daafdcdf99566e6de24aeb998c59557a%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22current_path%22%3Bi%3A1%3Bs%3A114%3A%22%7B%22city%22%3A%2230b7c1f3-03fb-11dc-95ee-00151716f9f5%22%2C%22cityName%22%3A%22%5Cu041C%5Cu043E%5Cu0441%5Cu043A%5Cu0432%5Cu0430%22%2C%22method%22%3A%22geoip%22%7D%22%3B%7D",
    },
    "spb": {
        "city_path": "spb",
        "current_path": "2833842207c764717eda226cb515bc459f2b17151dd158960f604415a83a10bfa%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22current_path%22%3Bi%3A1%3Bs%3A164%3A%22%7B%22city%22%3A%22566ca284-5bea-11e2-aee1-00155d030b1f%22%2C%22cityName%22%3A%22%5Cu0421%5Cu0430%5Cu043D%5Cu043A%5Cu0442-%5Cu041F%5Cu0435%5Cu0442%5Cu0435%5Cu0440%5Cu0431%5Cu0443%5Cu0440%5Cu0433%22%2C%22method%22%3A%22manual%22%7D%22%3B%7D",
    },
    "krasnodar": {
        "city_path": "krasnodar",
        "current_path": "c5f58b981d1ed0bad05ae63f54072ea9dcdf57acef965084aa1e42e07b47de20a%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22current_path%22%3Bi%3A1%3Bs%3A133%3A%22%7B%22city%22%3A%22884019c7-cf52-11de-b72b-00151716f9f5%22%2C%22cityName%22%3A%22%5Cu041A%5Cu0440%5Cu0430%5Cu0441%5Cu043D%5Cu043E%5Cu0434%5Cu0430%5Cu0440%22%2C%22method%22%3A%22manual%22%7D%22%3B%7D",
    },
}

SLUG_TO_CITY: dict[str, str] = {v: k for k, v in CITIES.items()}


def get_city_cookies(city_slug: str) -> dict[str, str]:
    """Return DNS regional cookies for a supported city slug."""
    try:
        return CITY_COOKIES[city_slug]
    except KeyError as exc:
        supported = ", ".join(sorted(CITY_COOKIES))
        raise ValueError(f"Unsupported city slug '{city_slug}'. Supported: {supported}") from exc
