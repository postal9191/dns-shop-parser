"""
Тесты для пользовательских настроек: db_manager (user_settings, user_categories)
и фильтрации в TelegramNotifier.send_digest.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from parser.db_manager import DBManager
from services.telegram_notifier import TelegramNotifier


# ─── DBManager: user_settings ────────────────────────────────────────────────

class TestUserSettings:
    def test_upsert_creates_defaults(self, db_memory):
        """upsert_user_settings без kwargs создаёт запись с дефолтами."""
        db_memory.upsert_user_settings("user1")
        s = db_memory.get_user_settings("user1")

        assert s is not None
        assert s["city_slug"] == "moscow"
        assert s["notify_new"] is True
        assert s["notify_price_drop"] is True
        assert s["min_price_drop_pct"] == 0
        assert s["notifications_on"] is True

    def test_upsert_updates_fields(self, db_memory):
        """upsert_user_settings обновляет только переданные поля."""
        db_memory.upsert_user_settings("user1")
        db_memory.upsert_user_settings("user1", city_slug="spb", notify_new=0)

        s = db_memory.get_user_settings("user1")
        assert s["city_slug"] == "spb"
        assert s["notify_new"] is False
        assert s["notify_price_drop"] is True  # не тронуто

    def test_upsert_idempotent(self, db_memory):
        """Повторный upsert без kwargs не перезаписывает существующие поля."""
        db_memory.upsert_user_settings("user1", city_slug="novosibirsk")
        db_memory.upsert_user_settings("user1")  # без kwargs

        s = db_memory.get_user_settings("user1")
        assert s["city_slug"] == "novosibirsk"

    def test_get_returns_none_for_unknown(self, db_memory):
        """get_user_settings возвращает None для неизвестного пользователя."""
        assert db_memory.get_user_settings("nobody") is None

    def test_ignores_unknown_fields(self, db_memory):
        """upsert_user_settings игнорирует неизвестные поля (SQL-инъекция невозможна)."""
        db_memory.upsert_user_settings("user1", unknown_field="hacked")
        s = db_memory.get_user_settings("user1")
        assert s is not None  # запись создана, но поле проигнорировано

    def test_min_price_drop_pct_values(self, db_memory):
        """min_price_drop_pct корректно сохраняет числовые значения."""
        db_memory.upsert_user_settings("user1", min_price_drop_pct=15)
        assert db_memory.get_user_settings("user1")["min_price_drop_pct"] == 15

    def test_get_all_subscribers_with_settings_defaults(self, db_memory):
        """get_all_subscribers_with_settings возвращает дефолты для подписчика без настроек."""
        db_memory.add_telegram_subscriber("user1")

        rows = db_memory.get_all_subscribers_with_settings()
        assert len(rows) == 1
        s = rows[0]
        assert s["user_id"] == "user1"
        assert s["notify_new"] is True
        assert s["notifications_on"] is True

    def test_get_all_subscribers_with_settings_merges(self, db_memory):
        """get_all_subscribers_with_settings возвращает реальные настройки если есть."""
        db_memory.add_telegram_subscriber("user1")
        db_memory.upsert_user_settings("user1", city_slug="kazan", notify_new=0)

        rows = db_memory.get_all_subscribers_with_settings()
        s = rows[0]
        assert s["city_slug"] == "kazan"
        assert s["notify_new"] is False

    def test_get_all_subscribers_excludes_non_subscribers(self, db_memory):
        """Пользователи с настройками, но без подписки — не возвращаются."""
        db_memory.upsert_user_settings("user_no_sub")

        rows = db_memory.get_all_subscribers_with_settings()
        assert rows == []


# ─── DBManager: user_categories ──────────────────────────────────────────────

class TestUserCategories:
    def test_get_empty_by_default(self, db_memory):
        """get_user_categories возвращает [] для нового пользователя."""
        assert db_memory.get_user_categories("user1") == []

    def test_set_and_get(self, db_memory):
        """set_user_categories сохраняет список категорий."""
        db_memory.set_user_categories("user1", ["cat-1", "cat-2"])
        assert set(db_memory.get_user_categories("user1")) == {"cat-1", "cat-2"}

    def test_set_empty_clears(self, db_memory):
        """set_user_categories([]) очищает выбор (= все категории)."""
        db_memory.set_user_categories("user1", ["cat-1"])
        db_memory.set_user_categories("user1", [])
        assert db_memory.get_user_categories("user1") == []

    def test_set_replaces(self, db_memory):
        """set_user_categories полностью заменяет предыдущий список."""
        db_memory.set_user_categories("user1", ["cat-1", "cat-2"])
        db_memory.set_user_categories("user1", ["cat-3"])
        assert db_memory.get_user_categories("user1") == ["cat-3"]

    def test_toggle_adds(self, db_memory):
        """toggle_user_category добавляет категорию если её нет."""
        added = db_memory.toggle_user_category("user1", "cat-1")
        assert added is True
        assert "cat-1" in db_memory.get_user_categories("user1")

    def test_toggle_removes(self, db_memory):
        """toggle_user_category убирает категорию если она уже есть."""
        db_memory.set_user_categories("user1", ["cat-1"])
        added = db_memory.toggle_user_category("user1", "cat-1")
        assert added is False
        assert db_memory.get_user_categories("user1") == []

    def test_toggle_independent_users(self, db_memory):
        """Категории разных пользователей не пересекаются."""
        db_memory.toggle_user_category("user1", "cat-1")
        db_memory.toggle_user_category("user2", "cat-2")
        assert db_memory.get_user_categories("user1") == ["cat-1"]
        assert db_memory.get_user_categories("user2") == ["cat-2"]

    def test_get_all_known_categories_empty(self, db_memory):
        """get_all_known_categories возвращает [] если парсер ещё не запускался."""
        assert db_memory.get_all_known_categories() == []

    def test_get_all_known_categories_after_state_update(self, db_memory):
        """get_all_known_categories возвращает категории из category_state."""
        db_memory.update_category_state("cat-1", "Ноутбуки", 10)
        db_memory.update_category_state("cat-2", "Мониторы", 5)

        cats = db_memory.get_all_known_categories()
        ids = [c["id"] for c in cats]
        assert "cat-1" in ids
        assert "cat-2" in ids


# ─── TelegramNotifier: send_digest фильтрация ────────────────────────────────

NEW_PRODUCT = {
    "category_id": "cat-1",
    "category": "Ноутбуки",
    "title": "Ноутбук A",
    "price": 50000,
    "price_old": 70000,
    "url": "https://dns-shop.ru/1",
    "status": "Новый",
}

PRICE_DROP = {
    "category_id": "cat-1",
    "title": "Ноутбук B",
    "url": "https://dns-shop.ru/2",
    "new_price": 40000,
    "old_price": 50000,
    "price_old": 60000,
    "status": "Новый",
}


def _make_notifier(db, subscriber_settings: list[dict]):
    """Хелпер: создаёт TelegramNotifier с mock-ботом и mock-БД."""
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
        # Только новые товары, снижений нет — пользователь не должен ничего получить
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        bot.send_message.assert_not_called()

    def test_notify_price_drop_off_filters_drops(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # Только ценовые изменения — пользователь не должен ничего получить
        self._run(notifier.send_digest([], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_min_price_drop_pct_filters_small_drops(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": False,
               "notify_price_drop": True, "min_price_drop_pct": 30, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # PRICE_DROP: 40000→50000 = 20% < 30% — должно быть отфильтровано
        self._run(notifier.send_digest([], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_min_price_drop_pct_passes_large_drops(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": False,
               "notify_price_drop": True, "min_price_drop_pct": 10, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # PRICE_DROP: 20% > 10% — должно пройти
        self._run(notifier.send_digest([], [PRICE_DROP]))
        bot.send_message.assert_called_once()

    def test_category_filter_blocks_other_categories(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # Пользователь выбрал только cat-2, а товар из cat-1
        notifier.db.get_user_categories.return_value = ["cat-2"]
        self._run(notifier.send_digest([NEW_PRODUCT], [PRICE_DROP]))
        bot.send_message.assert_not_called()

    def test_category_filter_passes_selected_category(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        # Пользователь выбрал cat-1 — совпадает с NEW_PRODUCT
        notifier.db.get_user_categories.return_value = ["cat-1"]
        self._run(notifier.send_digest([NEW_PRODUCT], []))
        bot.send_message.assert_called_once()

    def test_empty_category_filter_passes_all(self):
        sub = {"user_id": "u1", "city_slug": "moscow", "notify_new": True,
               "notify_price_drop": False, "min_price_drop_pct": 0, "notifications_on": True}
        notifier, bot, mock_db = _make_notifier(None, [sub])
        notifier.db = mock_db
        notifier.db.get_all_subscribers_with_settings.return_value = [sub]
        notifier.db.get_user_categories.return_value = []  # пусто = все
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
        assert "Ноутбук A" in msg

    def test_format_digest_contains_price_drops(self):
        notifier = TelegramNotifier()
        msg = notifier._format_digest([], [PRICE_DROP])
        assert "Снижение цен" in msg
        assert "Ноутбук B" in msg

    def test_format_digest_shows_percent(self):
        notifier = TelegramNotifier()
        msg = notifier._format_digest([], [PRICE_DROP])
        assert "20%" in msg  # (50000-40000)/50000 = 20%
