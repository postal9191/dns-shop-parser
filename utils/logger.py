import logging
import logging.handlers
from pathlib import Path


def setup_logger(name: str = "dns_monitor") -> logging.Logger:
    Path("logs").mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt_console = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt_console)

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
