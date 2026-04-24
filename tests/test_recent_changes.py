"""
Тесты для изменений:
- telegram_subscribers: новые поля, soft-delete, реактивация, subscribed_at не перезаписывается
- user_categories: хранение category_name при toggle и set
"""
import sqlite3
import pytest
from parser.db_manager import DBManager


# ─── Subscribers ──────────────────────────────────────────────────────────────

class TestSubscriberColumns:
    def test_table_has_new_columns(self, db_memory):
        """telegram_subscribers содержит все новые колонки."""
        with sqlite3.connect(db_memory.db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(telegram_subscribers)")
            cols = {row[1] for row in cursor.fetchall()}
        expected = {"user_id", "first_name", "last_name", "username",
                    "language_code", "is_active", "subscribed_at", "updated_at"}
        assert expected == cols

    def test_add_subscriber_stores_user_info(self, db_memory):
        """add_telegram_subscriber сохраняет first_name, username и т.д."""
        db_memory.add_telegram_subscriber(
            "111", first_name="Иван", last_name="Петров",
            username="ivan_p", language_code="ru",
        )
        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT first_name, last_name, username, language_code, is_active "
                "FROM telegram_subscribers WHERE user_id = '111'"
            ).fetchone()
        assert row == ("Иван", "Петров", "ivan_p", "ru", 1)

    def test_subscribed_at_not_overwritten_on_restart(self, db_memory):
        """subscribed_at пишется только при первой подписке."""
        db_memory.add_telegram_subscriber("222", first_name="A")
        with sqlite3.connect(db_memory.db_path) as conn:
            ts1 = conn.execute(
                "SELECT subscribed_at FROM telegram_subscribers WHERE user_id = '222'"
            ).fetchone()[0]

        # Повторный /start (реактивация после /stop)
        db_memory.remove_telegram_subscriber("222")
        db_memory.add_telegram_subscriber("222", first_name="B")

        with sqlite3.connect(db_memory.db_path) as conn:
            ts2 = conn.execute(
                "SELECT subscribed_at FROM telegram_subscribers WHERE user_id = '222'"
            ).fetchone()[0]

        assert ts1 == ts2

    def test_remove_sets_inactive_not_deletes(self, db_memory):
        """/stop помечает is_active=0, строка остаётся в БД."""
        db_memory.add_telegram_subscriber("333")
        db_memory.remove_telegram_subscriber("333")

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT is_active FROM telegram_subscribers WHERE user_id = '333'"
            ).fetchone()
        assert row is not None
        assert row[0] == 0

    def test_reactivate_on_second_start(self, db_memory):
        """После /stop повторный /start реактивирует подписчика."""
        db_memory.add_telegram_subscriber("444")
        db_memory.remove_telegram_subscriber("444")
        db_memory.add_telegram_subscriber("444", first_name="Новое имя")

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT is_active, first_name FROM telegram_subscribers WHERE user_id = '444'"
            ).fetchone()
        assert row[0] == 1
        assert row[1] == "Новое имя"

    def test_get_subscribers_returns_only_active(self, db_memory):
        """get_telegram_subscribers возвращает только активных."""
        db_memory.add_telegram_subscriber("1")
        db_memory.add_telegram_subscriber("2")
        db_memory.add_telegram_subscriber("3")
        db_memory.remove_telegram_subscriber("2")

        result = db_memory.get_telegram_subscribers()
        assert set(result) == {"1", "3"}
        assert "2" not in result

    def test_count_subscribers_counts_only_active(self, db_memory):
        """count_telegram_subscribers считает только активных."""
        db_memory.add_telegram_subscriber("1")
        db_memory.add_telegram_subscriber("2")
        db_memory.remove_telegram_subscriber("1")

        assert db_memory.count_telegram_subscribers() == 1

    def test_pagination_skips_inactive(self, db_memory):
        """Пагинация get_telegram_subscribers не включает неактивных."""
        for i in range(5):
            db_memory.add_telegram_subscriber(str(i))
        db_memory.remove_telegram_subscriber("2")
        db_memory.remove_telegram_subscriber("4")

        page1 = db_memory.get_telegram_subscribers(limit=10, offset=0)
        assert set(page1) == {"0", "1", "3"}


# ─── UserCategories.category_name ─────────────────────────────────────────────

class TestUserCategoryCategoryName:
    def _seed_category(self, db, cat_id, cat_name):
        """Добавляет категорию в category_state (как это делает парсер)."""
        db.update_category_state(cat_id, cat_name, product_count=1)

    def test_toggle_stores_category_name(self, db_memory):
        """toggle_user_category сохраняет название категории из category_state."""
        self._seed_category(db_memory, "cat-1", "Ноутбуки")
        db_memory.toggle_user_category("user1", "cat-1")

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT category_name FROM user_categories WHERE user_id='user1' AND category_id='cat-1'"
            ).fetchone()
        assert row is not None
        assert row[0] == "Ноутбуки"

    def test_set_user_categories_stores_names(self, db_memory):
        """set_user_categories сохраняет названия всех переданных категорий."""
        self._seed_category(db_memory, "cat-1", "Ноутбуки")
        self._seed_category(db_memory, "cat-2", "Смартфоны")

        db_memory.set_user_categories("user1", ["cat-1", "cat-2"])

        with sqlite3.connect(db_memory.db_path) as conn:
            rows = conn.execute(
                "SELECT category_id, category_name FROM user_categories WHERE user_id='user1'"
            ).fetchall()
        result = {r[0]: r[1] for r in rows}
        assert result == {"cat-1": "Ноутбуки", "cat-2": "Смартфоны"}

    def test_toggle_remove_then_add_keeps_name(self, db_memory):
        """После снятия и повторного добавления категория сохраняет имя."""
        self._seed_category(db_memory, "cat-1", "Ноутбуки")
        db_memory.toggle_user_category("user1", "cat-1")  # добавить
        db_memory.toggle_user_category("user1", "cat-1")  # убрать
        db_memory.toggle_user_category("user1", "cat-1")  # добавить снова

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT category_name FROM user_categories WHERE user_id='user1' AND category_id='cat-1'"
            ).fetchone()
        assert row[0] == "Ноутбуки"

    def test_set_empty_clears_categories(self, db_memory):
        """set_user_categories([]) очищает категории пользователя."""
        self._seed_category(db_memory, "cat-1", "Ноутбуки")
        db_memory.set_user_categories("user1", ["cat-1"])
        db_memory.set_user_categories("user1", [])

        with sqlite3.connect(db_memory.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM user_categories WHERE user_id='user1'"
            ).fetchall()
        assert rows == []

    def test_user_categories_table_has_category_name_column(self, db_memory):
        """Таблица user_categories содержит колонку category_name."""
        with sqlite3.connect(db_memory.db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(user_categories)")
            cols = {row[1] for row in cursor.fetchall()}
        assert "category_name" in cols
