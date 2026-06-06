"""
Qrator cookie resolver via Node.js + Playwright.

The Python side owns process lifecycle and timeouts so a slow Qrator/proxy
attempt cannot leave a detached Node/Chromium process behind.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dns_shop_parser.config import config
from dns_shop_parser.utils.logger import logger


_COOKIES_PATTERN = re.compile(
    r"__QRATOR_COOKIES__\s*\n(.*?)\n__END_COOKIES__",
    re.DOTALL,
)


@dataclass
class NodeSolverResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def get_solve_script_path() -> Path:
    return Path(__file__).resolve().parents[3] / "solve_qrator.js"


def cleanup_chromium_profile() -> bool:
    """Remove the persistent Chromium profile used outside Linux."""
    profile_dir = Path.home() / ".dns-parser-chromium"
    if not profile_dir.exists():
        logger.debug("[QRATOR] Chromium profile does not exist: %s", profile_dir)
        return True

    try:
        logger.warning("[QRATOR] Cleaning Chromium profile: %s", profile_dir)
        shutil.rmtree(profile_dir)
        logger.info("[QRATOR] Chromium profile cleaned")
        return True
    except Exception as exc:
        logger.error("[QRATOR] Failed to clean Chromium profile: %s", exc)
        logger.debug("[QRATOR] Profile cleanup error details:", exc_info=True)
        return False


def _find_node_executable() -> str | None:
    """Find Node.js executable with consistent error handling."""
    try:
        node_exe = shutil.which("node")
        if node_exe:
            logger.debug("[QRATOR] node found in PATH: %s", node_exe)
            return node_exe

        alternative_paths = [
            "C:\\Program Files\\nodejs\\node.exe",
            "C:\\Program Files (x86)\\nodejs\\node.exe",
        ]
        for path in alternative_paths:
            if Path(path).exists():
                logger.debug("[QRATOR] node found at fallback path: %s", path)
                return path

        logger.error("[QRATOR] Node.js not found in PATH or standard locations")
        return None
    except Exception as exc:
        logger.error("[QRATOR] Error searching for Node.js executable: %s", exc)
        logger.debug("[QRATOR] Node search error details:", exc_info=True)
        return None


def _run_command(command: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str] | None:
    """Run subprocess command with consistent error handling."""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("[QRATOR] Command timeout after %.1fs: %s", timeout, " ".join(command))
        logger.debug("[QRATOR] Timeout error details:", exc_info=True)
        return None
    except Exception as exc:
        logger.error("[QRATOR] Command failed: %s (%s)", " ".join(command), exc)
        logger.debug("[QRATOR] Command error details:", exc_info=True)
        return None


def check_node_health() -> bool:
    """Check that Node.js starts and report the exact binary/version."""
    try:
        node_exe = _find_node_executable()
        if not node_exe:
            return False

        result = _run_command([node_exe, "--version"], timeout=10)
        if result and result.returncode == 0:
            logger.info("[QRATOR] Node.js available: %s (%s)", result.stdout.strip(), node_exe)
            return True

        code = result.returncode if result else "no-result"
        logger.error("[QRATOR] node --version failed: %s", code)
        if result and result.stderr:
            logger.debug("[QRATOR] Node health check stderr: %s", result.stderr)
        return False
    except Exception as exc:
        logger.error("[QRATOR] Node health check failed: %s", exc)
        logger.debug("[QRATOR] Node health check error details:", exc_info=True)
        return False


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _node_eval(node_exe: str, code: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str] | None:
    return _run_command([node_exe, "-e", code], timeout=timeout)


def _check_playwright_chromium(node_exe: str) -> bool:
    """Check Playwright Chromium availability with consistent error handling."""
    try:
        code = (
            "const fs=require('fs');"
            "const { chromium }=require('playwright-extra');"
            "const p=chromium.executablePath();"
            "console.log(p);"
            "if(!p || !fs.existsSync(p)) process.exit(2);"
        )
        result = _node_eval(node_exe, code, timeout=20)
        if result and result.returncode == 0:
            chromium_path = result.stdout.strip().splitlines()[-1]
            logger.info("[QRATOR] Playwright Chromium: %s", chromium_path)
            return True

        logger.error("[QRATOR] Playwright Chromium is not available")
        if result:
            logger.debug("[QRATOR] Chromium check stderr: %s", result.stderr[-4000:])
        logger.info("[QRATOR] Try: npx playwright install --with-deps chromium")
        return False
    except Exception as exc:
        logger.error("[QRATOR] Playwright Chromium check failed: %s", exc)
        logger.debug("[QRATOR] Chromium check error details:", exc_info=True)
        logger.info("[QRATOR] Try: npx playwright install --with-deps chromium")
        return False


def _log_npm_dependencies() -> None:
    """Log npm dependencies with consistent error handling."""
    try:
        npm = shutil.which("npm")
        if not npm:
            logger.warning("[QRATOR] npm not found; skipping dependency diagnostics")
            return

        result = _run_command([npm, "ls", "playwright", "playwright-extra", "--depth=0"], timeout=20)
        if not result:
            logger.warning("[QRATOR] npm dependency check failed to execute")
            return

        if result.returncode == 0:
            logger.info("[QRATOR] npm dependencies OK")
        else:
            logger.warning("[QRATOR] npm dependency check returned code %d", result.returncode)
        logger.debug("[QRATOR] npm ls stdout: %s", result.stdout[-4000:])
        logger.debug("[QRATOR] npm ls stderr: %s", result.stderr[-4000:])
    except Exception as exc:
        logger.error("[QRATOR] npm dependency check failed: %s", exc)
        logger.debug("[QRATOR] npm dependency error details:", exc_info=True)


def _check_proxy_connectivity(node_exe: str) -> bool:
    """Check proxy connectivity with consistent error handling."""
    try:
        if not config.proxy_enabled():
            logger.info("[QRATOR] Proxy disabled")
            return True

        logger.info("[QRATOR] Proxy enabled for Qrator: %s:%s", config.proxy_host, config.proxy_port)
        code = r"""
