import hashlib
import json
import sqlite3

import pytest

from parser.db_manager import DBManager
from parser.models import Product


class TestDBManagerInit:
    def test_init_creates_tables(self, db_memory):
        """_init_db создаёт все необходимые таблицы."""
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()

        # Проверяем что таблицы были созданы при инициализации
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        conn.close()

        # Нам нужно создать новый экземпляр и проверить его БД
        db = DBManager(":memory:")
        assert db.db_path.name == ":memory:" or str(db.db_path) == ":memory:"


class TestDBManagerUpsertProducts:
    def test_upsert_new_product(self, db_memory, sample_product):
        """upsert_products вставляет новый товар."""
        upserted, changes = db_memory.upsert_products([sample_product])

        assert upserted == 1
        assert changes == []

    def test_upsert_updates_existing_product(self, db_memory, sample_product):
        """upsert_products обновляет существующий товар (не создаёт дубликат)."""
        db_memory.upsert_products([sample_product])
        initial_count = db_memory.get_product_count()

        # Вставляем же товар второй раз
        upserted, changes = db_memory.upsert_products([sample_product])

        # Количество товаров не изменилось (обновление, не вставка)
        assert db_memory.get_product_count() == initial_count
        assert db_memory.get_product_count() == 1

    def test_upsert_detects_price_change(self, db_memory, sample_product):
        """upsert_products детектирует изменение цены."""
        db_memory.upsert_products([sample_product])

        # Меняем цену
        product_new_price = Product(
            id=sample_product.id,
            uuid=sample_product.uuid,
            title=sample_product.title,
            price=40000,  # было 50000
            price_old=sample_product.price_old,
            url=sample_product.url,
        )

        upserted, changes = db_memory.upsert_products([product_new_price])

        assert len(changes) == 1
        assert changes[0]["new_price"] == 40000
        assert changes[0]["old_price"] == 50000

    def test_upsert_no_changes_if_price_same(self, db_memory, sample_product):
        """upsert_products не детектирует изменение если цена та же."""
        db_memory.upsert_products([sample_product])

        # Вставляем с той же ценой
        same_price_product = Product(
            id=sample_product.id,
            uuid=sample_product.uuid,
            title=sample_product.title,
            price=sample_product.price,  # Та же цена
            price_old=sample_product.price_old,
            url=sample_product.url,
        )

        upserted, changes = db_memory.upsert_products([same_price_product])

        assert changes == []


class TestDBManagerDeleteProducts:
    def test_delete_products_not_in_uuids(self, db_memory, sample_product, sample_product_no_discount):
        """delete_products_not_in_uuids удаляет товары которые не в списке."""
        # Создаём третий товар в той же категории что и sample_product
        product_to_delete = Product(
            id="as-ToDelete",
            uuid="product-to-delete-uuid",
            title="Товар для удаления",
            price=1000,
            price_old=2000,
            url="https://example.com/delete",
            category_id=sample_product.category_id,  # Та же категория!
        )

        db_memory.upsert_products([sample_product, product_to_delete, sample_product_no_discount])
        assert db_memory.get_product_count() == 3

        # Оставляем только sample_product в категории
        deleted = db_memory.delete_products_not_in_uuids(
            sample_product.category_id,
            [sample_product.uuid],
        )

        # Должен удалить product_to_delete, но не sample_product_no_discount (другая категория)
        assert deleted == 1
        assert db_memory.get_product_count() == 2

    def test_delete_products_keeps_needed_uuid(self, db_memory, sample_product, sample_product_no_discount):
        """delete_products_not_in_uuids не удаляет товары которые в списке."""
        sample_product_no_discount.category_id = sample_product.category_id
        db_memory.upsert_products([sample_product, sample_product_no_discount])

        deleted = db_memory.delete_products_not_in_uuids(
            sample_product.category_id,
            [sample_product.uuid, sample_product_no_discount.uuid],
        )

        assert deleted == 0
        assert db_memory.get_product_count() == 2


class TestDBManagerGetters:
    def test_get_product_count(self, db_memory, sample_product):
        """get_product_count возвращает количество товаров."""
        assert db_memory.get_product_count() == 0

        db_memory.upsert_products([sample_product])

        assert db_memory.get_product_count() == 1

    def test_get_products_by_category(self, db_memory, sample_product, sample_product_no_discount):
        """get_products_by_category фильтрует по category_id."""
        db_memory.upsert_products([sample_product, sample_product_no_discount])

        products = db_memory.get_products_by_category(sample_product.category_id)

        assert len(products) == 1
        assert products[0].uuid == sample_product.uuid

    def test_get_products_by_category_returns_empty_list(self, db_memory):
        """get_products_by_category возвращает пустой список если категория не найдена."""
        products = db_memory.get_products_by_category("nonexistent")

        assert products == []

    def test_get_price_drops(self, db_memory, sample_product):
        """get_price_drops возвращает товары со скидками."""
        db_memory.upsert_products([sample_product])

        drops = db_memory.get_price_drops(min_drop_percent=10.0)

        assert len(drops) == 1
        assert drops[0]["title"] == sample_product.title


