import sqlite3
import tempfile
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

import pytest

from parser.db_manager import DBManager
from parser.models import Product


@pytest.fixture
def db_memory():
    """Файловая SQLite база для тестирования (в temp)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        db = DBManager(db_path)
        try:
            yield db
        finally:
            # Принудительно закрываем все возможные соединения
            db.close()
            # Дополнительная очистка для Windows
            import gc
            gc.collect()
            # Принудительно закрываем все SQLite соединения к этому файлу
            try:
                # Создаем временное соединение и сразу закрываем для освобождения файла
                temp_conn = sqlite3.connect(db_path)
                temp_conn.close()
            except:
                pass


@pytest.fixture
def sample_product():
    """Пример товара для тестов."""
    return Product(
        id="as-AbCdEf",
        uuid="12345678-1234-1234-1234-123456789012",
        title="Тестовый ноутбук",
        price=50000,
        price_old=70000,
        url="https://dns-shop.ru/catalog/test/",
        category_id="cat-123",
        category_name="Ноутбуки",
        status="Новый",
        city_slug="moscow",
    )


@pytest.fixture
def sample_product_no_discount():
    """Товар без скидки."""
    return Product(
        id="as-XyZaBc",
        uuid="87654321-4321-4321-4321-210987654321",
        title="Монитор",
        price=10000,
        price_old=10000,
        url="https://dns-shop.ru/catalog/monitor/",
        category_id="cat-456",
        category_name="Мониторы",
        city_slug="moscow",
    )


@pytest.fixture(scope="session", autouse=True)
def _isolate_test_logging():
    """Prevent pytest runs from polluting production logs/app.log."""
    logger = logging.getLogger("dns_monitor")
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    for h in file_handlers:
        logger.removeHandler(h)
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for h in file_handlers:
            logger.addHandler(h)
