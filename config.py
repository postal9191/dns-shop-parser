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
    city_cookie_path: str
    city_cookie_current: str
    db_path: str
    parse_interval: int
    max_retries: int
    retry_delay: float
    log_level: str

    # Параллельная обработка
    parse_concurrency: int = 5

    # Эндпоинты DNS (паттерн по аналогии с products-filters)
    filters_path: str = "/catalogMarkdown/markdown/products-filters/"
    products_path: str = "/catalogMarkdown/markdown/products/"

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
            city_cookie_path=os.getenv("CITY_COOKIE_PATH", ""),
            city_cookie_current=os.getenv("CITY_COOKIE_CURRENT", ""),
            db_path=os.getenv("DB_PATH", "dns_monitor.db"),
            parse_interval=int(os.getenv("PARSE_INTERVAL", "3600")),  # 1 час
            parse_concurrency=int(os.getenv("PARSE_CONCURRENCY", "5")),
            max_retries=int(os.getenv("MAX_RETRIES", "4")),
            retry_delay=float(os.getenv("RETRY_DELAY", "5.0")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),  # INFO, DEBUG
            use_platform_ua=os.getenv("USE_PLATFORM_UA", "false").lower() == "true",
        )


config = Config.from_env()
