"""Тесты валидации пользовательского ввода в Telegram боте."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from services.telegram_bot.core import TelegramBot


class TestTelegramInputValidation:
    """Тесты валидации пользовательского ввода."""

    @pytest.fixture
    def bot(self):
        """Создает экземпляр бота для тестов."""
        bot = TelegramBot()
        bot.send_message = AsyncMock()
        return bot

    @pytest.mark.asyncio
    async def test_validate_normal_input(self, bot):
        """Тест валидации обычного текста."""
        result = await bot._validate_user_input("Привет, как дела?", "123")
        assert result is True
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_empty_input(self, bot):
        """Тест валидации пустого ввода."""
        result = await bot._validate_user_input("   ", "123")
        assert result is False
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_too_long_input(self, bot):
        """Тест валидации слишком длинного сообщения."""
        long_text = "a" * 5000  # Больше лимита в 4096 символов
        result = await bot._validate_user_input(long_text, "123")
        assert result is False
        bot.send_message.assert_called_once_with(
            "123",
            "❌ Сообщение слишком длинное. Максимальная длина: 4096 символов."
        )

    @pytest.mark.asyncio
    async def test_validate_suspicious_script_tag(self, bot):
        """Тест валидации подозрительного содержимого с script тегом."""
        suspicious_text = "Привет <script>alert('xss')</script>"
        result = await bot._validate_user_input(suspicious_text, "123")
        assert result is False
        bot.send_message.assert_called_once_with(
            "123",
            "❌ Сообщение содержит недопустимые символы."
        )

    @pytest.mark.asyncio
    async def test_validate_suspicious_javascript(self, bot):
        """Тест валидации подозрительного содержимого с javascript."""
        suspicious_text = "javascript:alert('test')"
        result = await bot._validate_user_input(suspicious_text, "123")
        assert result is False
        bot.send_message.assert_called_once_with(
            "123",
            "❌ Сообщение содержит недопустимые символы."
        )

    @pytest.mark.asyncio
    async def test_validate_spam_like_input(self, bot):
        """Тест валидации спам-подобного ввода."""
        spam_text = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # 55 одинаковых символов
        result = await bot._validate_user_input(spam_text, "123")
        assert result is False
        bot.send_message.assert_called_once_with(
            "123",
            "❌ Сообщение выглядит как спам."
        )

    @pytest.mark.asyncio
    async def test_validate_short_repetitive_input_allowed(self, bot):
        """Тест что короткие повторяющиеся сообщения разрешены."""
        short_repetitive = "aaaa"  # Короткое, не считается спамом
        result = await bot._validate_user_input(short_repetitive, "123")
        assert result is True
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_command_input(self, bot):
        """Тест валидации команд бота."""
        result = await bot._validate_user_input("/start", "123")
        assert result is True
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_search_query(self, bot):
        """Тест валидации поискового запроса."""
        result = await bot._validate_user_input("видеокарта RTX", "123")
        assert result is True
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_case_insensitive_suspicious_content(self, bot):
        """Тест что проверка подозрительного содержимого не зависит от регистра."""
        suspicious_text = "JAVASCRIPT:ALERT('TEST')"
        result = await bot._validate_user_input(suspicious_text, "123")
        assert result is False
        bot.send_message.assert_called_once_with(
            "123",
            "❌ Сообщение содержит недопустимые символы."
        )