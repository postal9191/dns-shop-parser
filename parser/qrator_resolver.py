"""
Получение qrator_jsid2 (и сопутствующих кук dns-shop.ru) через Node.js + Playwright.

Chromium сохраняет профиль с куками в ~/.dns-parser-chromium/ между запусками.
На 2м+ цикле браузер загружает сессию с диска — Qrator видит живые куки и не требует challenge.
Если куки протухли — сайт сам их обновляет, мы забираем свежие.
"""

import asyncio
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path

from utils.logger import logger


_COOKIES_PATTERN = re.compile(
    r"__QRATOR_COOKIES__\s*\n(.*?)\n__END_COOKIES__",
    re.DOTALL,
)


def get_solve_script_path() -> Path:
    return Path(__file__).parent.parent / "solve_qrator.js"


def cleanup_chromium_profile() -> None:
    """Очищает Chromium profile если он стал невалидным (протухшие куки, грязная кеш)."""
    profile_dir = Path.home() / '.dns-parser-chromium'
    if profile_dir.exists():
        try:
            logger.warning("[QRATOR] Очищаю Chromium profile: %s", profile_dir)
            shutil.rmtree(profile_dir)
            logger.info("[QRATOR] ✓ Profile очищена")
        except Exception as e:
            logger.error("[QRATOR] Ошибка при очистке profile: %s", e)
    else:
        logger.debug("[QRATOR] Profile не существует: %s", profile_dir)


def _find_node_executable() -> str | None:
    node_exe = shutil.which("node")
    if node_exe:
        logger.debug("[QRATOR] Найден node: %s", node_exe)
        return node_exe

    alternative_paths = [
        "C:\\Program Files\\nodejs\\node.exe",
        "C:\\Program Files (x86)\\nodejs\\node.exe",
    ]
    for path in alternative_paths:
        if Path(path).exists():
            logger.debug("[QRATOR] Найден node по альтернативному пути: %s", path)
            return path

    logger.error("[QRATOR] Node.js не найден в PATH и стандартных местах")
    return None


def check_node_health() -> bool:
    """Проверяет доступность Node.js запуском `node --version`."""
    node_exe = _find_node_executable()
    if not node_exe:
        return False
    try:
        result = subprocess.run(
            [node_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("[QRATOR] Node.js доступен: %s", result.stdout.strip())
            return True
        logger.error("[QRATOR] node --version вернул код %d", result.returncode)
        return False
    except Exception as exc:
        logger.error("[QRATOR] Ошибка при проверке Node.js: %s", exc)
        return False


async def _retry_qrator(retry_count: int, max_retries: int) -> bool:
    """Логирует и выполняет ожидание перед повтором. Возвращает True если нужен retry."""
    if retry_count < max_retries - 1:
        wait_time = (2 ** retry_count) + random.uniform(0, 1)
        logger.info("[QRATOR] Жду %.1f сек перед повтором...", wait_time)
        await asyncio.sleep(wait_time)
        return True
    return False


async def resolve_qrator_cookies(user_agent: str | None = None, retry_count: int = 0) -> dict[str, str] | None:
    """
    Запускает solve_qrator.js с retry логикой. До 3 попыток с экспоненциальной задержкой.

    ВАЖНО про user_agent: параметр принимается, но в Node НЕ передаётся.
    Причина — Chromium на каждой ОС шлёт свои client hints
    (sec-ch-ua-platform, navigator.platform и т.д.). Если подставить чужой UA,
    Qrator ловит рассинхрон fingerprint и отдаёт 403 на /__qrator/validate.
    Поэтому Node сам подбирает UA под свою реальную ОС — это рабочая схема.

    Возвращает: {'qrator_jsid2': ..., 'PHPSESSID': ..., '_csrf': ..., ...}
                или None при ошибке.
    """
    # На первой попытке ПЕРЕИСПОЛЬЗУЕМ сохранённый профиль Chromium.
    # В нём живут qrator_ssid2 (до 30 дней) и qrator_jsid2 — Qrator видит
    # "vetted visitor" и пропускает challenge либо даёт тривиальный.
    # Чистим только на retry: значит, сохранённая сессия протухла, пробуем как новый визитор.
    if retry_count > 0:
        logger.info("[QRATOR] Retry: чищу профиль и пробую как новый визитор")
        cleanup_chromium_profile()

    max_retries = 3
    script_path = get_solve_script_path()
    if not script_path.exists():
        logger.error("[QRATOR] solve_qrator.js не найден: %s", script_path)
        return None

    node_exe = _find_node_executable()
    if not node_exe:
        logger.error("[QRATOR] Невозможно запустить Node.js (node не найден в PATH)")
        logger.info("[QRATOR] Установите Node.js: https://nodejs.org/")
        return None

    env = os.environ.copy()
    env.setdefault("QRATOR_TARGET", "https://www.dns-shop.ru/catalog/markdown/")

    try:
        attempt_label = f"попытка {retry_count + 1}/{max_retries}" if retry_count > 0 else ""
        logger.debug("[QRATOR] Запускаю: %s %s %s(UA — авто по ОС Node)",
                     node_exe, script_path, attempt_label)

        result = await asyncio.to_thread(
            subprocess.run,
            [node_exe, str(script_path)],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )

        output = result.stdout + result.stderr
        logger.debug("[QRATOR] Return code: %d", result.returncode)

        if result.returncode != 0:
            logger.warning("[QRATOR] solve_qrator.js завершился с кодом %d", result.returncode)
            logger.debug("[QRATOR] Stderr (конец): %s", result.stderr[-4000:])

            if await _retry_qrator(retry_count, max_retries):
                return await resolve_qrator_cookies(user_agent, retry_count + 1)
            else:
                logger.error("[QRATOR] ❌ Qrator не решился после %d попыток", max_retries)
                return None

        match = _COOKIES_PATTERN.search(output)
        if match:
            cookies_json = match.group(1).strip()
            cookies = json.loads(cookies_json)
            jsid2 = cookies.get("qrator_jsid2", "")
            logger.info(
                "[QRATOR] ✅ Qrator решён, импортировано кук: %d (jsid2=%s...)",
                len(cookies), jsid2[:16] if jsid2 else "(нет)",
            )
            return cookies

        logger.error("[QRATOR] Куки не найдены в выводе solve_qrator.js")
        logger.debug("[QRATOR] Stderr (конец): %s", result.stderr[-4000:])

        if await _retry_qrator(retry_count, max_retries):
            return await resolve_qrator_cookies(user_agent, retry_count + 1)
        return None

    except subprocess.TimeoutExpired:
        logger.error("[QRATOR] solve_qrator.js timeout (300 сек)")
        logger.info("[QRATOR] Проверь: npx playwright install chromium")
        return None
    except Exception as exc:
        logger.error("[QRATOR] Ошибка при запуске solve_qrator.js: %s", exc)
        logger.debug("[QRATOR] Полная ошибка:", exc_info=True)
        return None
