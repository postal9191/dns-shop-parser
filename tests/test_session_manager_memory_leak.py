"""
Тесты для проверки исправления утечки памяти в SessionManager.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import aiohttp

from dns_shop_parser.parser.session_manager import SessionManager


class TestSessionManagerMemoryLeak:
    """Тесты для проверки корректного закрытия connector'ов при исключениях."""

    @pytest.mark.asyncio
    async def test_get_session_closes_connector_on_exception(self):
        """Проверяет, что connector закрывается при исключении в get_session()."""
        session_manager = SessionManager("moscow")
        session_manager._initialized = True  # Пропускаем инициализацию

        # Мокаем TCPConnector
        mock_connector = AsyncMock()
        mock_connector.close = AsyncMock()

        # Мокаем ClientSession, чтобы он выбрасывал исключение
        with patch('aiohttp.TCPConnector', return_value=mock_connector), \
             patch('aiohttp.ClientSession', side_effect=RuntimeError("Test exception")):

            with pytest.raises(RuntimeError, match="Test exception"):
                await session_manager.get_session()

            # Проверяем, что connector.close() был вызван
            mock_connector.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_success_does_not_close_connector(self):
        """Проверяет, что при успешном создании сессии connector не закрывается."""
        session_manager = SessionManager("moscow")
        session_manager._initialized = True

        mock_connector = AsyncMock()
        mock_connector.close = AsyncMock()
        mock_session = AsyncMock()

        with patch('aiohttp.TCPConnector', return_value=mock_connector), \
             patch('aiohttp.ClientSession', return_value=mock_session):

            result = await session_manager.get_session()

            # Проверяем, что сессия создана
            assert result == mock_session
            # Проверяем, что connector НЕ закрывался
            mock_connector.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_sets_session_to_none(self):
        """Проверяет, что close() устанавливает _session в None."""
        session_manager = SessionManager("moscow")

        # Создаем мок сессии
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()

        session_manager._session = mock_session

        await session_manager.close()

        # Проверяем, что сессия закрыта и обнулена
        mock_session.close.assert_called_once()
        assert session_manager._session is None

    @pytest.mark.asyncio
    async def test_close_handles_already_closed_session(self):
        """Проверяет, что close() корректно обрабатывает уже закрытую сессию."""
        session_manager = SessionManager("moscow")

        mock_session = AsyncMock()
        mock_session.closed = True  # Уже закрыта
        mock_session.close = AsyncMock()

        session_manager._session = mock_session

        await session_manager.close()

        # close() не должен вызываться для уже закрытой сессии
        mock_session.close.assert_not_called()
        assert session_manager._session is None

    @pytest.mark.asyncio
    async def test_close_handles_none_session(self):
        """Проверяет, что close() корректно обрабатывает None сессию."""
        session_manager = SessionManager("moscow")
        session_manager._session = None

        # Не должно выбрасывать исключение
        await session_manager.close()

        assert session_manager._session is None