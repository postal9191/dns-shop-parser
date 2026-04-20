"""
Тесты для retry логики Qrator и очистки Chromium profile.
"""

import asyncio
import json
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from parser.qrator_resolver import resolve_qrator_cookies, cleanup_chromium_profile


class TestCleanupChromiumProfile:
    """Тесты функции очистки Chromium profile."""

    def test_cleanup_removes_existing_profile(self):
        """Проверяет что cleanup удаляет существующий профиль."""
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / '.dns-parser-chromium'
            profile_path.mkdir()
            (profile_path / 'test_file.txt').write_text('test')

            assert profile_path.exists()

            with patch('pathlib.Path.home', return_value=Path(temp_dir)):
                cleanup_chromium_profile()

            assert not profile_path.exists()

    def test_cleanup_handles_nonexistent_profile(self):
        """Cleanup не должен выбросить ошибку если профиля нет."""
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / '.dns-parser-chromium'

            assert not profile_path.exists()

            with patch('pathlib.Path.home', return_value=Path(temp_dir)):
                # Не должна выбросить исключение
                cleanup_chromium_profile()

            assert not profile_path.exists()

    def test_cleanup_handles_permission_error(self):
        """Cleanup должен обработать ошибку прав доступа."""
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / '.dns-parser-chromium'
            profile_path.mkdir()

            with patch('pathlib.Path.home', return_value=Path(temp_dir)):
                with patch('shutil.rmtree', side_effect=PermissionError("Access denied")):
                    # Не должна выбросить исключение
                    cleanup_chromium_profile()


class TestResolveQratorWithRetry:
    """Тесты retry логики resolve_qrator_cookies."""

    @pytest.mark.asyncio
    async def test_resolve_qrator_success_first_try(self):
        """Успешное решение Qrator с первой попытки."""
        cookies = {'qrator_jsid2': 'test_jsid2_value', 'PHPSESSID': 'test_session'}
        cookies_output = f"__QRATOR_COOKIES__\n{json.dumps(cookies)}\n__END_COOKIES__"

        with patch('parser.qrator_resolver._find_node_executable', return_value='/usr/bin/node'):
            with patch('parser.qrator_resolver.get_solve_script_path', return_value=Path('/fake/solve_qrator.js')):
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('subprocess.run') as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=0,
                            stdout=cookies_output,
                            stderr='',
                        )

                        result = await resolve_qrator_cookies()

                        assert result is not None
                        assert result['qrator_jsid2'] == 'test_jsid2_value'
                        assert result['PHPSESSID'] == 'test_session'
                        # Проверяем что run вызван ровно один раз
                        assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_resolve_qrator_retry_on_failure(self):
        """Повтор при ошибке (код 1) и успех со 2-й попытки."""
        cookies = {'qrator_jsid2': 'test_jsid2_value'}
        cookies_output = f"__QRATOR_COOKIES__\n{json.dumps(cookies)}\n__END_COOKIES__"

        with patch('parser.qrator_resolver._find_node_executable', return_value='/usr/bin/node'):
            with patch('parser.qrator_resolver.get_solve_script_path', return_value=Path('/fake/solve_qrator.js')):
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('subprocess.run') as mock_run:
                        # Первый раз ошибка, второй раз успех
                        mock_run.side_effect = [
                            MagicMock(returncode=1, stdout='', stderr='403 Forbidden'),
                            MagicMock(returncode=0, stdout=cookies_output, stderr=''),
                        ]

                        with patch('asyncio.sleep', new_callable=AsyncMock):
                            result = await resolve_qrator_cookies()

                        assert result is not None
                        assert result['qrator_jsid2'] == 'test_jsid2_value'
                        # Проверяем что было 2 попытки
                        assert mock_run.call_count == 2

    @pytest.mark.asyncio
    async def test_resolve_qrator_exhausts_retries(self):
        """После 3 неудачных попыток возвращает None."""
        with patch('parser.qrator_resolver._find_node_executable', return_value='/usr/bin/node'):
            with patch('parser.qrator_resolver.get_solve_script_path', return_value=Path('/fake/solve_qrator.js')):
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('subprocess.run') as mock_run:
                        # Все попытки падают
                        mock_run.return_value = MagicMock(
                            returncode=1,
                            stdout='',
                            stderr='403 Forbidden',
                        )

                        with patch('asyncio.sleep', new_callable=AsyncMock):
                            result = await resolve_qrator_cookies()

                        assert result is None
                        # Проверяем что было 3 попытки
                        assert mock_run.call_count == 3

    @pytest.mark.asyncio
    async def test_resolve_qrator_exponential_backoff(self):
        """Проверяет экспоненциальную задержку между попытками (1, 2, 4 сек)."""
        with patch('parser.qrator_resolver._find_node_executable', return_value='/usr/bin/node'):
            with patch('parser.qrator_resolver.get_solve_script_path', return_value=Path('/fake/solve_qrator.js')):
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('subprocess.run') as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=1,
                            stdout='',
                            stderr='error',
                        )

                        sleep_calls = []
                        async def mock_sleep(duration):
                            sleep_calls.append(duration)

                        with patch('asyncio.sleep', side_effect=mock_sleep):
                            result = await resolve_qrator_cookies()

                        assert result is None
                        # Проверяем что задержки были 1 и 2 сек (на 2-й и 3-й попытке)
                        assert sleep_calls == [1, 2]

    @pytest.mark.asyncio
    async def test_resolve_qrator_missing_script(self):
        """Возвращает None если скрипт не найден."""
        with patch('parser.qrator_resolver.get_solve_script_path', return_value=Path('/fake/solve_qrator.js')):
            with patch('pathlib.Path.exists', return_value=False):
                result = await resolve_qrator_cookies()

                assert result is None

    @pytest.mark.asyncio
    async def test_resolve_qrator_missing_node(self):
        """Возвращает None если Node.js не найден."""
        with patch('parser.qrator_resolver._find_node_executable', return_value=None):
            result = await resolve_qrator_cookies()

            assert result is None


