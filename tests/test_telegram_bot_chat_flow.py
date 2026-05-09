import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from services.telegram_bot import TelegramBot


def _make_bot(db=None, parser_controller=None) -> TelegramBot:
    bot = TelegramBot.__new__(TelegramBot)
    bot.token = "test"
    bot.api_url = "https://api.telegram.org/bottest"
    bot.db = db
    bot.enabled = True
    bot.admin_id = "999"
    bot.subscribed_users = set()
    bot._session = None
    bot.parser_controller = parser_controller
    from services.telegram_bot.state import UserState
    # __init__ is not called via __new__, so call UserState.__init__ manually
    bot._user_state = object.__new__(UserState)
    UserState.__init__(bot._user_state)
    # Initialize handlers
    from services.telegram_bot.handlers.reports import ReportWizard
    from services.telegram_bot.handlers.settings import SettingsHandler
    from services.telegram_bot.handlers.admin import AdminHandler
    bot._report_wizard = ReportWizard(bot)
    bot._settings = SettingsHandler(bot, bot._report_wizard)
    bot._admin = AdminHandler(bot)
    # _handle_interval_input and _send_logs are now methods on the bot class (aliases)
    return bot


@pytest.mark.asyncio
async def test_send_message_returns_ok():
    bot = _make_bot()
    bot._telegram_request = AsyncMock(return_value=(200, {"ok": True}))

    result = await bot.send_message("chat1", "hello")

    assert result == "ok"
    bot._telegram_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_returns_blocked_for_403():
    bot = _make_bot()
    bot._telegram_request = AsyncMock(return_value=(403, {"description": "bot was blocked by the user"}))

    result = await bot.send_message("chat1", "hello")

    assert result == "blocked"


@pytest.mark.asyncio
async def test_send_message_returns_blocked_for_chat_not_found():
    bot = _make_bot()
    bot._telegram_request = AsyncMock(return_value=(400, {"description": "Bad Request: chat not found"}))

    result = await bot.send_message("chat1", "hello")

    assert result == "blocked"


@pytest.mark.asyncio
async def test_send_message_retries_after_rate_limit(monkeypatch):
    bot = _make_bot()
    bot._telegram_request = AsyncMock(side_effect=[
        (429, {"parameters": {"retry_after": 0}}),
        (200, {"ok": True}),
    ])
    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    result = await bot.send_message("chat1", "hello")

    assert result == "ok"
    assert bot._telegram_request.await_count == 2
    sleep_mock.assert_awaited()


@pytest.mark.asyncio
async def test_send_message_retries_server_error_then_succeeds(monkeypatch):
    bot = _make_bot()
    bot._telegram_request = AsyncMock(side_effect=[
        (500, {"description": "Internal Server Error"}),
        (200, {"ok": True}),
    ])
    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    result = await bot.send_message("chat1", "hello")

    assert result == "ok"
    assert bot._telegram_request.await_count == 2
    sleep_mock.assert_awaited()


@pytest.mark.asyncio
async def test_broadcast_message_counts_success_and_removes_blocked(monkeypatch):
    db = MagicMock()
    db.count_telegram_subscribers.return_value = 3
    db.get_telegram_subscribers.side_effect = [
        ["u1", "u2", "u3"],
        [],
    ]
    bot = _make_bot(db=db)
    bot.send_message = AsyncMock(side_effect=["ok", "blocked", "ok"])
    bot._remove_subscriber = AsyncMock(return_value=True)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await bot.broadcast_message("digest")

    assert result == 2
    bot._remove_subscriber.assert_awaited_once_with("u2")


@pytest.mark.asyncio
async def test_broadcast_message_uses_in_memory_fallback(monkeypatch):
    bot = _make_bot(db=None)
    bot.subscribed_users = {"u1", "u2"}
    # Use a proper async function to avoid StopAsyncIteration exhaustion
    async def _mock_send(chat_id, text):
        return "ok"
    bot.send_message = AsyncMock(side_effect=_mock_send)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await bot.broadcast_message("digest")

    assert result == 2
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_handle_update_start_for_new_user_saves_settings_and_shows_menu():
    db = MagicMock()
    bot = _make_bot(db=db)
    bot._add_subscriber = AsyncMock(return_value=True)
    bot.send_message = AsyncMock(return_value="ok")

    await bot.handle_update({
        "message": {
            "from": {"id": 123, "first_name": "Ivan"},
            "chat": {"id": 555},
            "text": "/start",
        }
    })

    bot._add_subscriber.assert_awaited_once()
    db.upsert_user_settings.assert_called_once_with("123")
    assert bot.send_message.await_count == 3
    assert bot.send_message.await_args_list[0].args[:2] == (
        "555",
        "✅ Подписка включена! Вы будете получать уведомления о новых товарах!",
    )
    assert bot.send_message.await_args_list[1].args[0] == "999"
    assert "Новый пользователь" in bot.send_message.await_args_list[1].args[1]
    assert bot.send_message.await_args_list[2].args[:2] == ("555", "Выберите действие:")


