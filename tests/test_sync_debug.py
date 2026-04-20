"""Тесты для отладки синхронизации товаров между сайтом и БД."""

import pytest

from parser.db_manager import DBManager
from parser.models import Product


class TestSyncDebug:
    """Проверяет что после полного цикла парсинга товаров в БД ровно столько сколько спарсили."""

    def test_full_sync_new_products(self, db_memory):
        """Полная синхронизация: новые товары должны появиться в БД."""
        category_id = "cat-1"

        # Симулируем первый цикл парсинга — 3 товара
        products_cycle1 = [
            Product(
                id="as-1", uuid="uuid-1", title="Товар 1",
                price=100, price_old=100, url="http://1", category_id=category_id
            ),
            Product(
                id="as-2", uuid="uuid-2", title="Товар 2",
                price=200, price_old=200, url="http://2", category_id=category_id
            ),
            Product(
                id="as-3", uuid="uuid-3", title="Товар 3",
                price=300, price_old=300, url="http://3", category_id=category_id
            ),
        ]

        # Вставляем товары
        upserted, _ = db_memory.upsert_products(products_cycle1)
        assert upserted == 3

        # Проверяем что в БД 3 товара
        assert db_memory.get_product_count() == 3

        # Удаляем товары которые больше не на сайте (пусть остались только uuid-1 и uuid-2)
        deleted = db_memory.delete_products_not_in_uuids(
            category_id,
            ["uuid-1", "uuid-2"],
        )

        # Должен удалить 1 товар (uuid-3)
        assert deleted == 1
        assert db_memory.get_product_count() == 2

    def test_full_sync_with_new_and_deleted(self, db_memory):
        """После полного цикла: новые добавлены, старые удалены."""
        category_id = "cat-1"

        # Цикл 1: вставляем 5 товаров
        products_cycle1 = [
            Product(
                id=f"as-{i}", uuid=f"uuid-{i}", title=f"Товар {i}",
                price=i*100, price_old=i*100, url=f"http://{i}", category_id=category_id
            )
            for i in range(1, 6)
        ]

        db_memory.upsert_products(products_cycle1)
        assert db_memory.get_product_count() == 5

        # Цикл 2: сайт вернул товары 2,3,4,6,7 (удалены 1,5, добавлены 6,7)
        uuids_cycle2 = ["uuid-2", "uuid-3", "uuid-4", "uuid-6", "uuid-7"]
        products_cycle2 = [
            Product(
                id="as-2", uuid="uuid-2", title="Товар 2 (обновлено)",
                price=200, price_old=150, url="http://2", category_id=category_id
            ),
            Product(
                id="as-3", uuid="uuid-3", title="Товар 3",
                price=300, price_old=300, url="http://3", category_id=category_id
            ),
            Product(
                id="as-4", uuid="uuid-4", title="Товар 4",
                price=400, price_old=400, url="http://4", category_id=category_id
            ),
            Product(
                id="as-6", uuid="uuid-6", title="Товар 6 (новый)",
                price=600, price_old=600, url="http://6", category_id=category_id
            ),
            Product(
                id="as-7", uuid="uuid-7", title="Товар 7 (новый)",
                price=700, price_old=700, url="http://7", category_id=category_id
            ),
        ]

        # Вставляем/обновляем товары из цикла 2
        db_memory.upsert_products(products_cycle2)

        # Удаляем товары которые больше не на сайте
        deleted = db_memory.delete_products_not_in_uuids(category_id, uuids_cycle2)

        # Должны быть удалены uuid-1 и uuid-5 (2 товара)
        assert deleted == 2

        # В БД должны быть только товары из цикла 2 (5 товаров)
        assert db_memory.get_product_count() == 5

        # Проверяем что правильные товары в БД
        products_in_db = db_memory.get_products_by_category(category_id)
        uuids_in_db = {p.uuid for p in products_in_db}
        assert uuids_in_db == set(uuids_cycle2)

    def test_delete_products_not_in_uuids_empty_list(self, db_memory):
        """Если передать пустой список UUID, ничего не удалится (защита от ошибок)."""
        category_id = "cat-1"

        # Вставляем товары
        products = [
            Product(
                id="as-1", uuid="uuid-1", title="Товар",
                price=100, price_old=100, url="http://1", category_id=category_id
            ),
        ]
        db_memory.upsert_products(products)

        # Пытаемся "удалить" с пустым списком
        deleted = db_memory.delete_products_not_in_uuids(category_id, [])

        # Должны вернуть 0 (защита)
        assert deleted == 0
        assert db_memory.get_product_count() == 1

    def test_multiple_categories_sync(self, db_memory):
        """Товары из разных категорий не должны конфликтовать при синхронизации."""
        cat1, cat2 = "cat-1", "cat-2"

        # Категория 1: 3 товара
        products_cat1 = [
            Product(
                id=f"as-cat1-{i}", uuid=f"uuid-cat1-{i}", title=f"Товар кат1 {i}",
                price=i*100, price_old=i*100, url=f"http://cat1/{i}", category_id=cat1
            )
            for i in range(1, 4)
        ]

        # Категория 2: 2 товара
        products_cat2 = [
            Product(
                id=f"as-cat2-{i}", uuid=f"uuid-cat2-{i}", title=f"Товар кат2 {i}",
                price=i*100, price_old=i*100, url=f"http://cat2/{i}", category_id=cat2
            )
            for i in range(1, 3)
        ]

        db_memory.upsert_products(products_cat1 + products_cat2)
        assert db_memory.get_product_count() == 5

        # Синхронизируем категорию 1: оставляем только первые 2 товара
        deleted_cat1 = db_memory.delete_products_not_in_uuids(
            cat1, ["uuid-cat1-1", "uuid-cat1-2"]
        )
        assert deleted_cat1 == 1  # Удалён uuid-cat1-3

        # Категория 2 должна остаться нетронутой
        assert db_memory.get_product_count() == 4
        products_cat2_check = db_memory.get_products_by_category(cat2)
        assert len(products_cat2_check) == 2  # Оба товара кат2 на месте

        products_cat1_check = db_memory.get_products_by_category(cat1)
        assert len(products_cat1_check) == 2  # Осталось 2 товара кат1