const { request } = require('http');
const target = 'www.dns-shop.ru:443';
const req = request({
  host: process.env.PROXY_HOST,
  port: Number(process.env.PROXY_PORT || 80),
  method: 'CONNECT',
  path: target,
  timeout: Number(process.env.QRATOR_PROXY_CHECK_TIMEOUT_MS || 20000),
  headers: process.env.PROXY_USER
    ? {'Proxy-Authorization': 'Basic ' + Buffer.from(process.env.PROXY_USER + ':' + (process.env.PROXY_PASSWORD || '')).toString('base64')}
    : undefined,
});
req.on('connect', (res, socket) => {
  console.log('CONNECT ' + res.statusCode);
  socket.destroy();
  process.exit(res.statusCode >= 200 && res.statusCode < 300 ? 0 : 2);
});
req.on('timeout', () => {
  console.error('proxy connect timeout');
  req.destroy();
  process.exit(3);
});
req.on('error', (err) => {
  console.error(err.message);
  process.exit(4);
});
req.end();
"""
        env_backup = os.environ.get("QRATOR_PROXY_CHECK_TIMEOUT_MS")
        os.environ["QRATOR_PROXY_CHECK_TIMEOUT_MS"] = str(int(config.qrator_proxy_check_timeout * 1000))

        try:
            result = _node_eval(node_exe, code, timeout=config.qrator_proxy_check_timeout + 5)
        finally:
            if env_backup is None:
                os.environ.pop("QRATOR_PROXY_CHECK_TIMEOUT_MS", None)
            else:
                os.environ["QRATOR_PROXY_CHECK_TIMEOUT_MS"] = env_backup

        if result and result.returncode == 0:
            logger.info("[QRATOR] Proxy CONNECT to dns-shop.ru is available")
            return True

        logger.error("[QRATOR] Proxy/network preflight failed; Qrator may be blocked or proxy is slow")
        if result:
            logger.debug("[QRATOR] Proxy check stdout: %s", result.stdout[-4000:])
            logger.debug("[QRATOR] Proxy check stderr: %s", result.stderr[-4000:])
        return False
    except Exception as exc:
        logger.error("[QRATOR] Proxy connectivity check failed: %s", exc)
        logger.debug("[QRATOR] Proxy check error details:", exc_info=True)
        return False


def qrator_preflight() -> bool:
    """Run cheap diagnostics before the expensive Qrator challenge."""
    try:
        node_exe = _find_node_executable()
        if not node_exe:
            return False

        logger.info(
            "[QRATOR] Timeouts: init=%.0fs node=%.0fs proxy-check=%.0fs",
            config.qrator_init_timeout,
            config.qrator_node_timeout,
            config.qrator_proxy_check_timeout,
        )
        if config.qrator_init_timeout <= config.qrator_node_timeout:
            logger.warning(
                "[QRATOR] QRATOR_INIT_TIMEOUT should be greater than QRATOR_NODE_TIMEOUT "
                "so Python does not cancel Node cleanup first"
            )

        _log_npm_dependencies()
        if not _check_playwright_chromium(node_exe):
            return False
        return _check_proxy_connectivity(node_exe)
    except Exception as exc:
        logger.error("[QRATOR] Preflight check failed: %s", exc)
        logger.debug("[QRATOR] Preflight error details:", exc_info=True)
        return False


async def _retry_qrator(retry_count: int, max_retries: int) -> bool:
    if retry_count < max_retries - 1:
        wait_time = (2**retry_count) + random.uniform(0, 1)
        logger.info("[QRATOR] Waiting %.1f sec before retry...", wait_time)
        await asyncio.sleep(wait_time)
        return True
    return False


async def _read_stream(stream: asyncio.StreamReader, label: str, sink: list[str]) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode("utf-8", errors="replace").rstrip()
        sink.append(text)
        if label == "stderr":
            logger.debug("[solve_qrator] %s", text)


def _terminate_process(process: asyncio.subprocess.Process) -> None:
    """Terminate process gracefully with consistent error handling."""
    if process.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        logger.debug("[QRATOR] Process already terminated")
        return
    except Exception as exc:
        logger.error("[QRATOR] Failed to terminate Node process gracefully: %s", exc)
        logger.debug("[QRATOR] Process termination error details:", exc_info=True)


def _kill_process(process: asyncio.subprocess.Process) -> None:
    """Kill process forcefully with consistent error handling."""
    if process.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        logger.debug("[QRATOR] Process already killed")
        return
    except Exception as exc:
        logger.error("[QRATOR] Failed to kill Node process: %s", exc)
        logger.debug("[QRATOR] Process kill error details:", exc_info=True)


async def _run_node_solver(
    node_exe: str,
    script_path: Path,
    env: dict[str, str],
    timeout: float,
) -> NodeSolverResult:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    preexec_fn = None if sys.platform == "win32" else os.setsid

    process = await asyncio.create_subprocess_exec(
        node_exe,
        str(script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(_project_root()),
        creationflags=creationflags,
        preexec_fn=preexec_fn,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    readers = [
        asyncio.create_task(_read_stream(process.stdout, "stdout", stdout_lines)),
        asyncio.create_task(_read_stream(process.stderr, "stderr", stderr_lines)),
    ]

    try:
        returncode = await asyncio.wait_for(process.wait(), timeout=timeout)
        await asyncio.gather(*readers, return_exceptions=True)
        return NodeSolverResult(returncode, "\n".join(stdout_lines), "\n".join(stderr_lines))
    except asyncio.TimeoutError:
        logger.error("[QRATOR] Qrator Node solver timeout (%.0f sec)", timeout)
        _terminate_process(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _kill_process(process)
            await process.wait()
        await asyncio.gather(*readers, return_exceptions=True)
        return NodeSolverResult(
            process.returncode if process.returncode is not None else -1,
            "\n".join(stdout_lines),
            "\n".join(stderr_lines),
            timed_out=True,
        )


async def resolve_qrator_cookies(user_agent: str | None = None, retry_count: int = 0) -> dict[str, str] | None:
    """Run solve_qrator.js with retry and return DNS/Qrator cookies."""
    try:
        if retry_count > 0:
            logger.info("[QRATOR] Retry: cleaning profile and trying as a new visitor")
            if not cleanup_chromium_profile():
                logger.warning("[QRATOR] Profile cleanup failed, continuing anyway")

        max_retries = 3
        script_path = get_solve_script_path()
        if not script_path.exists():
            logger.error("[QRATOR] solve_qrator.js not found: %s", script_path)
            return None

        node_exe = _find_node_executable()
        if not node_exe:
            logger.error("[QRATOR] Cannot start Node.js")
            return None

        env = os.environ.copy()
        env.setdefault("QRATOR_TARGET", "https://www.dns-shop.ru/catalog/markdown/")
        env.setdefault("QRATOR_NODE_TIMEOUT", str(int(config.qrator_node_timeout)))

        if config.proxy_enabled():
            env["PROXY_HOST"] = config.proxy_host
            env["PROXY_PORT"] = str(config.proxy_port)
            env["PROXY_USER"] = config.proxy_user
            env["PROXY_PASSWORD"] = config.proxy_password
            logger.info("[QRATOR] Proxy for Node enabled: %s:%s", config.proxy_host, config.proxy_port)

        attempt_label = f" attempt {retry_count + 1}/{max_retries}" if retry_count > 0 else ""
        logger.debug("[QRATOR] Starting: %s %s%s", node_exe, script_path, attempt_label)

        result = await _run_node_solver(
            node_exe,
            script_path,
            env,
            timeout=config.qrator_node_timeout,
        )

        output = result.stdout + "\n" + result.stderr
        logger.debug("[QRATOR] Node solver return code: %d", result.returncode)

        if result.timed_out:
            logger.error("[QRATOR] Node solver timed out")
            logger.info("[QRATOR] Check Linux deps: npx playwright install --with-deps chromium")
            return None

        if result.returncode != 0:
            if result.returncode == 2:
                logger.warning("[QRATOR] Qrator rejected challenge (validate 403 / qrerror/403)")
            else:
                logger.warning("[QRATOR] solve_qrator.js exited with code %d", result.returncode)
            logger.debug("[QRATOR] Node stderr tail: %s", result.stderr[-4000:])

            if await _retry_qrator(retry_count, max_retries):
                return await resolve_qrator_cookies(user_agent, retry_count + 1)
            logger.error("[QRATOR] Qrator was not solved after %d attempts", max_retries)
            return None

        match = _COOKIES_PATTERN.search(output)
        if match:
            try:
                cookies_json = match.group(1).strip()
                cookies = json.loads(cookies_json)
                jsid2 = cookies.get("qrator_jsid2", "")
                logger.info(
                    "[QRATOR] Qrator solved, imported cookies: %d (jsid2=%s...)",
                    len(cookies),
                    jsid2[:16] if jsid2 else "(missing)",
                )
                return cookies
            except json.JSONDecodeError as exc:
                logger.error("[QRATOR] Failed to parse cookies JSON: %s", exc)
                logger.debug("[QRATOR] Invalid JSON: %s", cookies_json[:500])
                return None

        logger.error("[QRATOR] Cookies marker not found in solve_qrator.js output")
        logger.debug("[QRATOR] Node stderr tail: %s", result.stderr[-4000:])

        if await _retry_qrator(retry_count, max_retries):
            return await resolve_qrator_cookies(user_agent, retry_count + 1)
        return None

    except Exception as exc:
        logger.error("[QRATOR] Failed to run solve_qrator.js: %s", exc)
        logger.debug("[QRATOR] Full error details:", exc_info=True)
        return None