@pytest.mark.asyncio
async def test_handle_update_stop_for_subscriber_removes_subscription():
    bot = _make_bot()
    bot.subscribed_users = {"123"}
    bot._remove_subscriber = AsyncMock(return_value=True)
    bot.send_message = AsyncMock(return_value="ok")

    await bot.handle_update({
        "message": {
            "from": {"id": 123},
            "chat": {"id": 555},
            "text": "/stop",
        }
    })

    bot._remove_subscriber.assert_awaited_once_with("123")
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_update_settings_requires_subscription():
    bot = _make_bot()
    bot.send_message = AsyncMock(return_value="ok")
    bot._handle_settings_command = AsyncMock()

    await bot.handle_update({
        "message": {
            "from": {"id": 123},
            "chat": {"id": 555},
            "text": "/settings",
        }
    })

    bot._handle_settings_command.assert_not_called()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_update_settings_dispatches_for_subscriber():
    bot = _make_bot()
    bot.subscribed_users = {"123"}
    bot._settings.handle_command = AsyncMock()

    await bot.handle_update({
        "message": {
            "from": {"id": 123},
            "chat": {"id": 555},
            "text": "/settings",
        }
    })

    bot._settings.handle_command.assert_awaited_once_with("123", "555", "/settings")


@pytest.mark.asyncio
async def test_handle_update_routes_callback_query():
    bot = _make_bot()
    bot._handle_callback_query = AsyncMock()

    update = {"callback_query": {"id": "cb1", "data": "x"}}
    await bot.handle_update(update)

    bot._handle_callback_query.assert_awaited_once_with(update["callback_query"])


@pytest.mark.asyncio
async def test_handle_update_ignores_message_without_text():
    bot = _make_bot()
    bot.send_message = AsyncMock(return_value="ok")

    await bot.handle_update({
        "message": {
            "from": {"id": 123},
            "chat": {"id": 555},
        }
    })

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_interval_input_rejects_invalid_number():
    parser_controller = MagicMock()
    parser_controller.set_interval = AsyncMock(return_value=True)
    bot = _make_bot(parser_controller=parser_controller)
    bot._waiting_for_interval.add("123")
    bot.send_message = AsyncMock(return_value="ok")

    await bot._handle_interval_input("123", "555", "abc")

    parser_controller.set_interval.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    assert "123" not in bot._waiting_for_interval


@pytest.mark.asyncio
async def test_handle_interval_input_sets_interval():
    parser_controller = MagicMock()
    parser_controller.set_interval = AsyncMock(return_value=True)
    bot = _make_bot(parser_controller=parser_controller)
    bot._waiting_for_interval.add("123")
    bot.send_message = AsyncMock(return_value="ok")

    await bot._handle_interval_input("123", "555", "1800")

    parser_controller.set_interval.assert_awaited_once_with(1800)
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_logs_sends_not_found_message(monkeypatch, tmp_path):
    bot = _make_bot()
    bot.send_message = AsyncMock(return_value="ok")
    monkeypatch.chdir(tmp_path)

    await bot._send_logs("555")

    bot.send_message.assert_awaited_once()
    assert "Логи не найдены" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_send_logs_splits_long_output(monkeypatch, tmp_path):
    bot = _make_bot()
    bot.send_message = AsyncMock(return_value="ok")
    monkeypatch.chdir(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    long_line = "<error>" * 900
    (log_dir / "app.log").write_text("\n".join([long_line] * 3), encoding="utf-8")

    await bot._send_logs("555")

    assert bot.send_message.await_count >= 2
    assert all(call_item.args[1].startswith("<pre>") for call_item in bot.send_message.await_args_list)
