"""
Получение qrator_jsid2 куки через Node.js скрипт solve_qrator.js.

Используется как fallback когда логин + HTTP недостаточно
для получения jsid2 куки.
"""

import asyncio
import json
import re
import subprocess
from pathlib import Path

from utils.logger import logger


_COOKIES_PATTERN = re.compile(
    r"__QRATOR_COOKIES__\s*\n(.*?)\n__END_COOKIES__",
    re.DOTALL,
)


def get_solve_script_path() -> Path:
    """Возвращает путь к solve_qrator.js."""
    return Path(__file__).parent.parent / "solve_qrator.js"


async def resolve_qrator_cookies() -> dict[str, str] | None:
    """
    Запускает solve_qrator.js и получает qrator_jsid2.
    Возвращает словарь с куками или None если ошибка.
    """
    script_path = get_solve_script_path()
    if not script_path.exists():
        logger.error("solve_qrator.js не найден: %s", script_path)
        return None

    try:
        logger.debug("Запускаем solve_qrator.js для получения jsid2...")
        result = await asyncio.to_thread(
            subprocess.run,
            ["node", str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr
        logger.debug("solve_qrator.js вывод (последние 200 символов): %s", output[-200:])

        # Парсим JSON из вывода
        match = _COOKIES_PATTERN.search(output)
        if match:
            cookies_json = match.group(1).strip()
            cookies = json.loads(cookies_json)
            logger.info(
                "Qrator challenge решен, получена jsid2 кука"
            )
            return cookies
        else:
            logger.error("Не удалось найти куки в выводе solve_qrator.js")
            logger.debug("Полный вывод: %s", output)
            return None

    except subprocess.TimeoutExpired:
        logger.error("solve_qrator.js timeout (60 сек)")
        return None
    except Exception as exc:
        logger.error("Ошибка при запуске solve_qrator.js: %s", exc)
        return None
