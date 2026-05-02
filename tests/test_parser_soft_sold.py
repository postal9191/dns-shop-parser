"""Tests for parser soft-sold safeguards and disappeared-category handling."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parser.models import Category, Product


def _load_parser_entrypoint():
    module_path = Path(__file__).resolve().parents[1] / "parser.py"
    spec = importlib.util.spec_from_file_location("parser_entrypoint", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeParser:
    def __init__(self, *, uuids_new=None, uuids_used=None, products=None, categories=None):
        self.uuids_new = uuids_new or []
        self.uuids_used = uuids_used or []
        self.products = products or []
        self.categories = categories or []

    async def fetch_product_uuids(self, category_id: str, status: int = None):
        if status == 0:
            return list(self.uuids_new)
        if status == 1:
            return list(self.uuids_used)
        return []

    async def fetch_products_details(self, uuids, category_id, category_name, uuid_to_status=None):
        return list(self.products)

    async def fetch_categories(self):
        return list(self.categories)


class RecordingDB:
    def __init__(self):
        self.category_state = None
        self.new_products = []
        self.updated_state = []
        self.soft_marked_products = []
        self.soft_marked_categories = []
        self.upserted_products = []
        self.category_states = {}
        self.product_count = 0

    def get_category_state(self, category_id, city_slug):
        return self.category_state

    def get_new_products_in_category(self, category_id, uuids, city_slug):
        return list(self.new_products)

    def update_category_state(self, category_id, label, count, city_slug, uuids=None):
        self.updated_state.append((category_id, label, count, city_slug, list(uuids or [])))

    def upsert_products(self, products):
        self.upserted_products.extend(products)
        return len(products), []

    def delete_products_not_in_uuids(self, category_id, uuids, city_slug):
        self.soft_marked_products.append((category_id, list(uuids), city_slug))
        return 0

    def get_product_count(self):
        return self.product_count

    def get_all_category_states(self, city_slug):
        return dict(self.category_states)

    def delete_all_products_in_category(self, category_id, city_slug):
        self.soft_marked_categories.append((category_id, city_slug))
        return 1


def _monitor(fake_parser, fake_db):
    parser_entrypoint = _load_parser_entrypoint()
    monitor = object.__new__(parser_entrypoint.DNSMonitorBrowserless)
    monitor.city_slug = "moscow"
    monitor.parser = fake_parser
    monitor.db = fake_db
    monitor.tg = SimpleNamespace(send_digest=AsyncMock(), send_admin_alert=AsyncMock())
    monitor.parse_interval = 3600
    return monitor


@pytest.mark.asyncio
async def test_process_category_skips_soft_mark_when_details_missing():
    """UUID без деталей не должны обновлять state и помечать товары купленными."""
    fake_db = RecordingDB()
    fake_db.new_products = ["uuid-1"]
    monitor = _monitor(
        FakeParser(uuids_new=["uuid-1"], products=[]),
        fake_db,
    )
    cat = Category(id="cat-1", label="Категория", count=1)

    result = await monitor._process_category(cat, 1, 1, False, [], [])

    assert result == (0, 0)
    assert fake_db.upserted_products == []
    assert fake_db.soft_marked_products == []
    assert fake_db.updated_state == []


@pytest.mark.asyncio
async def test_process_category_skips_state_when_expected_uuids_missing():
    """Если category count > 0, пустой UUID считается сомнительным fetch."""
    fake_db = RecordingDB()
    monitor = _monitor(FakeParser(uuids_new=[], uuids_used=[]), fake_db)
    cat = Category(id="cat-1", label="Категория", count=3)

    result = await monitor._process_category(cat, 1, 1, False, [], [])

    assert result == (0, 0)
    assert fake_db.soft_marked_products == []
    assert fake_db.updated_state == []


@pytest.mark.asyncio
async def test_process_category_allows_empty_zero_count_category_state():
    """Категория с count=0 остается мягким пустым состоянием."""
    fake_db = RecordingDB()
    monitor = _monitor(FakeParser(uuids_new=[], uuids_used=[]), fake_db)
    cat = Category(id="cat-empty", label="Пустая", count=0)

    result = await monitor._process_category(cat, 1, 1, False, [], [])

    assert result == (0, 0)
    assert fake_db.soft_marked_products == []
    assert fake_db.updated_state == [("cat-empty", "Пустая", 0, "moscow", [])]


@pytest.mark.asyncio
async def test_parse_all_soft_marks_only_disappeared_active_categories():
    """Категории, исчезнувшие из fetch_categories, уходят в soft-sold."""
    fake_db = RecordingDB()
    fake_db.category_states = {"cat-active": 1, "cat-gone": 1}
    fake_parser = FakeParser(categories=[Category(id="cat-active", label="Активная", count=1)])
    monitor = _monitor(fake_parser, fake_db)
    monitor._process_category = AsyncMock(return_value=(0, 0))

    await monitor.parse_all()

    monitor._process_category.assert_awaited_once()
    assert fake_db.soft_marked_categories == [("cat-gone", "moscow")]
    monitor.tg.send_digest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_category_reactivates_sold_product_through_upsert():
    """Вернувшийся товар проходит через upsert, где DB снимает is_sold."""
    product = Product(
        id="as-1",
        uuid="uuid-1",
        title="Товар",
        price=100,
        price_old=200,
        url="http://example.test",
        category_id="cat-1",
        category_name="Категория",
        status="Новый",
        city_slug="moscow",
    )
    fake_db = RecordingDB()
    fake_db.category_state = {"last_product_count": 0, "uuid_hash": "old"}
    fake_db.new_products = ["uuid-1"]
    monitor = _monitor(FakeParser(uuids_new=["uuid-1"], products=[product]), fake_db)
    cat = Category(id="cat-1", label="Категория", count=1)

    result = await monitor._process_category(cat, 1, 1, False, [], [])

    assert result == (1, 1)
    assert fake_db.upserted_products == [product]
    assert fake_db.soft_marked_products == [("cat-1", ["uuid-1"], "moscow")]
    assert fake_db.updated_state == [("cat-1", "Категория", 1, "moscow", ["uuid-1"])]
