"""
Тесты для нового и исправленного функционала:
- admin notification settings (notify_errors, notify_parse_finish)
- батчинг в fetch_products_details
- send_admin_alert / send_admin_parse_finish
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from parser.db_manager import DBManager
from services.telegram_notifier import TelegramNotifier
from services.telegram_bot import TelegramBot


# ─── TelegramNotifier: admin alerts ───────────────────────────────────────────

class TestAdminAlerts:
    def _make_notifier(self, admin_id="999", notify_errors=True, notify_parse_finish=True):
        mock_bot = MagicMock()
        mock_bot.admin_id = admin_id
        mock_bot.send_message = AsyncMock(return_value="ok")
        mock_bot.close = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.get_all_subscribers_with_settings.return_value = [
            {"user_id": admin_id, "notify_errors": notify_errors,
             "notify_parse_finish": notify_parse_finish},
        ]
        notifier = TelegramNotifier(bot=mock_bot, db=mock_db)
        return notifier, mock_bot, mock_db

    def test_send_admin_alert_disabled_when_bot_none(self):
        """send_admin_alert не падает если bot=None."""
        notifier = TelegramNotifier(bot=None)
        # не должно выбросить
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            notifier.send_admin_alert("test", msg_type="error")
        )

    @pytest.mark.asyncio
    async def test_send_admin_alert_error_skipped_when_notify_errors_false(self):
        """Ошибки не отправляются если notify_errors=False."""
        notifier, mock_bot, _ = self._make_notifier(notify_errors=False)
        await notifier.send_admin_alert("some error", msg_type="error")
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_admin_alert_error_sent_when_notify_errors_true(self):
        """Ошибка отправляется если notify_errors=True."""
        notifier, mock_bot, _ = self._make_notifier(notify_errors=True)
        await notifier.send_admin_alert("ERROR: something broke", msg_type="error")
        mock_bot.send_message.assert_awaited_once_with("999", "ERROR: something broke")

    @pytest.mark.asyncio
    async def test_send_admin_alert_parse_finish_skipped_when_notify_parse_finish_false(self):
        """Сводка о парсинге не отправляется если notify_parse_finish=False."""
        notifier, mock_bot, _ = self._make_notifier(notify_parse_finish=False)
        await notifier.send_admin_alert("parse finish", msg_type="parse_finish")
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_admin_alert_parse_finish_sent_when_notify_parse_finish_true(self):
        """Сводка о парсинге отправляется если notify_parse_finish=True."""
        notifier, mock_bot, _ = self._make_notifier(notify_parse_finish=True)
        await notifier.send_admin_alert("parse finish", msg_type="parse_finish")
        mock_bot.send_message.assert_awaited_once_with("999", "parse finish")

    @pytest.mark.asyncio
    async def test_send_admin_parse_finish_formats_message(self):
        """send_admin_parse_finish отправляет правильно отформатированное сообщение."""
        notifier, mock_bot, _ = self._make_notifier(notify_parse_finish=True)
        await notifier.send_admin_parse_finish(
            new_cnt=5, updated_cnt=100, price_changed=2,
            total_db=500, prev_cnt=510, delta=-10,
        )
        args = mock_bot.send_message.call_args[0]
        assert "📋" in args[1]
        assert "🆕 Новых: 5" in args[1]
        assert "🔄 Обновлено: 100" in args[1]
        assert "💰 Цены изменились: 2" in args[1]
        assert "📦 Всего в БД: 500" in args[1]
        assert "(-10)" in args[1]  # delta < 0 → скобки

    @pytest.mark.asyncio
    async def test_send_admin_parse_finish_positive_delta(self):
        """Положительный delta показывается как (+N)."""
        notifier, mock_bot, _ = self._make_notifier(notify_parse_finish=True)
        await notifier.send_admin_parse_finish(
            new_cnt=1, updated_cnt=10, price_changed=0,
            total_db=20, prev_cnt=15, delta=5,
        )
        assert "(+5)" in mock_bot.send_message.call_args[0][1]

    @pytest.mark.asyncio
    async def test_admin_settings_cached(self):
        """Настройки админа кешируются (один запрос к БД)."""
        notifier, _, mock_db = self._make_notifier()
        await notifier.send_admin_alert("test1", msg_type="error")
        await notifier.send_admin_alert("test2", msg_type="error")
        await notifier.send_admin_parse_finish(0, 0, 0, 0, 0, 0)
        # БД запрашивается один раз
        assert mock_db.get_all_subscribers_with_settings.call_count == 1

    @pytest.mark.asyncio
    async def test_admin_settings_cache_invalidate(self):
        """_invalidate_admin_settings сбрасывает кеш."""
        notifier, _, mock_db = self._make_notifier()
        await notifier.send_admin_alert("test", msg_type="error")
        assert mock_db.get_all_subscribers_with_settings.call_count == 1

        notifier._invalidate_admin_settings()
        await notifier.send_admin_alert("test", msg_type="error")
        assert mock_db.get_all_subscribers_with_settings.call_count == 2

    @pytest.mark.asyncio
    async def test_close_clears_cache(self):
        """close() сбрасывает _admin_settings."""
        notifier, _, _ = self._make_notifier()
        notifier._admin_settings = {"test": "data"}
        await notifier.close()
        # bot.close() вызван, _admin_settings сброшен
        assert notifier._admin_settings is None
        assert notifier.bot.close.await_count == 1

    @pytest.mark.asyncio
    async def test_admin_not_in_subscribers_no_crash(self):
        """Если админ не подписан — отправка всё равно работает (по admin_id)."""
        mock_bot = MagicMock()
        mock_bot.admin_id = "999"
        mock_bot.send_message = AsyncMock(return_value="ok")
        mock_db = MagicMock()
        mock_db.get_all_subscribers_with_settings.return_value = [
            {"user_id": "other_user", "notify_errors": True, "notify_parse_finish": True},
        ]
        notifier = TelegramNotifier(bot=mock_bot, db=mock_db)
        # Админ получает сообщение потому что notify_errors=True по умолчанию
        await notifier.send_admin_alert("admin message", msg_type="error")
        mock_bot.send_message.assert_called_once_with("999", "admin message")


# ─── DBManager: notify_errors / notify_parse_finish ──────────────────────────

class TestAdminNotificationSettings:
    def test_upsert_creates_admin_flags_defaults(self, db_memory):
        """Новый пользователь получает notify_errors=1, notify_parse_finish=1."""
        db_memory.upsert_user_settings("user1")
        s = db_memory.get_user_settings("user1")
        assert s["notify_errors"] is True
        assert s["notify_parse_finish"] is True

    def test_upsert_toggles_notify_errors(self, db_memory):
        """notify_errors корректно переключается 0↔1."""
        db_memory.upsert_user_settings("user1", notify_errors=0)
        assert db_memory.get_user_settings("user1")["notify_errors"] is False

        db_memory.upsert_user_settings("user1", notify_errors=1)
        assert db_memory.get_user_settings("user1")["notify_errors"] is True

    def test_upsert_toggles_notify_parse_finish(self, db_memory):
        """notify_parse_finish корректно переключается 0↔1."""
        db_memory.upsert_user_settings("user1", notify_parse_finish=0)
        assert db_memory.get_user_settings("user1")["notify_parse_finish"] is False

        db_memory.upsert_user_settings("user1", notify_parse_finish=1)
        assert db_memory.get_user_settings("user1")["notify_parse_finish"] is True

    def test_get_all_subscribers_includes_admin_flags(self, db_memory):
        """get_all_subscribers_with_settings возвращает новые флаги."""
        db_memory.add_telegram_subscriber("user1")
        db_memory.upsert_user_settings("user1", notify_errors=0, notify_parse_finish=0)

        rows = db_memory.get_all_subscribers_with_settings()
        assert len(rows) == 1
        assert rows[0]["notify_errors"] is False
        assert rows[0]["notify_parse_finish"] is False

    def test_get_all_subscribers_defaults_for_new_flags(self, db_memory):
        """COALESCE возвращает 1 для отсутствующих колонок."""
        db_memory.add_telegram_subscriber("user1")
        # upsert без флагов
        db_memory.upsert_user_settings("user1", city_slug="kazan")

        rows = db_memory.get_all_subscribers_with_settings()
        assert rows[0]["notify_errors"] is True  # COALESCE → default 1
        assert rows[0]["notify_parse_finish"] is True


# ─── TelegramBot: admin notify keyboard ──────────────────────────────────────

def _make_bot(db=None, parser_controller=None, admin_id="999"):
    bot = TelegramBot.__new__(TelegramBot)
    bot.token = "test"
    bot.api_url = "https://api.telegram.org/bottest"
    bot.db = db
    bot.enabled = True
    bot.admin_id = admin_id
    bot.subscribed_users = set()
    bot._session = None
    bot._waiting_for_interval = set()
    bot._broadcast_lock = asyncio.Lock()
    bot._subscriber_lock = asyncio.Lock()
    bot._user_cat_page = {}
    bot._report_state = {}
    bot._report_cat_page = {}
    bot._report_search_mode = {}
    bot._settings_search_mode = {}
    bot._user_cat_query = {}
    bot.parser_controller = parser_controller
    # Инициализируем admin_panel для доступа к admin-функциям
    from services.admin_panel import ParserController
    bot._parser_controller = parser_controller if parser_controller else MagicMock(spec=ParserController)
    return bot


class TestAdminNotifyKeyboard:
    def test_build_admin_notify_keyboard_on(self):
        """Обе кнопки ВКЛ → ✅ Ошибки: ВКЛ / ✅ Парсинг: ВКЛ."""
        bot = _make_bot()
        kb = bot._build_admin_notify_keyboard(
            {"notify_errors": True, "notify_parse_finish": True}
        )
        rows = kb["inline_keyboard"]
        assert rows[0][0]["text"] == "✅ Ошибки: ВКЛ"
        assert rows[0][0]["callback_data"] == "set_err:0"
        assert rows[0][1]["text"] == "✅ Парсинг: ВКЛ"
        assert rows[0][1]["callback_data"] == "set_pf:0"

    def test_build_admin_notify_keyboard_off(self):
        """Обе кнопки ВЫКЛ → ❌ Ошибки: ВЫКЛ / ❌ Парсинг: ВЫКЛ."""
        bot = _make_bot()
        kb = bot._build_admin_notify_keyboard(
            {"notify_errors": False, "notify_parse_finish": False}
        )
        rows = kb["inline_keyboard"]
        assert rows[0][0]["text"] == "❌ Ошибки: ВЫКЛ"
        assert rows[0][0]["callback_data"] == "set_err:1"
        assert rows[0][1]["text"] == "❌ Парсинг: ВЫКЛ"
        assert rows[0][1]["callback_data"] == "set_pf:1"

    def test_build_admin_notify_keyboard_mixed(self):
        """Ошибки выкл, парсинг вкл."""
        bot = _make_bot()
        kb = bot._build_admin_notify_keyboard(
            {"notify_errors": False, "notify_parse_finish": True}
        )
        rows = kb["inline_keyboard"]
        assert rows[0][0]["text"] == "❌ Ошибки: ВЫКЛ"
        assert rows[0][1]["text"] == "✅ Парсинг: ВКЛ"

    def test_build_admin_notify_keyboard_defaults(self):
        """Отсутствующие ключи → дефолт True."""
        bot = _make_bot()
        kb = bot._build_admin_notify_keyboard({})
        rows = kb["inline_keyboard"]
        assert rows[0][0]["text"] == "✅ Ошибки: ВКЛ"  # default True
        assert rows[0][1]["text"] == "✅ Парсинг: ВКЛ"  # default True

    def test_build_admin_keyboard_includes_back_to_main_menu(self):
        """Проверяем что admin_notify keyboard содержит кнопку возврата."""
        bot = _make_bot()
        kb = bot._build_admin_notify_keyboard({})
        rows = kb["inline_keyboard"]
        # Последний ряд должен содержать "Назад"
        last_row = rows[-1]
        assert any("Назад" in b["text"] for b in last_row)

    def test_build_admin_keyboard_includes_notify_button(self):
        """Проверяем наличие обоих toggle-кнопок."""
        kb = _make_bot()._build_admin_notify_keyboard({})
        flat = [b for row in kb["inline_keyboard"] for b in row]
        assert any("Ошибки" in b["text"] for b in flat)
        assert any("Парсинг" in b["text"] for b in flat)


# ─── TelegramBot: admin callback routing ───────────────────────────────────────

@pytest.mark.asyncio
async def test_callback_set_err_routed_to_user_settings_handler(monkeypatch):
    """set_err:N попадает в _handle_user_settings_callback (подписчик)."""
    db = MagicMock()
    db.get_user_settings.return_value = {
        "notify_errors": True, "notify_parse_finish": True,
    }
    bot = _make_bot(db=db)
    bot.subscribed_users = {"999"}
    bot._answer_callback = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=True)

    await bot._handle_callback_query({
        "id": "q1",
        "from": {"id": 999},
        "message": {"chat": {"id": 111}, "message_id": 10},
        "data": "set_err:0",
    })

    db.upsert_user_settings.assert_called_with("999", notify_errors=0)


@pytest.mark.asyncio
async def test_callback_set_pf_routed_to_user_settings_handler(monkeypatch):
    """set_pf:N попадает в _handle_user_settings_callback (подписчик)."""
    db = MagicMock()
    db.get_user_settings.return_value = {
        "notify_errors": True, "notify_parse_finish": True,
    }
    bot = _make_bot(db=db)
    bot.subscribed_users = {"999"}
    bot._answer_callback = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=True)

    await bot._handle_callback_query({
        "id": "q1",
        "from": {"id": 999},
        "message": {"chat": {"id": 111}, "message_id": 10},
        "data": "set_pf:0",
    })

    db.upsert_user_settings.assert_called_with("999", notify_parse_finish=0)


@pytest.mark.asyncio
async def test_callback_set_err_updates_keyboard_to_admin():
    """set_err:N для админа обновляет сообщение админ-клавиатурой."""
    db = MagicMock()
    db.get_user_settings.return_value = {
        "notify_errors": False, "notify_parse_finish": True,
    }
    bot = _make_bot(db=db, admin_id="999")
    bot.subscribed_users = {"999"}
    bot._answer_callback = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=True)

    await bot._handle_callback_query({
        "id": "q1",
        "from": {"id": 999},
        "message": {"chat": {"id": 111}, "message_id": 10},
        "data": "set_err:1",
    })

    # edit_message_text вызван с админской клавиатурой (проверяем reply_markup)
    args, kwargs = bot.edit_message_text.call_args
    assert kwargs.get("reply_markup", {}).get("inline_keyboard") is not None


@pytest.mark.asyncio
async def test_callback_admin_notify_updates_message_inline():
    """admin_notify обновляет сообщение inline."""
    db = MagicMock()
    db.get_user_settings.return_value = {"notify_errors": True, "notify_parse_finish": True}
    bot = _make_bot(db=db, admin_id="999")
    bot._answer_callback = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=True)

    await bot._handle_callback_query({
        "id": "q1",
        "from": {"id": 999},
        "message": {"chat": {"id": 111}, "message_id": 5},
        "data": "admin_notify",
    })

    # edit_message_text вызван - проверяем позиционные args (text идёт 3-м)
    args, kwargs = bot.edit_message_text.call_args
    assert "Уведомления админа" in args[2]
    bot._answer_callback.assert_awaited()


@pytest.mark.asyncio
async def test_callback_admin_back_returns_to_admin_panel():
    """admin_back обновляет сообщение админ-панелью."""
    db = MagicMock()
    db.get_user_settings.return_value = {"notify_errors": True, "notify_parse_finish": True}
    bot = _make_bot(db=db, admin_id="999")
    bot._answer_callback = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=True)

    await bot._handle_callback_query({
        "id": "q1",
        "from": {"id": 999},
        "message": {"chat": {"id": 111}, "message_id": 7},
        "data": "admin_back",
    })

    args, kwargs = bot.edit_message_text.call_args
    assert "Админ-панель" in args[2]