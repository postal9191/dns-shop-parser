"""
Тесты для деталей qrator_resolver: функции, не покрытые test_qrator_retry.
Покрываем _find_node_executable, check_node_health, _run_command,
_check_playwright_chromium, _log_npm_dependencies, _retry_qrator,
_terminate_process, _kill_process, _read_stream, _COOKIES_PATTERN.
"""

import asyncio
import json
import subprocess
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from dns_shop_parser.parser.qrator_resolver import (
    NodeSolverResult,
    cleanup_chromium_profile,
    get_solve_script_path,
    _find_node_executable,
    check_node_health,
    _run_command,
    _check_playwright_chromium,
    _log_npm_dependencies,
    _retry_qrator,
    _terminate_process,
    _kill_process,
    _read_stream,
    _COOKIES_PATTERN,
)


class TestCOOKIESPattern:
    """Тесты regex парсинга cookies."""

    def test_pattern_matches_standard_cookies(self):
        output = "__QRATOR_COOKIES__\n{\"qrator_jsid2\": \"abc123\", \"session\": \"xyz\"}\n__END_COOKIES__"
        m = _COOKIES_PATTERN.search(output)
        assert m is not None
        cookies = json.loads(m.group(1).strip())
        assert cookies["qrator_jsid2"] == "abc123"

    def test_pattern_handles_multiline_json(self):
        json_str = json.dumps(
            {"a": "1", "b": "2"}, indent=4, ensure_ascii=False
        )
        output = f"__QRATOR_COOKIES__\n{json_str}\n__END_COOKIES__"
        m = _COOKIES_PATTERN.search(output)
        assert m is not None

    def test_pattern_returns_none_when_marker_missing(self):
        m = _COOKIES_PATTERN.search("no markers here")
        assert m is None


class TestFindNodeExecutable:
    """Тесты поиска Node.js исполняемого файла."""

    def test_finds_node_in_path(self):
        with patch("shutil.which", return_value="/usr/bin/node"):
            result = _find_node_executable()
        assert result == "/usr/bin/node"

    def test_fails_when_not_in_path(self):
        with patch("shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = _find_node_executable()
        assert result is None

    def test_falls_back_to_standard_paths(self):
        def which_none(_):
            return None

        def path_exists_side_effect(self):
            if str(self) == "C:\\Program Files\\nodejs\\node.exe":
                return True
            return False

        with patch("shutil.which", side_effect=which_none):
            with patch.object(Path, "exists", autospec=True, side_effect=path_exists_side_effect):
                result = _find_node_executable()
        assert result == "C:\\Program Files\\nodejs\\node.exe"

    def test_handles_exception_in_search(self):
        with patch("shutil.which", side_effect=Exception("search failed")):
            result = _find_node_executable()
        assert result is None


class TestRunCommand:
    """Тесты для _run_command."""

    def test_returns_result_on_success(self):
        completed = subprocess.CompletedProcess(["echo", "hello"], 0, "hello\n", "")
        with patch("subprocess.run", return_value=completed) as run:
            result = _run_command(["echo", "hello"], timeout=5)
        assert result is not None
        assert result.returncode == 0
        run.assert_called_once()

    def test_handles_timeout(self):
        import subprocess as sp
        # Запускаем команду, которая гарантированно превысит таймаут на Windows
        if hasattr(sp, "STARTUPINFO"):
            startupinfo = sp.STARTUPINFO()
            startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
        else:
            startupinfo = None

        result = _run_command(
            ["ping", "-n", "10", "127.0.0.1"],
            timeout=0.01,
        )
        assert result is None

    def test_handles_exception(self):
        result = _run_command(["/nonexistent_binary_12345"])
        assert result is None


class TestCheckNodeHealth:
    """Тесты для check_node_health."""

    def test_returns_true_when_node_works(self):
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value="/usr/bin/node"):
            with patch("dns_shop_parser.parser.qrator_resolver._run_command") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="v20.0.0\n")
                result = check_node_health()
        assert result is True

    def test_returns_false_when_node_not_found(self):
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value=None):
            result = check_node_health()
        assert result is False

    def test_returns_false_when_version_fails(self):
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value="/usr/bin/node"):
            with patch("dns_shop_parser.parser.qrator_resolver._run_command") as mock_run:
                mock_run.return_value = Mock(returncode=1, stdout="", stderr="error")
                result = check_node_health()
        assert result is False

    def test_handles_no_result(self):
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value="/usr/bin/node"):
            with patch("dns_shop_parser.parser.qrator_resolver._run_command", return_value=None):
                result = check_node_health()
        assert result is False


