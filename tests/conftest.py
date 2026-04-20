import sqlite3
import tempfile
from pathlib import Path

import pytest

from parser.db_manager import DBManager
from parser.models import Product


@pytest.fixture
def db_memory():
    """Файловая SQLite база для тестирования (в temp)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        db = DBManager(db_path)
        yield db
        db.close()


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
    )
