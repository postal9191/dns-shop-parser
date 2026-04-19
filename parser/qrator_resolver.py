"""
Получение qrator_jsid2 куки через Node.js скрипт solve_qrator.js.

Используется как fallback когда логин + HTTP недостаточно
для получения jsid2 куки.
"""

import asyncio
import json
import re
import subprocess
import shutil
import time
from pathlib import Path

from utils.logger import logger


_COOKIES_PATTERN = re.compile(
    r"__QRATOR_COOKIES__\s*\n(.*?)\n__END_COOKIES__",
    re.DOTALL,
)

_CACHE_FILE = Path(__file__).parent.parent / ".qrator_cache.json"
# Куки qrator_jsid2 живут ~15 мин. Кешируем на 13 мин с запасом.
_CACHE_TTL = 800


def _load_cached_cookies() -> dict[str, str] | None:
    """Загружает кешированные Qrator куки если они ещё свежие (< 13 мин)."""
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text())
        age = int(time.time() - data.get("ts", 0))
        if age < _CACHE_TTL:
            logger.debug("[QRATOR] Используем кешированную qrator_jsid2 (возраст: %ds)", age)
            return data.get("cookies")
        logger.debug("[QRATOR] Кеш устарел (%ds > %ds), решаем заново", age, _CACHE_TTL)
    except Exception:
        pass
    return None


def _save_cached_cookies(cookies: dict[str, str]) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps({"ts": time.time(), "cookies": cookies}))
        logger.debug("[QRATOR] Qrator куки сохранены в кеш")
    except Exception as exc:
        logger.warning("[QRATOR] Не удалось сохранить кеш: %s", exc)


def get_solve_script_path() -> Path:
    """Возвращает путь к solve_qrator.js."""
    return Path(__file__).parent.parent / "solve_qrator.js"


def _find_node_executable() -> str | None:
    """Пытается найти исполняемый файл node."""
    # Сначала пробуем стандартный путь
    node_exe = shutil.which("node")
    if node_exe:
        logger.debug("[QRATOR] Найден node: %s", node_exe)
        return node_exe

    # Fallback для Windows
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


async def resolve_qrator_cookies(force: bool = False) -> dict[str, str] | None:
    """
    Запускает solve_qrator.js и получает qrator_jsid2.
    force=True — принудительно пропускает кеш и решает заново.
    """
    if not force:
        cached = _load_cached_cookies()
        if cached:
            return cached
    elif _CACHE_FILE.exists():
        _CACHE_FILE.unlink(missing_ok=True)

    script_path = get_solve_script_path()
    if not script_path.exists():
        logger.error("[QRATOR] solve_qrator.js не найден: %s", script_path)
        return None

    # Находим node исполняемый файл
    node_exe = _find_node_executable()
    if not node_exe:
        logger.error("[QRATOR] Невозможно запустить Node.js (node не найден в PATH)")
        logger.info("[QRATOR] Убедись что Node.js установлен: https://nodejs.org/")
        return None

    try:
        logger.debug("[QRATOR] Запускаю: %s %s", node_exe, script_path)
        result = await asyncio.to_thread(
            subprocess.run,
            [node_exe, str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr
        logger.debug("[QRATOR] Return code: %d", result.returncode)

        if result.returncode != 0:
            logger.warning("[QRATOR] Node.js скрипт завершился с ошибкой %d", result.returncode)
            logger.debug("[QRATOR] Stderr: %s", result.stderr[:500])

        logger.debug("[QRATOR] Вывод (последние 200 символов): %s", output[-200:] if output else "(пусто)")

        # Парсим JSON из вывода
        match = _COOKIES_PATTERN.search(output)
        if match:
            cookies_json = match.group(1).strip()
            cookies = json.loads(cookies_json)
            logger.info("[QRATOR] ✅ Qrator challenge решен, получена jsid2 кука")
            _save_cached_cookies(cookies)
            return cookies
        else:
            logger.error("[QRATOR] Не удалось найти куки в выводе solve_qrator.js")
            logger.debug("[QRATOR] Полный вывод: %s", output)
            return None

    except subprocess.TimeoutExpired:
        logger.error("[QRATOR] Node.js скрипт timeout (60 сек) - возможно Playwright браузер медленно запускается")
        logger.info("[QRATOR] На Linux убедись: npx playwright install chromium")
        return None
    except Exception as exc:
        logger.error("[QRATOR] Ошибка при запуске solve_qrator.js: %s", exc)
        logger.debug("[QRATOR] Полная ошибка:", exc_info=True)
        return None