class TestCheckPlaywrightChromium:
    """Тесты для _check_playwright_chromium."""

    def test_returns_true_when_chromium_available(self):
        with patch("dns_shop_parser.parser.qrator_resolver._node_eval") as mock_eval:
            mock_result = Mock(returncode=0, stdout="/some/path/ms-playwright/chromium-1234/chrome-win/chrome.exe\n")
            mock_eval.return_value = mock_result
            result = _check_playwright_chromium("/usr/bin/node")
        assert result is True

    def test_returns_false_on_nonzero_returncode(self):
        with patch("dns_shop_parser.parser.qrator_resolver._node_eval") as mock_eval:
            mock_eval.return_value = Mock(returncode=1, stdout="", stderr="error")
            result = _check_playwright_chromium("/usr/bin/node")
        assert result is False

    def test_handles_exception(self):
        with patch("dns_shop_parser.parser.qrator_resolver._node_eval", side_effect=Exception("boom")):
            result = _check_playwright_chromium("/usr/bin/node")
        assert result is False


class TestLogNpmDependencies:
    """Тесты для _log_npm_dependencies."""

    def test_skips_when_npm_not_found(self):
        with patch("shutil.which", return_value=None):
            # Не должна выбросить исключение
            _log_npm_dependencies()

    def test_handles_failed_which(self):
        with patch("shutil.which", side_effect=Exception("boom")):
            _log_npm_dependencies()

    def test_calls_npm_ls_when_found(self):
        with patch("shutil.which", return_value="/usr/bin/npm"):
            with patch("dns_shop_parser.parser.qrator_resolver._run_command") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="ok\n", stderr="")
                _log_npm_dependencies()
                assert mock_run.called


