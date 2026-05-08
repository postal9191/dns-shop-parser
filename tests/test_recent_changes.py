"""
РўРµСЃС‚С‹ РґР»СЏ РёР·РјРµРЅРµРЅРёР№:
- telegram_subscribers: РЅРѕРІС‹Рµ РїРѕР»СЏ, soft-delete, СЂРµР°РєС‚РёРІР°С†РёСЏ, subscribed_at РЅРµ РїРµСЂРµР·Р°РїРёСЃС‹РІР°РµС‚СЃСЏ
- user_categories: С…СЂР°РЅРµРЅРёРµ category_name РїСЂРё toggle Рё set
"""
import sqlite3
import pytest
from parser.db_manager import DBManager


# в”Ђв”Ђв”Ђ Subscribers в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class TestSubscriberColumns:
    def test_table_has_new_columns(self, db_memory):
        """telegram_subscribers СЃРѕРґРµСЂР¶РёС‚ РІСЃРµ РЅРѕРІС‹Рµ РєРѕР»РѕРЅРєРё."""
        with sqlite3.connect(db_memory.db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(telegram_subscribers)")
            cols = {row[1] for row in cursor.fetchall()}
        expected = {"user_id", "first_name", "last_name", "username",
                    "language_code", "is_active", "subscribed_at", "updated_at"}
        assert expected == cols

    def test_add_subscriber_stores_user_info(self, db_memory):
        """add_telegram_subscriber СЃРѕС…СЂР°РЅСЏРµС‚ first_name, username Рё С‚.Рґ."""
        db_memory.add_telegram_subscriber(
            "111", first_name="РРІР°РЅ", last_name="РџРµС‚СЂРѕРІ",
            username="ivan_p", language_code="ru",
        )
        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT first_name, last_name, username, language_code, is_active "
                "FROM telegram_subscribers WHERE user_id = '111'"
            ).fetchone()
        assert row == ("РРІР°РЅ", "РџРµС‚СЂРѕРІ", "ivan_p", "ru", 1)

    def test_subscribed_at_not_overwritten_on_restart(self, db_memory):
        """subscribed_at РїРёС€РµС‚СЃСЏ С‚РѕР»СЊРєРѕ РїСЂРё РїРµСЂРІРѕР№ РїРѕРґРїРёСЃРєРµ."""
        db_memory.add_telegram_subscriber("222", first_name="A")
        with sqlite3.connect(db_memory.db_path) as conn:
            ts1 = conn.execute(
                "SELECT subscribed_at FROM telegram_subscribers WHERE user_id = '222'"
            ).fetchone()[0]

        # РџРѕРІС‚РѕСЂРЅС‹Р№ /start (СЂРµР°РєС‚РёРІР°С†РёСЏ РїРѕСЃР»Рµ /stop)
        db_memory.remove_telegram_subscriber("222")
        db_memory.add_telegram_subscriber("222", first_name="B")

        with sqlite3.connect(db_memory.db_path) as conn:
            ts2 = conn.execute(
                "SELECT subscribed_at FROM telegram_subscribers WHERE user_id = '222'"
            ).fetchone()[0]

        assert ts1 == ts2

    def test_remove_sets_inactive_not_deletes(self, db_memory):
        """/stop РїРѕРјРµС‡Р°РµС‚ is_active=0, СЃС‚СЂРѕРєР° РѕСЃС‚Р°С‘С‚СЃСЏ РІ Р‘Р”."""
        db_memory.add_telegram_subscriber("333")
        db_memory.remove_telegram_subscriber("333")

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT is_active FROM telegram_subscribers WHERE user_id = '333'"
            ).fetchone()
        assert row is not None
        assert row[0] == 0

    def test_reactivate_on_second_start(self, db_memory):
        """РџРѕСЃР»Рµ /stop РїРѕРІС‚РѕСЂРЅС‹Р№ /start СЂРµР°РєС‚РёРІРёСЂСѓРµС‚ РїРѕРґРїРёСЃС‡РёРєР°."""
        db_memory.add_telegram_subscriber("444")
        db_memory.remove_telegram_subscriber("444")
        db_memory.add_telegram_subscriber("444", first_name="РќРѕРІРѕРµ РёРјСЏ")

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT is_active, first_name FROM telegram_subscribers WHERE user_id = '444'"
            ).fetchone()
        assert row[0] == 1
        assert row[1] == "РќРѕРІРѕРµ РёРјСЏ"

    def test_get_subscribers_returns_only_active(self, db_memory):
        """get_telegram_subscribers РІРѕР·РІСЂР°С‰Р°РµС‚ С‚РѕР»СЊРєРѕ Р°РєС‚РёРІРЅС‹С…."""
        db_memory.add_telegram_subscriber("1")
        db_memory.add_telegram_subscriber("2")
        db_memory.add_telegram_subscriber("3")
        db_memory.remove_telegram_subscriber("2")

        result = db_memory.get_telegram_subscribers()
        assert set(result) == {"1", "3"}
        assert "2" not in result

    def test_count_subscribers_counts_only_active(self, db_memory):
        """count_telegram_subscribers СЃС‡РёС‚Р°РµС‚ С‚РѕР»СЊРєРѕ Р°РєС‚РёРІРЅС‹С…."""
        db_memory.add_telegram_subscriber("1")
        db_memory.add_telegram_subscriber("2")
        db_memory.remove_telegram_subscriber("1")

        assert db_memory.count_telegram_subscribers() == 1

    def test_pagination_skips_inactive(self, db_memory):
        """РџР°РіРёРЅР°С†РёСЏ get_telegram_subscribers РЅРµ РІРєР»СЋС‡Р°РµС‚ РЅРµР°РєС‚РёРІРЅС‹С…."""
        for i in range(5):
            db_memory.add_telegram_subscriber(str(i))
        db_memory.remove_telegram_subscriber("2")
        db_memory.remove_telegram_subscriber("4")

        page1 = db_memory.get_telegram_subscribers(limit=10, offset=0)
        assert set(page1) == {"0", "1", "3"}


