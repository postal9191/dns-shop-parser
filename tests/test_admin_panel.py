"""
Тесты для админ-панели и callback обработчиков.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from services.admin_panel import ParserController, ParserState


class TestParserController:
    """Тесты парсера контроллер."""

    def test_parser_state_initial(self):
        """Проверяет начальное состояние ParserState."""
        state = ParserState()
        assert state.is_running is False
        assert state.is_paused is False
        assert state.current_interval == 3600
        assert state.iteration_count == 0

    def test_parser_controller_init(self):
        """Проверяет инициализацию контроллера."""
        controller = ParserController()
        assert controller.state.is_running is False
        assert controller.state.is_paused is False

    @pytest.mark.asyncio
    async def test_parser_start(self):
        """Проверяет запуск парсера."""
        controller = ParserController()

        result = await controller.start()
        assert result is True
        assert controller.state.is_running is True
        assert controller.state.is_paused is False
        assert isinstance(controller.state.last_start_time, datetime)

    @pytest.mark.asyncio
    async def test_parser_start_twice_returns_false(self):
        """Повторный запуск должен вернуть False."""
        controller = ParserController()

        await controller.start()
        result = await controller.start()

        assert result is False

    @pytest.mark.asyncio
    async def test_parser_stop(self):
        """Проверяет остановку парсера."""
        controller = ParserController()
        await controller.start()

        result = await controller.stop()
        assert result is True
        assert controller.state.is_running is False
        assert controller._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_parser_stop_not_running_returns_false(self):
        """Остановка неработающего парсера должна вернуть False."""
        controller = ParserController()

        result = await controller.stop()
        assert result is False

    @pytest.mark.asyncio
    async def test_parser_restart(self):
        """Проверяет перезапуск парсера."""
        controller = ParserController()

        result = await controller.restart()
        assert result is True
        assert controller.state.is_running is True

    @pytest.mark.asyncio
    async def test_parser_pause(self):
        """Проверяет паузу парсера."""
        controller = ParserController()
        await controller.start()

        result = await controller.pause()
        assert result is True
        assert controller.state.is_paused is True
        assert controller._pause_event.is_set()

    @pytest.mark.asyncio
    async def test_parser_pause_not_running_returns_false(self):
        """Пауза неработающего парсера должна вернуть False."""
        controller = ParserController()

        result = await controller.pause()
        assert result is False

    @pytest.mark.asyncio
    async def test_parser_resume(self):
        """Проверяет возобновление парсера."""
        controller = ParserController()
        await controller.start()
        await controller.pause()

        result = await controller.resume()
        assert result is True
        assert controller.state.is_paused is False
        assert not controller._pause_event.is_set()

    @pytest.mark.asyncio
    async def test_parser_set_interval(self):
        """Проверяет установку интервала."""
        controller = ParserController()

        result = await controller.set_interval(1800)
        assert result is True
        assert controller.state.current_interval == 1800
        assert controller._pending_interval == 1800
        assert controller._interval_changed_event.is_set()

    @pytest.mark.asyncio
    async def test_parser_set_interval_zero_returns_false(self):
        """Интервал 0 должен вернуть False."""
        controller = ParserController()

        result = await controller.set_interval(0)
        assert result is False

    @pytest.mark.asyncio
    async def test_parser_set_interval_negative_returns_false(self):
        """Отрицательный интервал должен вернуть False."""
        controller = ParserController()

        result = await controller.set_interval(-100)
        assert result is False

    def test_should_stop(self):
        """Проверяет проверку остановки."""
        controller = ParserController()

        assert controller.should_stop() is False
        controller._stop_event.set()
        assert controller.should_stop() is True

    @pytest.mark.asyncio
    async def test_get_pending_interval(self):
        """Проверяет получение ожидающего интервала."""
        controller = ParserController()

        assert controller.get_pending_interval() is None

        await controller.set_interval(2400)

        interval = controller.get_pending_interval()
        assert interval == 2400

        assert controller.get_pending_interval() is None

    def test_get_status(self):
        """Проверяет получение статуса."""
        controller = ParserController()

        status = controller.get_status()
        assert isinstance(status, str)
        assert "Остановлен" in status or "статус" in status.lower()

    @pytest.mark.asyncio
    async def test_get_status_running(self):
        """Проверяет статус работающего парсера."""
        controller = ParserController()
        await controller.start()

        status = controller.get_status()
        assert "Работает" in status or "работа" in status.lower()


class TestCallbackHandling:
    """Тесты для обработки callback запросов."""

    @pytest.mark.asyncio
    async def test_callback_with_valid_admin_id(self):
        """Проверяет обработку callback с корректным admin_id."""
        from services.telegram_bot import TelegramBot

        bot = TelegramBot(parser_controller=ParserController())
        bot.admin_id = "123456"

        callback_query = {
            "id": "callback_1",
            "from": {"id": 123456},
            "message": {"chat": {"id": 789}},
            "data": "admin_start"
        }

        # Мокируем методы
        bot._answer_callback = AsyncMock(return_value=True)

        await bot._handle_callback_query(callback_query)

        # Проверяем что callback был обработан
        assert bot._answer_callback.called

    @pytest.mark.asyncio
    async def test_callback_with_wrong_admin_id(self):
        """Проверяет обработку callback с неправильным admin_id."""
        from services.telegram_bot import TelegramBot

        bot = TelegramBot(parser_controller=ParserController())
        bot.admin_id = "999999"  # Другой admin_id

        callback_query = {
            "id": "callback_1",
            "from": {"id": 123456},
            "message": {"chat": {"id": 789}},
            "data": "admin_start"
        }

        bot._answer_callback = AsyncMock(return_value=True)

        await bot._handle_callback_query(callback_query)

        # Проверяем что был отправлен отказ в доступе
        bot._answer_callback.assert_called()
        call_args = bot._answer_callback.call_args
        assert "Нет доступа" in str(call_args)

    @pytest.mark.asyncio
    async def test_callback_without_parser_controller(self):
        """Проверяет обработку callback без parser_controller."""
        from services.telegram_bot import TelegramBot

        bot = TelegramBot(parser_controller=None)
        bot.admin_id = "123456"

        callback_query = {
            "id": "callback_1",
            "from": {"id": 123456},
            "message": {"chat": {"id": 789}},
            "data": "admin_start"
        }

        bot._answer_callback = AsyncMock(return_value=True)

        await bot._handle_callback_query(callback_query)

        # Проверяем что была ошибка
        bot._answer_callback.assert_called()
        call_args = bot._answer_callback.call_args
        assert "контроллер" in str(call_args).lower() or "ошибка" in str(call_args).lower()
