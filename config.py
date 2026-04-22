import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class Config:
    telegram_token: str
    telegram_chat_id: str
    telegram_chat_admin: str
    api_base_url: str
    cookies_str: str
    city_cookie_path: str
    city_cookie_current: str
    db_path: str
    parse_interval: int
    max_retries: int
    retry_delay: float
    dns_login: str
    dns_password: str
    log_level: str

    # Параллельная обработка
    parse_concurrency: int = 5

    # Эндпоинты DNS (паттерн по аналогии с products-filters)
    filters_path: str = "/catalogMarkdown/markdown/products-filters/"
    products_path: str = "/catalogMarkdown/markdown/products/"

    # Chrome опции
    chrome_headless: bool = False
    chrome_profile_dir: str = ""

    # Кроссплатформенность
    use_platform_ua: bool = False  # Использовать реальный UserAgent для ОС

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("TELEGRAM_TOKEN", "").strip()
        # Telegram token необязателен, но если задан - нужен chat_id
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        admin_id = os.getenv("TELEGRAM_CHAT_ADMIN", "").strip()

        return cls(
            telegram_token=token,
            telegram_chat_id=chat_id,
            telegram_chat_admin=admin_id,
            api_base_url=os.getenv("API_BASE_URL", "https://www.dns-shop.ru").rstrip("/"),
            cookies_str=os.getenv("DNS_COOKIES", ""),
            city_cookie_path=os.getenv("CITY_COOKIE_PATH", "krasnodar"),
            city_cookie_current=os.getenv("CITY_COOKIE_CURRENT", "c5f58b981d1ed0bad05ae63f54072ea9dcdf57acef965084aa1e42e07b47de20a%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22current_path%22%3Bi%3A1%3Bs%3A133%3A%22%7B%22city%22%3A%22884019c7-cf52-11de-b72b-00151716f9f5%22%2C%22cityName%22%3A%22%5Cu041a%5Cu0440%5Cu0430%5Cu0441%5Cu043d%5Cu043e%5Cu0434%5Cu0430%5Cu0440%22%2C%22method%22%3A%22manual%22%7D%22%3B%7D"),
            db_path=os.getenv("DB_PATH", "dns_monitor.db"),
            parse_interval=int(os.getenv("PARSE_INTERVAL", "3600")),  # 1 час
            parse_concurrency=int(os.getenv("PARSE_CONCURRENCY", "5")),
            max_retries=int(os.getenv("MAX_RETRIES", "4")),
            retry_delay=float(os.getenv("RETRY_DELAY", "5.0")),
            dns_login=os.getenv("DNS_LOGIN", ""),
            dns_password=os.getenv("DNS_PASSWORD", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),  # INFO, DEBUG
            chrome_headless=os.getenv("CHROME_HEADLESS", "false").lower() == "true",
            chrome_profile_dir=os.getenv("CHROME_PROFILE_DIR", ""),
            use_platform_ua=os.getenv("USE_PLATFORM_UA", "false").lower() == "true",
        )


config = Config.from_env()
