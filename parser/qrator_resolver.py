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
from pathlib import Path

from utils.logger import logger


_COOKIES_PATTERN = re.compile(
    r"__QRATOR_COOKIES__\s*\n(.*?)\n__END_COOKIES__",
    re.DOTALL,
)


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


async def resolve_qrator_cookies() -> dict[str, str] | None:
    """
    Запускает solve_qrator.js и получает qrator_jsid2.
    Возвращает словарь с куками или None если ошибка.

    Поддерживает кроссплатформенность (Windows/Linux/macOS).
    """
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
