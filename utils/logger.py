import logging
import logging.handlers
import os
from pathlib import Path


def setup_logger(name: str = "dns_monitor") -> logging.Logger:
    Path("logs").mkdir(exist_ok=True)

    logger = logging.getLogger(name)

    # Очищаем старые обработчики если есть (для повторной инициализации)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Получаем уровень логирования из переменной окружения (по умолчанию INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, log_level_str, logging.INFO)

    # Логгер на DEBUG чтобы файл получал всё, консоль фильтруется отдельно
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Не распространяем логи родительским логгерам

    fmt_console = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(fmt_console)
    console.addFilter(lambda record: record.levelno >= console_level)  # Двойная фильтрация

    file_handler = logging.handlers.RotatingFileHandler(
        "logs/app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt_file)

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
