#!/usr/bin/env python3
"""
Автоматический запуск: обновление кук + парсинг товаров в цикле.
ТГ бот работает параллельно в отдельной задаче (всегда включен).
"""

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import config
from parser.db_manager import DBManager
from services.telegram_bot import init_telegram_bot
from services.admin_panel import ParserController
from utils.logger import logger

# Определяем директорию проекта
PROJECT_DIR = Path(__file__).parent.absolute()

async def _run_subprocess(script: str, log_name: str) -> bool:
    """Запускает Python-скрипт в отдельном процессе асинхронно."""
    logger.info("[RUN] Запускаю: %s", log_name)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, str(PROJECT_DIR / script)],
                cwd=str(PROJECT_DIR),
                check=False,
                timeout=600,
            ),
        )
        if result.returncode == 0:
            logger.info("[RUN] ✓ %s завершено успешно", log_name)
            return True
        else:
            logger.error("[RUN] ✗ %s завершен с кодом %d", script, result.returncode)
            return False
    except asyncio.TimeoutError:
        logger.error("[RUN] ✗ %s превышен timeout (10 минут)", script)
        return False
    except Exception as e:
        logger.error("[RUN] ✗ Ошибка при выполнении %s: %s", script, e)
        return False


async def run_parser() -> bool:
    """Запускает parser в отдельном процессе асинхронно."""
    return await _run_subprocess("parser.py", "Парсинг товаров")


async def telegram_bot_polling(telegram_bot) -> None:
    """Бесконечный цикл для ТГ бота (работает параллельно)."""
    await telegram_bot.polling_loop()


async def main_cycle(parser_controller: ParserController) -> None:
    """Главный цикл: парсинг товаров с поддержкой управления админом."""
    logger.info("="*70)
    logger.info("[RUN] Запущен автоматический парсер DNS Shop")
    logger.info(f"[RUN] Режим: БЕЗ БРАУЗЕРА (Playwright + Node.js для Qrator)")
    logger.info(f"[RUN] Интервал обновления: {config.parse_interval} сек")
    logger.info("[RUN] Админ-панель активна")
    logger.info("="*70)

    iteration = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    wait_time = config.parse_interval

    while not parser_controller.should_stop():
        if not parser_controller.state.is_running:
            logger.info("[RUN] ⏸️  Парсер остановлен админом, ожидание команды...")
            await asyncio.sleep(5)
            continue

        iteration += 1
        parser_controller.state.iteration_count = iteration
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info("")
        logger.info("="*70)
        logger.info(f"[RUN] Итерация #{iteration} [{timestamp}]")
        if consecutive_errors > 0:
            logger.warning(f"[RUN] Подряд ошибок: {consecutive_errors}/{max_consecutive_errors}")
        logger.info("="*70)

        if await run_parser():
            consecutive_errors = 0
            logger.info("[RUN] ✅ Парсер завершен успешно")
        else:
            consecutive_errors += 1
            logger.error(f"[RUN] ❌ Парсер завершен с ошибкой ({consecutive_errors}/{max_consecutive_errors})")

            if consecutive_errors >= max_consecutive_errors:
                logger.critical("[RUN] 🔴 Достигнуто максимальное число ошибок. Требуется вмешательство!")
                await asyncio.sleep(60)

        # Ждем перед следующей итерацией с проверкой команд админа
        new_interval = parser_controller.get_pending_interval()
        if new_interval:
            wait_time = new_interval
            logger.info(f"[RUN] ⏱️  Новый интервал: {wait_time} сек")

        logger.info(f"[RUN] Следующее обновление через {wait_time} сек...")
        try:
            await asyncio.sleep(wait_time)
        except KeyboardInterrupt:
            logger.info("[RUN] Остановлено пользователем (Ctrl+C)")
            break


async def main() -> None:
    """Запускает основной цикл и ТГ бота параллельно."""

    # Инициализируем контроллер парсера и БД
    parser_controller = ParserController()
    db = DBManager(config.db_path)
    telegram_bot = init_telegram_bot(db, parser_controller)

    # Автоматический старт парсера при запуске
    await parser_controller.start()

    # Создаем две независимые задачи:
    # 1. Основной цикл (get_cookies + parser) с поддержкой управления
    # 2. ТГ бот (polling - обработка команд)

    tasks = [
        asyncio.create_task(main_cycle(parser_controller)),
        asyncio.create_task(telegram_bot_polling(telegram_bot)),
    ]

    try:
        # Ждем первой завершенной задачи (обычно при Ctrl+C)
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("[RUN] Остановлено пользователем (Ctrl+C)")
    finally:
        # Отменяем все задачи при выходе
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await telegram_bot.close()
        db.close()
        logger.info("[RUN] Выход")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[RUN] Выход")
        sys.exit(0)
    except Exception as e:
        logger.error(f"[RUN] Критическая ошибка: {e}")
        sys.exit(1)
