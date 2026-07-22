import hashlib
import logging
import logging.handlers
import os
import re
from pathlib import Path
from typing import Optional


# Паттерны для redaction секретов в логах
_SECRET_PATTERNS = [
    # Cookie header: "Cookie: name=value; name2=value2" → имена + fingerprints
    (re.compile(r'(cookie\s*[:=]\s*)([^\r\n]{10,})', re.IGNORECASE), r'\1[REDACTED]'),
    # CSRF токены
    (re.compile(r'(csrf[_-]?token\s*[:=]\s*)(\S{8,})', re.IGNORECASE), r'\1[REDACTED]'),
    # Authorization headers (Bearer tokens, Basic auth, etc.)
    (re.compile(r'(authorization\s*[:=]\s*\S*\s*)(\S{8,})', re.IGNORECASE), r'\1[REDACTED]'),
    # Telegram tokens (формат: цифры:буквы)
    (re.compile(r'(\d{8,10}:[A-Za-z0-9_-]{30,})'), '[TG_TOKEN_REDACTED]'),
]


def _fingerprint(value: str, length: int = 8) -> str:
    """Возвращает короткий SHA-256 fingerprint значения."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class SecretRedactionFilter(logging.Filter):
    """Фильтр, redact-ящий секреты в сообщениях логов.

    Заменяет чувствительные данные (cookies, CSRF, tokens) на [REDACTED]
    перед записью в файл/консоль.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg and isinstance(record.msg, str):
            for pattern, replacement in _SECRET_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
            # Также обрабатываем args если есть (для %s форматирования)
            if record.args:
                record.args = tuple(
                    _redact_value(a) if isinstance(a, str) else a
                    for a in (record.args if isinstance(record.args, tuple) else (record.args,))
                )
        return True


def _redact_value(s: str) -> str:
    """Redact-ит строковое значение, если содержит секретные паттерны."""
    for pattern, replacement in _SECRET_PATTERNS:
        s = pattern.sub(replacement, s)
    return s


def redact_cookie_value(cookie_name: str, cookie_value: str) -> str:
    """Возвращает безопасное представление cookie для логов.

    Формат: "имя=SHA256[:8]" — достаточно для отладки, не раскрывает значение.
    """
    return f"{cookie_name}={_fingerprint(cookie_value)}"


def setup_logger(name: str = "dns_monitor") -> logging.Logger:
    Path("logs").mkdir(exist_ok=True)

    logger = logging.getLogger(name)

    # Очищаем старые обработчики если есть (для повторной инициализации)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Получаем уровень логирования из переменной окружения (по умолчанию INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, log_level_str, logging.INFO)

    # Логгер на минимальный уровень — хендлеры фильтруют сами через setLevel
    logger.setLevel(console_level)
    logger.propagate = False  # Не распространяем логи родительским логгерам

    fmt_console = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Фильтр redaction — применяется ко всем хендлерам
    redaction_filter = SecretRedactionFilter()

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(fmt_console)
    console.addFilter(redaction_filter)

    # Файловый уровень: DEBUG для файла, но консоль контролируется LOG_LEVEL
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt_file)
    file_handler.addFilter(redaction_filter)

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
