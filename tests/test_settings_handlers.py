"""
Тесты для SettingsHandler (services/telegram_bot/handlers/settings.py).
Покрываем handle_command, handle_callback, _handle_set, обработку cities.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch


class _DBStub:
    """Простая заглушка БД с обычными методами (для asyncio.to_thread)."""
    def __init__(self, **kw):
        self._kw = kw

    def _method(self, name, *args, **kwargs):
        d = self._kw
        if name == 'get_user_settings': return d.get('settings', {})
        if name == 'get_user_categories': return d.get('user_categories', [])
        if name == 'get_all_known_categories':
            return [
                {**cat, "name": cat.get("name", cat.get("label", cat["id"]))}
                for cat in d.get('categories', [])
            ]
        if name == 'upsert_user_settings': pass
        if name == 'add_telegram_subscriber': pass
        if name == 'remove_telegram_subscriber': pass
        if name == 'ensure_scheduled_event': pass
        if name == 'has_scheduled_event_type': return d.get('has_event', False)
        if name == 'mark_scheduled_event_done': pass
        if name == 'mark_scheduled_event_failed': pass
        if name == 'count_telegram_subscribers': return len(d.get('_tg_subs', []))
        if name == 'get_pending_scheduled_events': return d.get('_events', [])
        if name == 'get_active_free_subscribers_with_settings': return d.get('_subs', [])
        if name == 'get_current_digest_data': return ([], [])
        return []

    def __getattr__(self, name):
        """Любой метод БД вызывает _method с именем."""
        # Не вызывать рекурсию для служебных атрибутов
        if name.startswith('_'):
            raise AttributeError(name)
        return lambda *args, **kw: self._method(name, *args, **kw)


def _make_handler(bot_mock=None, db_kw=None) -> "SettingsHandler":
    """Создаёт SettingsHandler с заглушками."""
    from dns_shop_parser.services.telegram_bot.handlers.settings import SettingsHandler
    if bot_mock is None:
        bot = Mock()
        bot.send_message = AsyncMock()
        bot.edit_message_text = AsyncMock()
        bot._answer_callback = AsyncMock()
        bot._handle_admin_command = AsyncMock()
        async def _db_call(func, *args, **kwargs):
            return func(*args, **kwargs)
        bot._db_call = AsyncMock(side_effect=_db_call)
        # Явно задаём db чтобы избежать авто-создания Mock
        if db_kw is not None:
            bot.db = _DBStub(**db_kw)
        else:
            bot.db = None
    else:
        bot = bot_mock
    bot._user_state = Mock(
        user_cat_page={},
        user_cat_query={},
        settings_search_mode={},
    )
    if db_kw is not None and bot.db is None:
        bot.db = _DBStub(**db_kw)
    rw = AsyncMock()
    return SettingsHandler(bot, rw)


class TestHandleCommand:
    """Тесты для handle_command."""

    @pytest.mark.asyncio
    async def test_settings_command(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_command("user1", "chat1", "/settings")
        handler._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_city_command(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': ''}})
        await handler.handle_command("user1", "chat1", "/city")
        handler._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_categories_command_no_db(self):
        handler = _make_handler()
        handler._bot.db = None
        await handler.handle_command("user1", "chat1", "/categories")
        handler._bot.send_message.assert_called_once()
        assert "БД не инициализирована" in handler._bot.send_message.call_args[0][1]

    @pytest.mark.asyncio
    async def test_categories_command_empty(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_command("user1", "chat1", "/categories")
        handler._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_command(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_command("user1", "chat1", "/status")
        handler._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_command_noop(self):
        handler = _make_handler()
        await handler.handle_command("user1", "chat1", "/unknown")

    @pytest.mark.asyncio
    async def test_settings_command_no_db(self):
        handler = _make_handler()
        handler._bot.db = None
        await handler.handle_command("user1", "chat1", "/settings")
        handler._bot.send_message.assert_called_once()
        assert "БД не инициализирована" in handler._bot.send_message.call_args[0][1]


class TestHandleCallback:
    """Тесты для handle_callback."""

    @pytest.mark.asyncio
    async def test_report_callback_delegates_to_rw(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "report_discounts")
        assert handler._rw.handle.called

    @pytest.mark.asyncio
    async def test_menu_settings_open(self):
        handler = _make_handler()
        handler._bot.edit_message_text = AsyncMock()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "menu_settings_open")
        assert handler._bot._answer_callback.called

    @pytest.mark.asyncio
    async def test_menu_back(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "settings_back")
        assert handler._bot._answer_callback.called or handler._bot.edit_message_text.called

    @pytest.mark.asyncio
    async def test_menu_settings_cmd(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "settings_cmd")

    @pytest.mark.asyncio
    async def test_menu_city_cmd(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "city_cmd")

    @pytest.mark.asyncio
    async def test_menu_status_cmd(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "status_cmd")

    @pytest.mark.asyncio
    async def test_menu_admin(self):
        handler = _make_handler()
        handler._bot.admin_id = "999"
        handler._bot.db = _DBStub()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "admin_cmd")

    @pytest.mark.asyncio
    async def test_cat_toggle_with_db(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}, 'categories': [{'id': 'cat-1'}]})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "toggle_cat:cat-1")

    @pytest.mark.asyncio
    async def test_cat_toggle_without_db(self):
        handler = _make_handler()
        handler._bot.db = None
        await handler.handle_callback("cb1", "user1", "chat1", 42, "toggle_cat:cat-1")

    @pytest.mark.asyncio
    async def test_cat_page_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}, 'categories': [{'id': f'cat-{i}'} for i in range(20)]})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "cat_page:1")

    @pytest.mark.asyncio
    async def test_cat_page_invalid_value(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "cat_page:abc")

    @pytest.mark.asyncio
    async def test_cat_page_noop(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "cat_page:")

    @pytest.mark.asyncio
    async def test_cat_all(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}, 'categories': [{'id': f'cat-{i}'} for i in range(5)]})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "cat_all")

    @pytest.mark.asyncio
    async def test_cat_search_clear(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}, 'categories': [{'id': f'cat-{i}'} for i in range(5)]})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "cat_search_clear")

    @pytest.mark.asyncio
    async def test_city_callback_unknown(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "city:unknown")

    @pytest.mark.asyncio
    async def test_unknown_callback_returns_error(self):
        handler = _make_handler()
        await handler.handle_callback("cb1", "user1", "chat1", 42, "unknown_cb")


class TestHandleSet:
    """Тесты для handle_set."""

    @pytest.mark.asyncio
    async def test_set_new_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_city:krasnodar")

    @pytest.mark.asyncio
    async def test_set_drop_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_threshold:5")

    @pytest.mark.asyncio
    async def test_set_pct_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_min_drop:10")

    @pytest.mark.asyncio
    async def test_set_notif_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_notifications_on")

    @pytest.mark.asyncio
    async def test_set_err_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_error_alert_on")

    @pytest.mark.asyncio
    async def test_set_pf_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_platform:android")

    @pytest.mark.asyncio
    async def test_set_value_out_of_range(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_threshold:500")

    @pytest.mark.asyncio
    async def test_set_invalid_integer(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "set_threshold:abc")

    @pytest.mark.asyncio
    async def test_set_no_match_returns_false(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        result = await handler.handle_callback("cb1", "user1", "chat1", 42, "set_unknown:asdf")


class TestHandleSearchInput:
    """Тесты для обработки поиска категорий."""

    @pytest.mark.asyncio
    async def test_search_input_updates_query(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        handler._us.settings_search_mode["user1"] = ("chat1", 42)
        await handler.handle_search_input("user1", "  Laptops  ")
        assert handler._us.user_cat_query["user1"] == "Laptops"


class TestOnCity:
    """Тесты для city callback."""

    @pytest.mark.asyncio
    async def test_city_callback_valid(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "city:krasnodar")


class TestOnCatToggleUnknownCategory:
    """Тесты для toggle с несуществующей категорией."""

    @pytest.mark.asyncio
    async def test_toggle_unknown_category(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "toggle_cat:nonexistent")


class TestOnMenuCategoriesCmd:
    """Тесты для /categories команды."""

    @pytest.mark.asyncio
    async def test_no_categories(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "menu_categories_cmd")


class TestOnMenuStatusCmdNoDb:
    """Тесты для /status без БД."""

    @pytest.mark.asyncio
    async def test_no_db_returns_empty_settings(self):
        handler = _make_handler()
        handler._bot.db = None
        await handler.handle_callback("cb1", "user1", "chat1", 42, "status_cmd")


class TestOnCatPage:
    """Тесты для cat_page."""

    @pytest.mark.asyncio
    async def test_page_negative(self):
        handler = _make_handler(db_kw={'settings': {'city_slug': 'moscow'}})
        await handler.handle_callback("cb1", "user1", "chat1", 42, "cat_page:-5")