# в”Ђв”Ђв”Ђ UserCategories.category_name в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class TestUserCategoryCategoryName:
    def _seed_category(self, db, cat_id, cat_name):
        """Р”РѕР±Р°РІР»СЏРµС‚ РєР°С‚РµРіРѕСЂРёСЋ РІ category_state (РєР°Рє СЌС‚Рѕ РґРµР»Р°РµС‚ РїР°СЂСЃРµСЂ)."""
        db.update_category_state(cat_id, cat_name, 1, "moscow")

    def test_toggle_stores_category_name(self, db_memory):
        """toggle_user_category СЃРѕС…СЂР°РЅСЏРµС‚ РЅР°Р·РІР°РЅРёРµ РєР°С‚РµРіРѕСЂРёРё РёР· category_state."""
        self._seed_category(db_memory, "cat-1", "РќРѕСѓС‚Р±СѓРєРё")
        db_memory.toggle_user_category("user1", "cat-1", "moscow")

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT category_name FROM user_categories WHERE user_id='user1' AND category_id='cat-1'"
            ).fetchone()
        assert row is not None
        assert row[0] == "РќРѕСѓС‚Р±СѓРєРё"

    def test_set_user_categories_stores_names(self, db_memory):
        """set_user_categories СЃРѕС…СЂР°РЅСЏРµС‚ РЅР°Р·РІР°РЅРёСЏ РІСЃРµС… РїРµСЂРµРґР°РЅРЅС‹С… РєР°С‚РµРіРѕСЂРёР№."""
        self._seed_category(db_memory, "cat-1", "РќРѕСѓС‚Р±СѓРєРё")
        self._seed_category(db_memory, "cat-2", "РЎРјР°СЂС‚С„РѕРЅС‹")

        db_memory.set_user_categories("user1", ["cat-1", "cat-2"], "moscow")

        with sqlite3.connect(db_memory.db_path) as conn:
            rows = conn.execute(
                "SELECT category_id, category_name FROM user_categories WHERE user_id='user1'"
            ).fetchall()
        result = {r[0]: r[1] for r in rows}
        assert result == {"cat-1": "РќРѕСѓС‚Р±СѓРєРё", "cat-2": "РЎРјР°СЂС‚С„РѕРЅС‹"}

    def test_toggle_remove_then_add_keeps_name(self, db_memory):
        """РџРѕСЃР»Рµ СЃРЅСЏС‚РёСЏ Рё РїРѕРІС‚РѕСЂРЅРѕРіРѕ РґРѕР±Р°РІР»РµРЅРёСЏ РєР°С‚РµРіРѕСЂРёСЏ СЃРѕС…СЂР°РЅСЏРµС‚ РёРјСЏ."""
        self._seed_category(db_memory, "cat-1", "РќРѕСѓС‚Р±СѓРєРё")
        db_memory.toggle_user_category("user1", "cat-1", "moscow")  # РґРѕР±Р°РІРёС‚СЊ
        db_memory.toggle_user_category("user1", "cat-1", "moscow")  # СѓР±СЂР°С‚СЊ
        db_memory.toggle_user_category("user1", "cat-1", "moscow")  # РґРѕР±Р°РІРёС‚СЊ СЃРЅРѕРІР°

        with sqlite3.connect(db_memory.db_path) as conn:
            row = conn.execute(
                "SELECT category_name FROM user_categories WHERE user_id='user1' AND category_id='cat-1'"
            ).fetchone()
        assert row[0] == "РќРѕСѓС‚Р±СѓРєРё"

    def test_set_empty_clears_categories(self, db_memory):
        """set_user_categories([]) РѕС‡РёС‰Р°РµС‚ РєР°С‚РµРіРѕСЂРёРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
        self._seed_category(db_memory, "cat-1", "РќРѕСѓС‚Р±СѓРєРё")
        db_memory.set_user_categories("user1", ["cat-1"], "moscow")
        db_memory.set_user_categories("user1", [], "moscow")

        with sqlite3.connect(db_memory.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM user_categories WHERE user_id='user1'"
            ).fetchall()
        assert rows == []

    def test_user_categories_table_has_category_name_column(self, db_memory):
        """РўР°Р±Р»РёС†Р° user_categories СЃРѕРґРµСЂР¶РёС‚ РєРѕР»РѕРЅРєСѓ category_name."""
        with sqlite3.connect(db_memory.db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(user_categories)")
            cols = {row[1] for row in cursor.fetchall()}
        assert "category_name" in cols