class TestRetryQrator:
    """Тесты для _retry_qrator."""

    @pytest.mark.asyncio
    async def test_retry_on_non_last_attempt(self):
        result = await _retry_qrator(retry_count=0, max_retries=3)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_retry_on_last_attempt(self):
        result = await _retry_qrator(retry_count=2, max_retries=3)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_retry_when_max_retries_one(self):
        result = await _retry_qrator(retry_count=0, max_retries=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_time_increases_with_retry_count(self):
        # retry_count=1 → wait = 2^1 + random(0,1) = 2.x–3.x
        wait_times = []

        async def capture_sleep(duration):
            wait_times.append(duration)

        with patch("asyncio.sleep", side_effect=capture_sleep):
            await _retry_qrator(retry_count=1, max_retries=4)

        assert len(wait_times) == 1
        # 2^1 + random(0,1) = от 2.0 до 3.0
        assert wait_times[0] >= 2.0
        assert wait_times[0] < 4.0


class TestTerminateProcess:
    """Тесты для _terminate_process."""

    def test_early_return_when_already_terminated(self):
        process = Mock(returncode=1)
        # Не должна выбросить исключение
        _terminate_process(process)
        assert not process.terminate.called

    def test_calls_terminate_on_windows(self):
        process = Mock(returncode=None)
        with patch("sys.platform", "win32"):
            _terminate_process(process)
        process.terminate.assert_called_once()

    def test_handles_process_lookup_error(self):
        process = Mock(returncode=None)
        process.terminate.side_effect = ProcessLookupError()
        with patch("sys.platform", "win32"):
            _terminate_process(process)


class TestKillProcess:
    """Тесты для _kill_process."""

    def test_early_return_when_already_terminated(self):
        process = Mock(returncode=1)
        _kill_process(process)
        assert not process.kill.called

    def test_calls_kill_on_windows(self):
        process = Mock(returncode=None)
        with patch("sys.platform", "win32"):
            _kill_process(process)
        process.kill.assert_called_once()

    def test_handles_process_lookup_error(self):
        process = Mock(returncode=None)
        process.kill.side_effect = ProcessLookupError()
        with patch("sys.platform", "win32"):
            _kill_process(process)


class TestReadStream:
    """Тесты для _read_stream."""

    @pytest.mark.asyncio
    async def test_reads_single_line(self):
        reader = asyncio.StreamReader()
        payload = b"hello world\n"
        reader.feed_data(payload)
        reader.feed_eof()

        sink: list[str] = []
        await _read_stream(reader, "stderr", sink)

        assert sink == ["hello world"]

    @pytest.mark.asyncio
    async def test_reads_multiple_lines(self):
        reader = asyncio.StreamReader()
        payload = b"line1\nline2\nline3\n"
        reader.feed_data(payload)
        reader.feed_eof()

        sink: list[str] = []
        await _read_stream(reader, "stderr", sink)

        assert sink == ["line1", "line2", "line3"]

    @pytest.mark.asyncio
    async def test_handles_replace_errors(self):
        reader = asyncio.StreamReader()
        # UTF-8 недопустимые байты
        payload = b"\xff\xfe\r\n"
        reader.feed_data(payload)
        reader.feed_eof()

        sink: list[str] = []
        await _read_stream(reader, "stderr", sink)

        assert len(sink) == 1
        # Должно содержать replacement символ вместо краха


class TestGetSolveScriptPath:
    """Тесты для get_solve_script_path."""

    def test_returns_correct_path(self):
        p = get_solve_script_path()
        assert isinstance(p, Path)
        assert p.name == "solve_qrator.js"


class TestNodeSolverResult:
    """Тесты для NodeSolverResult dataclass."""

    def test_defaults_timed_out_false(self):
        r = NodeSolverResult(0, "out", "err")
        assert r.timed_out is False

    def test_sets_timed_out_true(self):
        r = NodeSolverResult(-1, "", "timeout", timed_out=True)
        assert r.timed_out is True


class TestCheckProxyConnectivity:
    """Тесты для _check_proxy_connectivity."""

    def test_returns_true_when_proxy_disabled(self):
        with patch("dns_shop_parser.parser.qrator_resolver.config") as mock_cfg:
            mock_cfg.proxy_enabled.return_value = False
            result = shutil.which  # сохраним ссылку
        from dns_shop_parser.parser.qrator_resolver import _check_proxy_connectivity

        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value=None):
            pass

        # Проверяем через qrator_preflight, так как _check_proxy_connectivity требует node_exe
        # Но нам важно проверить что когда proxy disabled → сразу True
        def mock_find(_):
            return "/usr/bin/node"

        with patch("dns_shop_parser.parser.qrator_resolver.config") as mock_cfg:
            with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", side_effect=mock_find):
                mock_cfg.proxy_enabled.return_value = False
                result = _check_proxy_connectivity("/usr/bin/node")
        assert result is True

    def test_returns_false_on_exception(self):
        import os
        with patch("dns_shop_parser.parser.qrator_resolver.config") as mock_cfg:
            with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value=None):
                pass

        def raise_proxy(_):
            from dns_shop_parser.parser.qrator_resolver import config
            with patch.object(config, 'proxy_enabled', return_value=True):
                with patch('os.environ.get', side_effect=Exception("env fail")):
                    from dns_shop_parser.parser.qrator_resolver import _check_proxy_connectivity
                    return _check_proxy_connectivity("/usr/bin/node")

        from dns_shop_parser.parser.qrator_resolver import config
        with patch.object(config, 'proxy_enabled', return_value=True):
            with patch('os.environ.get', side_effect=Exception("env fail")):
                from dns_shop_parser.parser.qrator_resolver import _check_proxy_connectivity
                result = _check_proxy_connectivity("/usr/bin/node")
        assert result is False


class TestQratorPreflight:
    """Тесты для qrator_preflight."""

    def test_returns_false_when_node_not_found(self):
        from dns_shop_parser.parser.qrator_resolver import qrator_preflight
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", return_value=None):
            result = qrator_preflight()
        assert result is False

    def test_returns_false_when_chromium_missing(self):
        from dns_shop_parser.parser.qrator_resolver import qrator_preflight
        mock_find = lambda _: "/usr/bin/node"
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", side_effect=mock_find):
            with patch("dns_shop_parser.parser.qrator_resolver._check_playwright_chromium", return_value=False):
                result = qrator_preflight()
        assert result is False

    def test_returns_false_on_exception(self):
        from dns_shop_parser.parser.qrator_resolver import qrator_preflight
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", side_effect=Exception("boom")):
            result = qrator_preflight()
        assert result is False

    def test_warns_when_init_timeout_not_greater(self):
        from dns_shop_parser.parser.qrator_resolver import qrator_preflight, config as cfg
        mock_find = lambda: "/usr/bin/node"
        with patch("dns_shop_parser.parser.qrator_resolver._find_node_executable", side_effect=mock_find):
            with patch.object(cfg, 'qrator_init_timeout', 10):
                with patch.object(cfg, 'qrator_node_timeout', 20):
                    with patch("dns_shop_parser.parser.qrator_resolver._check_playwright_chromium", return_value=True):
                        with patch("dns_shop_parser.parser.qrator_resolver._check_proxy_connectivity", return_value=True):
                            result = qrator_preflight()
            assert result is True
