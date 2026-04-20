"""Тест для проверки проблемы: категория не обновилась → товары остаются в БД."""

import pytest

from parser.db_manager import DBManager
from parser.models import Product


class TestCategoryUpdateIssue:
    """Проверяет проблему когда категория не обновляется на сайте."""

    def test_category_not_updated_old_products_remain(self, db_memory):
        """
        ПРОБЛЕМА: если категория не обновилась (вернула 0 товаров),
        старые товары остаются в БД.
        """
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

        # Цикл 2: сайт НИЧЕГО не вернул (0 товаров, сбой парсинга или сайт обновился)
        # В коде: if products: ... else: ... ничего не удаляется!
        # Нужно явно вызвать delete_products_not_in_uuids с пустым списком

        uuids_cycle2 = []

        # Если товаров 0, delete вернёт 0 (защита)
        deleted = db_memory.delete_products_not_in_uuids(category_id, uuids_cycle2)
        assert deleted == 0

        # ПРОБЛЕМА: товары всё ещё в БД!
        assert db_memory.get_product_count() == 5

        print(f"❌ ПРОБЛЕМА: получено 0 товаров, но в БД осталось {db_memory.get_product_count()}")

    def test_partial_category_update_orphaned_products(self, db_memory):
        """
        Если категория вернула только часть товаров,
        остальные должны быть удалены.
        """
        category_id = "cat-1"

        # Цикл 1: 10 товаров
        products_cycle1 = [
            Product(
                id=f"as-{i}", uuid=f"uuid-{i}", title=f"Товар {i}",
                price=i*100, price_old=i*100, url=f"http://{i}", category_id=category_id
            )
            for i in range(1, 11)
        ]
        db_memory.upsert_products(products_cycle1)
        assert db_memory.get_product_count() == 10

        # Цикл 2: вернул только товары 1-3 (потеряны 4-10)
        uuids_cycle2 = ["uuid-1", "uuid-2", "uuid-3"]
        products_cycle2 = [
            Product(
                id=f"as-{i}", uuid=f"uuid-{i}", title=f"Товар {i}",
                price=i*100, price_old=i*100, url=f"http://{i}", category_id=category_id
            )
            for i in range(1, 4)
        ]

        db_memory.upsert_products(products_cycle2)

        # Удаляем товары которых нет в текущем списке
        deleted = db_memory.delete_products_not_in_uuids(category_id, uuids_cycle2)

        # Должны удалить 7 товаров (4-10)
        assert deleted == 7
        assert db_memory.get_product_count() == 3

    def test_fetch_products_returns_none_orphaned_products(self, db_memory):
        """
        КРИТИЧЕСКАЯ ОШИБКА: если fetch_products_details вернул None или пустой список,
        delete_products_not_in_uuids никогда не вызовется!
        """
        category_id = "cat-1"

        # Вставляем товары
        products = [
            Product(
                id=f"as-{i}", uuid=f"uuid-{i}", title=f"Товар {i}",
                price=i*100, price_old=i*100, url=f"http://{i}", category_id=category_id
            )
            for i in range(1, 6)
        ]
        db_memory.upsert_products(products)
        assert db_memory.get_product_count() == 5

        # КРИТИЧЕСКАЯ ОШИБКА В КОДЕ:
        # if products:
        #     saved, price_changes = db_memory.upsert_products(products)
        #     deleted = db_memory.delete_products_not_in_uuids(cat.id, uuids)
        # else:
        #     # ничего не удаляется!
        #
        # Если fetch_products_details вернул пустой список,
        # старые товары никогда не удалятся!

        # Симулируем fetch_products_details вернул []
        products_empty = []
        uuids_empty = []

        # В коде: if products: не выполнится, delete не вызовется
        if products_empty:
            db_memory.upsert_products(products_empty)
            db_memory.delete_products_not_in_uuids(category_id, uuids_empty)

        # Товары остаются в БД!
        assert db_memory.get_product_count() == 5
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: вернулось 0 товаров, но {db_memory.get_product_count()} в БД")

    def test_fix_always_call_delete_products(self, db_memory):
        """
        РЕШЕНИЕ: всегда вызывать delete_products_not_in_uuids.
        delete_products_not_in_uuids имеет защиту от пустого списка.
        """
        category_id = "cat-1"

        # Вставляем товары
        products_cycle1 = [
            Product(
                id=f"as-{i}", uuid=f"uuid-{i}", title=f"Товар {i}",
                price=i*100, price_old=i*100, url=f"http://{i}", category_id=category_id
            )
            for i in range(1, 6)
        ]
        db_memory.upsert_products(products_cycle1)
        assert db_memory.get_product_count() == 5

        # Защита: если текущий список пуст, вернёт 0 (не удаляет)
        # Это нужно чтобы защитить от случайного удаления при сбое парсинга
        uuids_cycle2 = []  # Получены 0 товаров

        deleted = db_memory.delete_products_not_in_uuids(category_id, uuids_cycle2)
        assert deleted == 0  # Защита срабатывает
        assert db_memory.get_product_count() == 5  # Товары не удалены

        print("✅ delete_products_not_in_uuids имеет защиту от пустого списка")
