"""
РўРµСЃС‚С‹ РґР»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёС… РЅР°СЃС‚СЂРѕРµРє: db_manager (user_settings, user_categories)
Рё С„РёР»СЊС‚СЂР°С†РёРё РІ TelegramNotifier.send_digest.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from dns_shop_parser.parser.db_manager import DBManager
from dns_shop_parser.services.telegram_notifier import TelegramNotifier


# в”Ђв”Ђв”Ђ DBManager: user_settings в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class TestUserSettings:
    def test_upsert_creates_defaults(self, db_memory):
        """upsert_user_settings Р±РµР· kwargs СЃРѕР·РґР°С‘С‚ Р·Р°РїРёСЃСЊ СЃ РґРµС„РѕР»С‚Р°РјРё."""
        db_memory.upsert_user_settings("user1")
        s = db_memory.get_user_settings("user1")

        assert s is not None
        assert s["city_slug"] == "moscow"
        assert s["notify_new"] is True
        assert s["notify_price_drop"] is True
        assert s["min_price_drop_pct"] == 0
        assert s["notifications_on"] is True

    def test_upsert_updates_fields(self, db_memory):
        """upsert_user_settings РѕР±РЅРѕРІР»СЏРµС‚ С‚РѕР»СЊРєРѕ РїРµСЂРµРґР°РЅРЅС‹Рµ РїРѕР»СЏ."""
        db_memory.upsert_user_settings("user1")
        db_memory.upsert_user_settings("user1", city_slug="spb", notify_new=0)

        s = db_memory.get_user_settings("user1")
        assert s["city_slug"] == "spb"
        assert s["notify_new"] is False
        assert s["notify_price_drop"] is True  # РЅРµ С‚СЂРѕРЅСѓС‚Рѕ

    def test_upsert_idempotent(self, db_memory):
        """РџРѕРІС‚РѕСЂРЅС‹Р№ upsert Р±РµР· kwargs РЅРµ РїРµСЂРµР·Р°РїРёСЃС‹РІР°РµС‚ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРµ РїРѕР»СЏ."""
        db_memory.upsert_user_settings("user1", city_slug="novosibirsk")
        db_memory.upsert_user_settings("user1")  # Р±РµР· kwargs

        s = db_memory.get_user_settings("user1")
        assert s["city_slug"] == "novosibirsk"

    def test_get_returns_none_for_unknown(self, db_memory):
        """get_user_settings РІРѕР·РІСЂР°С‰Р°РµС‚ None РґР»СЏ РЅРµРёР·РІРµСЃС‚РЅРѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
        assert db_memory.get_user_settings("nobody") is None

    def test_ignores_unknown_fields(self, db_memory):
        """upsert_user_settings РёРіРЅРѕСЂРёСЂСѓРµС‚ РЅРµРёР·РІРµСЃС‚РЅС‹Рµ РїРѕР»СЏ (SQL-РёРЅСЉРµРєС†РёСЏ РЅРµРІРѕР·РјРѕР¶РЅР°)."""
        db_memory.upsert_user_settings("user1", unknown_field="hacked")
        s = db_memory.get_user_settings("user1")
        assert s is not None  # Р·Р°РїРёСЃСЊ СЃРѕР·РґР°РЅР°, РЅРѕ РїРѕР»Рµ РїСЂРѕРёРіРЅРѕСЂРёСЂРѕРІР°РЅРѕ

    def test_min_price_drop_pct_values(self, db_memory):
        """min_price_drop_pct РєРѕСЂСЂРµРєС‚РЅРѕ СЃРѕС…СЂР°РЅСЏРµС‚ С‡РёСЃР»РѕРІС‹Рµ Р·РЅР°С‡РµРЅРёСЏ."""
        db_memory.upsert_user_settings("user1", min_price_drop_pct=15)
        assert db_memory.get_user_settings("user1")["min_price_drop_pct"] == 15

    def test_get_all_subscribers_with_settings_defaults(self, db_memory):
        """get_all_subscribers_with_settings РІРѕР·РІСЂР°С‰Р°РµС‚ РґРµС„РѕР»С‚С‹ РґР»СЏ РїРѕРґРїРёСЃС‡РёРєР° Р±РµР· РЅР°СЃС‚СЂРѕРµРє."""
        db_memory.add_telegram_subscriber("user1")

        rows = db_memory.get_all_subscribers_with_settings()
        assert len(rows) == 1
        s = rows[0]
        assert s["user_id"] == "user1"
        assert s["notify_new"] is True
        assert s["notifications_on"] is True

    def test_get_all_subscribers_with_settings_merges(self, db_memory):
        """get_all_subscribers_with_settings РІРѕР·РІСЂР°С‰Р°РµС‚ СЂРµР°Р»СЊРЅС‹Рµ РЅР°СЃС‚СЂРѕР№РєРё РµСЃР»Рё РµСЃС‚СЊ."""
        db_memory.add_telegram_subscriber("user1")
        db_memory.upsert_user_settings("user1", city_slug="kazan", notify_new=0)

        rows = db_memory.get_all_subscribers_with_settings()
        s = rows[0]
        assert s["city_slug"] == "kazan"
        assert s["notify_new"] is False

    def test_get_all_subscribers_excludes_non_subscribers(self, db_memory):
        """РџРѕР»СЊР·РѕРІР°С‚РµР»Рё СЃ РЅР°СЃС‚СЂРѕР№РєР°РјРё, РЅРѕ Р±РµР· РїРѕРґРїРёСЃРєРё вЂ” РЅРµ РІРѕР·РІСЂР°С‰Р°СЋС‚СЃСЏ."""
        db_memory.upsert_user_settings("user_no_sub")

        rows = db_memory.get_all_subscribers_with_settings()
        assert rows == []


