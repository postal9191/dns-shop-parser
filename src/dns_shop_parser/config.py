import os
import platform
from dataclasses import dataclass

from dotenv import load_dotenv
from dns_shop_parser.utils.logger import logger

load_dotenv(override=True)


@dataclass
class Config:
    telegram_token: str
    telegram_chat_id: str
    telegram_chat_admin: str
    api_base_url: str
    db_path: str
    parse_interval: int
    max_retries: int
    retry_delay: float
    log_level: str
    qrator_init_timeout: float
    qrator_node_timeout: float
    qrator_proxy_check_timeout: float

    # Параллельная обработка
    parse_concurrency: int = 3

    # Эндпоинты DNS (паттерн по аналогии с products-filters)
    filters_path: str = "/catalogMarkdown/markdown/products-filters/"
    products_path: str = "/catalogMarkdown/markdown/products/"

    # Кроссплатформенность
    use_platform_ua: bool = False  # Использовать реальный UserAgent для ОС

    # Proxy (pool.proxy.market:10000–10999)
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_user: str = ""
    proxy_password: str = ""

    # Админ-бот (опционально)
    admin_telegram_token: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("TELEGRAM_TOKEN", "").strip()
        # Telegram token необязателен, но если задан - нужен chat_id
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        admin_id = os.getenv("TELEGRAM_CHAT_ADMIN", "").strip()

        default_qrator_init_timeout = "360" if platform.system().lower() == "linux" else "330"

        return cls(
            telegram_token=token,
            telegram_chat_id=chat_id,
            telegram_chat_admin=admin_id,
            admin_telegram_token=os.getenv("TELEGRAM_ADMIN_TOKEN", "").strip(),
            api_base_url=os.getenv("API_BASE_URL", "https://www.dns-shop.ru").rstrip("/"),
            db_path=os.getenv("DB_PATH", "dns_monitor.db"),
            parse_interval=int(os.getenv("PARSE_INTERVAL") or "3600"),  # 1 час
            parse_concurrency=int(os.getenv("PARSE_CONCURRENCY") or "5"),
            max_retries=int(os.getenv("MAX_RETRIES") or "4"),
            retry_delay=float(os.getenv("RETRY_DELAY") or "5.0"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),  # INFO, DEBUG
            qrator_init_timeout=float(os.getenv("QRATOR_INIT_TIMEOUT") or default_qrator_init_timeout),
            qrator_node_timeout=float(os.getenv("QRATOR_NODE_TIMEOUT") or "300"),
            qrator_proxy_check_timeout=float(os.getenv("QRATOR_PROXY_CHECK_TIMEOUT") or "20"),
            use_platform_ua=os.getenv("USE_PLATFORM_UA", "false").lower() == "true",
            proxy_host=os.getenv("PROXY_HOST", "").strip(),
            proxy_port=int(os.getenv("PROXY_PORT") or "0"),
            proxy_user=os.getenv("PROXY_USER", "").strip(),
            proxy_password=os.getenv("PROXY_PASSWORD", "").strip(),
        )

    def __post_init__(self):
        """Валидация критических полей после инициализации"""
        # Валидация токена Telegram
        if self.telegram_token and len(self.telegram_token) < 10:
            raise ValueError("Invalid telegram token format")

        # Валидация админского токена
        if self.admin_telegram_token and len(self.admin_telegram_token) < 10:
            raise ValueError("Invalid admin telegram token format")

        # Логирование настройки прокси без раскрытия пароля
        if self.proxy_password:
            logger.debug("Proxy configured with authentication")

    def proxy_enabled(self) -> bool:
        return bool(self.proxy_host and self.proxy_port > 0)

    def safe_repr(self) -> str:
        """Безопасное представление конфига для логирования"""
        return (f"Config(api_base_url={self.api_base_url}, "
                f"proxy_enabled={self.proxy_enabled()}, "
                f"parse_interval={self.parse_interval}, "
                f"log_level={self.log_level})")


config = Config.from_env()