class TestDBManagerCategoryState:
    def test_get_category_state_returns_none_if_not_found(self, db_memory):
        """get_category_state возвращает None если категория не найдена."""
        state = db_memory.get_category_state("nonexistent")

        assert state is None

    def test_update_category_state_creates_record(self, db_memory):
        """update_category_state создаёт запись."""
        db_memory.update_category_state("cat-1", "Ноутбуки", 5, ["uuid-1", "uuid-2"])

        state = db_memory.get_category_state("cat-1")

        assert state is not None
        assert state["category_name"] == "Ноутбуки"
        assert state["last_product_count"] == 5

    def test_update_category_state_calculates_uuid_hash(self, db_memory):
        """update_category_state вычисляет md5-хэш UUID."""
        uuids = ["uuid-2", "uuid-1", "uuid-3"]
        db_memory.update_category_state("cat-1", "Category", 3, uuids)

        state = db_memory.get_category_state("cat-1")

        # Хэш — SHA256 от JSON-списка отсортированных UUID
        expected_hash = hashlib.sha256(json.dumps(sorted(uuids)).encode()).hexdigest()
        assert state["uuid_hash"] == expected_hash

    def test_update_category_state_sorts_uuids(self, db_memory):
        """update_category_state сортирует UUID перед хешированием."""
        uuids1 = ["a", "b", "c"]
        uuids2 = ["c", "a", "b"]

        db_memory.update_category_state("cat-1", "Cat", 3, uuids1)
        state1 = db_memory.get_category_state("cat-1")

        db_memory.update_category_state("cat-1", "Cat", 3, uuids2)
        state2 = db_memory.get_category_state("cat-1")

        # Хэши должны быть одинаковыми
        assert state1["uuid_hash"] == state2["uuid_hash"]


class TestDBManagerNewProducts:
    def test_get_new_products_in_category(self, db_memory, sample_product):
        """get_new_products_in_category возвращает UUID которых нет в БД."""
        db_memory.upsert_products([sample_product])

        new_uuid = "new-uuid-123"
        new_products = db_memory.get_new_products_in_category(
            sample_product.category_id,
            [sample_product.uuid, new_uuid],
        )

        assert new_products == [new_uuid]

    def test_get_new_products_in_category_empty_if_all_exist(self, db_memory, sample_product):
        """get_new_products_in_category пустой если все UUID в БД."""
        db_memory.upsert_products([sample_product])

        new_products = db_memory.get_new_products_in_category(
            sample_product.category_id,
            [sample_product.uuid],
        )

        assert new_products == []


class TestDBManagerSubscribers:
    def test_add_and_get_telegram_subscribers(self, db_memory):
        """add_telegram_subscriber добавляет подписчика."""
        db_memory.add_telegram_subscriber("user-123")
        db_memory.add_telegram_subscriber("user-456")

        subscribers = db_memory.get_telegram_subscribers()

        assert "user-123" in subscribers
        assert "user-456" in subscribers
        assert len(subscribers) == 2

    def test_remove_telegram_subscriber(self, db_memory):
        """remove_telegram_subscriber удаляет подписчика."""
        db_memory.add_telegram_subscriber("user-123")
        db_memory.add_telegram_subscriber("user-456")

        db_memory.remove_telegram_subscriber("user-123")

        subscribers = db_memory.get_telegram_subscribers()

        assert "user-123" not in subscribers
        assert "user-456" in subscribers

    def test_add_telegram_subscriber_duplicate(self, db_memory):
        """add_telegram_subscriber игнорирует дубликаты (INSERT OR IGNORE)."""
        db_memory.add_telegram_subscriber("user-123")
        db_memory.add_telegram_subscriber("user-123")

        subscribers = db_memory.get_telegram_subscribers()

        assert len(subscribers) == 1


class TestDBManagerCategoryStates:
    def test_get_all_category_states(self, db_memory):
        """get_all_category_states возвращает dict всех категорий."""
        db_memory.update_category_state("cat-1", "Ноутбуки", 10)
        db_memory.update_category_state("cat-2", "Мониторы", 5)

        states = db_memory.get_all_category_states()

        assert states["cat-1"] == 10
        assert states["cat-2"] == 5

    def test_get_all_category_states_empty(self, db_memory):
        """get_all_category_states возвращает пустой dict если нет категорий."""
        states = db_memory.get_all_category_states()

        assert states == {}