# в”Ђв”Ђв”Ђ DBManager: user_categories в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class TestUserCategories:
    def test_get_empty_by_default(self, db_memory):
        """get_user_categories РІРѕР·РІСЂР°С‰Р°РµС‚ [] РґР»СЏ РЅРѕРІРѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
        assert db_memory.get_user_categories("user1", "moscow") == []

    def test_set_and_get(self, db_memory):
        """set_user_categories СЃРѕС…СЂР°РЅСЏРµС‚ СЃРїРёСЃРѕРє РєР°С‚РµРіРѕСЂРёР№."""
        db_memory.set_user_categories("user1", ["cat-1", "cat-2"], "moscow")
        assert set(db_memory.get_user_categories("user1", "moscow")) == {"cat-1", "cat-2"}

    def test_set_empty_clears(self, db_memory):
        """set_user_categories([]) РѕС‡РёС‰Р°РµС‚ РІС‹Р±РѕСЂ (= РІСЃРµ РєР°С‚РµРіРѕСЂРёРё)."""
        db_memory.set_user_categories("user1", ["cat-1"], "moscow")
        db_memory.set_user_categories("user1", [], "moscow")
        assert db_memory.get_user_categories("user1", "moscow") == []

    def test_set_replaces(self, db_memory):
        """set_user_categories РїРѕР»РЅРѕСЃС‚СЊСЋ Р·Р°РјРµРЅСЏРµС‚ РїСЂРµРґС‹РґСѓС‰РёР№ СЃРїРёСЃРѕРє."""
        db_memory.set_user_categories("user1", ["cat-1", "cat-2"], "moscow")
        db_memory.set_user_categories("user1", ["cat-3"], "moscow")
        assert db_memory.get_user_categories("user1", "moscow") == ["cat-3"]

    def test_toggle_adds(self, db_memory):
        """toggle_user_category РґРѕР±Р°РІР»СЏРµС‚ РєР°С‚РµРіРѕСЂРёСЋ РµСЃР»Рё РµС‘ РЅРµС‚."""
        added = db_memory.toggle_user_category("user1", "cat-1", "moscow")
        assert added is True
        assert "cat-1" in db_memory.get_user_categories("user1", "moscow")

    def test_toggle_removes(self, db_memory):
        """toggle_user_category СѓР±РёСЂР°РµС‚ РєР°С‚РµРіРѕСЂРёСЋ РµСЃР»Рё РѕРЅР° СѓР¶Рµ РµСЃС‚СЊ."""
        db_memory.set_user_categories("user1", ["cat-1"], "moscow")
        added = db_memory.toggle_user_category("user1", "cat-1", "moscow")
        assert added is False
        assert db_memory.get_user_categories("user1", "moscow") == []

    def test_toggle_independent_users(self, db_memory):
        """РљР°С‚РµРіРѕСЂРёРё СЂР°Р·РЅС‹С… РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ РЅРµ РїРµСЂРµСЃРµРєР°СЋС‚СЃСЏ."""
        db_memory.toggle_user_category("user1", "cat-1", "moscow")
        db_memory.toggle_user_category("user2", "cat-2", "moscow")
        assert db_memory.get_user_categories("user1", "moscow") == ["cat-1"]
        assert db_memory.get_user_categories("user2", "moscow") == ["cat-2"]


    def test_same_category_id_is_isolated_between_cities(self, db_memory):
        """Одинаковый category_id в разных городах хранится раздельно."""
        db_memory.set_user_categories("user1", ["cat-1"], "krasnodar")
        db_memory.set_user_categories("user1", ["cat-1", "cat-2"], "moscow")
        assert db_memory.get_user_categories("user1", "krasnodar") == ["cat-1"]
        assert set(db_memory.get_user_categories("user1", "moscow")) == {"cat-1", "cat-2"}

    def test_set_empty_clears_only_current_city(self, db_memory):
        """set_user_categories([]) очищает только текущий city_slug."""
        db_memory.set_user_categories("user1", ["cat-1"], "krasnodar")
        db_memory.set_user_categories("user1", ["cat-2"], "moscow")
        db_memory.set_user_categories("user1", [], "krasnodar")
        assert db_memory.get_user_categories("user1", "krasnodar") == []
        assert db_memory.get_user_categories("user1", "moscow") == ["cat-2"]
    def test_get_all_known_categories_empty(self, db_memory):
        """get_all_known_categories РІРѕР·РІСЂР°С‰Р°РµС‚ [] РµСЃР»Рё РїР°СЂСЃРµСЂ РµС‰С‘ РЅРµ Р·Р°РїСѓСЃРєР°Р»СЃСЏ."""
        assert db_memory.get_all_known_categories() == []

    def test_get_all_known_categories_after_state_update(self, db_memory):
        """get_all_known_categories РІРѕР·РІСЂР°С‰Р°РµС‚ РєР°С‚РµРіРѕСЂРёРё РёР· category_state."""
        db_memory.update_category_state("cat-1", "РќРѕСѓС‚Р±СѓРєРё", 10, "")
        db_memory.update_category_state("cat-2", "РњРѕРЅРёС‚РѕСЂС‹", 5, "")

        cats = db_memory.get_all_known_categories()
        ids = [c["id"] for c in cats]
        assert "cat-1" in ids
        assert "cat-2" in ids

    def test_get_all_known_categories_hides_sold(self, db_memory):
        """get_all_known_categories СЃРєСЂС‹РІР°РµС‚ РёСЃС‡РµР·РЅСѓРІС€РёРµ РєР°С‚РµРіРѕСЂРёРё."""
        db_memory.update_category_state("cat-1", "РќРѕСѓС‚Р±СѓРєРё", 1, "", ["uuid-1"])
        db_memory.delete_all_products_in_category("cat-1", "")

        assert db_memory.get_all_known_categories() == []


# в”Ђв”Ђв”Ђ TelegramNotifier: send_digest С„РёР»СЊС‚СЂР°С†РёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

NEW_PRODUCT = {
    "category_id": "cat-1",
    "category": "РќРѕСѓС‚Р±СѓРєРё",
    "title": "РќРѕСѓС‚Р±СѓРє A",
    "price": 50000,
    "price_old": 70000,
    "url": "https://dns-shop.ru/1",
    "status": "РќРѕРІС‹Р№",
}

PRICE_DROP = {
    "category_id": "cat-1",
    "title": "РќРѕСѓС‚Р±СѓРє B",
    "url": "https://dns-shop.ru/2",
    "new_price": 40000,
    "old_price": 50000,
    "price_old": 60000,
    "status": "РќРѕРІС‹Р№",
}


def _make_notifier(db, subscriber_settings: list[dict]):
    """РҐРµР»РїРµСЂ: СЃРѕР·РґР°С‘С‚ TelegramNotifier СЃ mock-Р±РѕС‚РѕРј Рё mock-Р‘Р”."""
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value="ok")

    mock_db = MagicMock()
    mock_db.get_all_subscribers_with_settings.return_value = subscriber_settings
    mock_db.get_user_categories.return_value = []
    mock_db.remove_telegram_subscriber = MagicMock()

    return TelegramNotifier(bot=bot, db=mock_db), bot, mock_db


class TestSendDigestFiltering:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_no_subscribers_sends_nothing(self):
        notifier, bot, _ = _make_notifier(None, [])
        notifier.db = MagicMock()
        notifier.db.get_all_subscribers_with_settings.return_value = []
        self._run(notifier.send_digest([NEW_PRODUCT], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_notifications_off_skips_user(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": False}
        notifier, bot, _ = _make_notifier(None, [sub])
        notifier.db = MagicMock()
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        notifier.db.get_user_categories.return_value = []
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        bot.send_message.assert_not_called()

    def test_notify_new_off_filters_new_products(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": False,
               "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # РўРѕР»СЊРєРѕ РЅРѕРІС‹Рµ С‚РѕРІР°СЂС‹, СЃРЅРёР¶РµРЅРёР№ РЅРµС‚ вЂ” РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РґРѕР»Р¶РµРЅ РЅРёС‡РµРіРѕ РїРѕР»СѓС‡РёС‚СЊ
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        bot.send_message.assert_not_called()

    def test_notify_price_drop_off_filters_drops(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # РўРѕР»СЊРєРѕ С†РµРЅРѕРІС‹Рµ РёР·РјРµРЅРµРЅРёСЏ вЂ” РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РґРѕР»Р¶РµРЅ РЅРёС‡РµРіРѕ РїРѕР»СѓС‡РёС‚СЊ
        self._run(notifier.send_digest([], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_min_price_drop_pct_filters_small_drops(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": False,
               "notify_price_drop": True, "min_price_drop_pct": 30, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # PRICE_DROP: 40000в†’50000 = 20% < 30% вЂ” РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РѕС‚С„РёР»СЊС‚СЂРѕРІР°РЅРѕ
        self._run(notifier.send_digest([], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_min_price_drop_pct_passes_large_drops(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": False,
               "notify_price_drop": True, "min_price_drop_pct": 10, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # PRICE_DROP: 20% > 10% вЂ” РґРѕР»Р¶РЅРѕ РїСЂРѕР№С‚Рё
        self._run(notifier.send_digest([], [PRICE_DROP]))
        bot.send_message.assert_called_once()

    def test_category_filter_blocks_other_categories(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РІС‹Р±СЂР°Р» С‚РѕР»СЊРєРѕ cat-2, Р° С‚РѕРІР°СЂ РёР· cat-1
        notifier.db.get_user_categories.return_value = ["cat-2"]
        self._run(notifier.send_digest([NEW_PRODUCT], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_category_filter_passes_selected_category(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РІС‹Р±СЂР°Р» cat-1 вЂ” СЃРѕРІРїР°РґР°РµС‚ СЃ NEW_PRODUCT
        notifier.db.get_user_categories.return_value = ["cat-1"]
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        bot.send_message.assert_called_once()

    def test_empty_category_filter_passes_all(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        notifier.db.get_user_categories.return_value = []  # РїСѓСЃС‚Рѕ = РІСЃРµ
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        bot.send_message.assert_called_once()

    def test_blocked_user_removed_from_subscribers(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        bot.send_message = AsyncMock(return_value="blocked")
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        notifier.db.get_user_categories.return_value = []
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        mock_db.remove_telegram_subscriber.assert_called_once_with("u1")

    def test_format_digest_contains_new_products(self):
        notifier = TelegramNotifier()
        msg = notifier._format_digest([NEW_PRODUCT], [])
        assert "Новые товары" in msg
        assert "https://dns-shop.ru/1" in msg

    def test_format_digest_contains_price_drops(self):
        notifier = TelegramNotifier()
        msg = notifier._format_digest([], [PRICE_DROP])
        assert "Снижение цен" in msg
        assert "https://dns-shop.ru/2" in msg

    def test_format_digest_shows_percent(self):
        notifier = TelegramNotifier()
        msg = notifier._format_digest([], [PRICE_DROP])
        assert "20%" in msg  # (50000-40000)/50000 = 20%