class TestSessionInitWithRetryAndCleanup:
    """Тесты логики инициализации сессии с retry и очисткой profile."""

    @pytest.mark.asyncio
    async def test_init_session_success_first_try(self):
        """Успешная инициализация с первой попытки."""
        from parser.session_manager import SessionManager

        session_mgr = SessionManager()

        with patch.object(session_mgr, '_resolve_qrator', new_callable=AsyncMock, return_value=True):
            with patch.object(session_mgr, '_fetch_base_cookies', new_callable=AsyncMock, return_value=True):
                result = await session_mgr._init_session()

                assert result is True
                assert session_mgr._initialized is True

    @pytest.mark.asyncio
    async def test_init_session_qrator_fails_first_try_succeeds_second(self):
        """При ошибке Qrator очищает profile и повторяет, со 2-й раз успех."""
        from parser.session_manager import SessionManager

        session_mgr = SessionManager()
        resolve_count = 0

        async def mock_resolve():
            nonlocal resolve_count
            resolve_count += 1
            # Первый раз False, второй раз True
            return resolve_count > 1

        with patch.object(session_mgr, '_resolve_qrator', side_effect=mock_resolve):
            with patch.object(session_mgr, '_fetch_base_cookies', new_callable=AsyncMock, return_value=True):
                with patch('parser.session_manager.cleanup_chromium_profile') as mock_cleanup:
                    with patch('asyncio.sleep', new_callable=AsyncMock):
                        result = await session_mgr._init_session()

                        assert result is True
                        # Проверяем что cleanup был вызван один раз
                        assert mock_cleanup.call_count == 1
                        # Проверяем что resolve был вызван дважды
                        assert resolve_count == 2

    @pytest.mark.asyncio
    async def test_init_session_qrator_fails_twice_returns_false(self):
        """При двух неудачах Qrator возвращает False и не инициализирует."""
        from parser.session_manager import SessionManager

        session_mgr = SessionManager()

        with patch.object(session_mgr, '_resolve_qrator', new_callable=AsyncMock, return_value=False):
            with patch('parser.session_manager.cleanup_chromium_profile') as mock_cleanup:
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    result = await session_mgr._init_session()

                    assert result is False
                    assert session_mgr._initialized is False
                    # Cleanup должен быть вызван один раз (при первой ошибке)
                    assert mock_cleanup.call_count == 1
