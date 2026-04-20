"""Тесты на восстановление после сбоя парсинга."""

import pytest

from parser.db_manager import DBManager
from parser.models import Product


class TestRecoveryAfterFailure:
    """Проверяет что система восстанавливается при сбое парсинга."""

    def test_recovery_after_empty_products_failure(self, db_memory):
        """
        Сценарий: свет выключили во время парсинга.
        1. Цикл 1: спарсили A, B, D (товар C продан)
        2. Уpsert выполнился ✅
        3. Delete не выполнился ❌ (свет выключился)
        4. В БД: A, B, C (лишний), D

        5. Цикл 2: спарсили снова A, B, D
        6. Уpsert выполнился ✅
        7. Delete выполнился ✅ (удалил C)
        8. В БД: A, B, D (синхронно) ✅
        """
        category_id = "cat-1"

        # ЦИКЛ 1: Вставляем товары A, B, C, D
        products_cycle1 = [
            Product(
                id="as-A", uuid="uuid-A", title="Товар A",
                price=100, price_old=100, url="http://A", category_id=category_id
            ),
            Product(
                id="as-B", uuid="uuid-B", title="Товар B",
                price=200, price_old=200, url="http://B", category_id=category_id
            ),
            Product(
                id="as-C", uuid="uuid-C", title="Товар C (продан)",
                price=300, price_old=300, url="http://C", category_id=category_id
            ),
        ]
        db_memory.upsert_products(products_cycle1)
        assert db_memory.get_product_count() == 3

        # ЦИКЛ 2: Сайт вернул A, B, D (C продан, D добавлен)
        # Но свет выключился ДО delete
        uuids_cycle2 = ["uuid-A", "uuid-B", "uuid-D"]
        products_cycle2 = [
            Product(
                id="as-A", uuid="uuid-A", title="Товар A",
                price=100, price_old=100, url="http://A", category_id=category_id
            ),
            Product(
                id="as-B", uuid="uuid-B", title="Товар B",
                price=200, price_old=200, url="http://B", category_id=category_id
            ),
            Product(
                id="as-D", uuid="uuid-D", title="Товар D (новый)",
                price=400, price_old=400, url="http://D", category_id=category_id
            ),
        ]

        # upsert выполнился
        db_memory.upsert_products(products_cycle2)
        assert db_memory.get_product_count() == 4  # A, B, C (лишний), D

        # swet выключился, delete не выполнился
        # (симулируем что delete не вызовется)
        assert db_memory.get_product_count() == 4

        # ЦИКЛ 3: Свет вернулся, запустили парсер снова
        # Сайт снова вернул A, B, D
        db_memory.upsert_products(products_cycle2)

        # Теперь delete выполнится ✅
        deleted = db_memory.delete_products_not_in_uuids(category_id, uuids_cycle2)

        # Удалён лишний товар C
        assert deleted == 1
        assert db_memory.get_product_count() == 3

        # Синхронно с сайтом ✅
        products_in_db = db_memory.get_products_by_category(category_id)
        uuids_in_db = {p.uuid for p in products_in_db}
        assert uuids_in_db == {"uuid-A", "uuid-B", "uuid-D"}

    def test_protection_from_zero_products_failure(self, db_memory):
        """
        Сценарий: fetch_products_details вернул пустой список.
        Защита: delete_products_not_in_uuids не удаляет при пустом списке.

        Это важно потому что:
        - Если сбой парсинга (сет выключился) → не захотим удалить ВСЕ товары
        - При следующем цикле товары синхронизируются
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

        # fetch_products_details вернул ошибку: products = []
        # (или свет выключился при fetch_products_details)
        uuids_empty = []

        # ЗАЩИТА: delete с пустым списком НЕ удаляет
        deleted = db_memory.delete_products_not_in_uuids(category_id, uuids_empty)
        assert deleted == 0

        # Товары остаются в БД ✅ (безопасная защита)
        assert db_memory.get_product_count() == 5

        print("✅ ЗАЩИТА: товары НЕ удалены при сбое парсинга (пустой список)")

    def test_idempotent_recovery_two_failures_in_row(self, db_memory):
        """
        Сценарий: два сбоя парсинга подряд.
        Система должна восстановиться при третьем цикле.
        """
        category_id = "cat-1"

        # Исходное состояние: товары A, B, C
        products_initial = [
            Product(
                id=f"as-{c}", uuid=f"uuid-{c}", title=f"Товар {c}",
                price=100, price_old=100, url=f"http://{c}", category_id=category_id
            )
            for c in ["A", "B", "C"]
        ]
        db_memory.upsert_products(products_initial)
        assert db_memory.get_product_count() == 3

        # ЦИКЛ 1 СБОЙ: вернулось A, B, D (C продан, D добавлен)
        # Но свет выключился ДО delete
        upsert1 = [
            Product(
                id=f"as-{c}", uuid=f"uuid-{c}", title=f"Товар {c}",
                price=100, price_old=100, url=f"http://{c}", category_id=category_id
            )
            for c in ["A", "B", "D"]
        ]
        db_memory.upsert_products(upsert1)
        # delete не выполнился (пропускаем)
        assert db_memory.get_product_count() == 4  # A, B, C, D (лишний C)

        # ЦИКЛ 2 СБОЙ: вернулось 0 товаров (fetch упал)
        # delete также не выполнится (защита)
        deleted = db_memory.delete_products_not_in_uuids(category_id, [])
        assert deleted == 0
        assert db_memory.get_product_count() == 4  # Всё ещё A, B, C, D

        # ЦИКЛ 3 УСПЕХ: вернулось A, B, D снова
        db_memory.upsert_products(upsert1)
        # Теперь delete выполнится ✅
        deleted = db_memory.delete_products_not_in_uuids(category_id, ["uuid-A", "uuid-B", "uuid-D"])
        assert deleted == 1  # Удалён лишний C
        assert db_memory.get_product_count() == 3

        print("✅ ИДЕМПОТЕНТНОСТЬ: система восстановилась после двух сбоев")

    def test_category_state_tracks_sync_progress(self, db_memory):
        """
        category_state хранит хэш UUID для отслеживания синхронизации.
        Это помогает определить было ли изменение состава товаров.
        """
        category_id = "cat-1"

        # Первый цикл: товары A, B, C
        uuids1 = ["uuid-A", "uuid-B", "uuid-C"]
        db_memory.update_category_state(category_id, "Категория", 3, uuids1)

        state1 = db_memory.get_category_state(category_id)
        assert state1["uuid_hash"] is not None

        # Второй цикл: ТЕ ЖЕ товары (без изменений)
        uuids2 = ["uuid-A", "uuid-B", "uuid-C"]
        db_memory.update_category_state(category_id, "Категория", 3, uuids2)

        state2 = db_memory.get_category_state(category_id)
        # Хэш должен быть одинаковым (порядок сортируется)
        assert state1["uuid_hash"] == state2["uuid_hash"]

        # Третий цикл: ИЗМЕНИЛСЯ состав (C удалён, D добавлен)
        uuids3 = ["uuid-A", "uuid-B", "uuid-D"]
        db_memory.update_category_state(category_id, "Категория", 3, uuids3)

        state3 = db_memory.get_category_state(category_id)
        # Хэш должен быть ДРУГОЙ (состав изменился)
        assert state1["uuid_hash"] != state3["uuid_hash"]

        print("✅ ОТСЛЕЖИВАНИЕ: category_state помогает определить синхронизацию")
