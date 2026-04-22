#!/usr/bin/env python3
"""
Автоматический запуск: обновление кук + парсинг товаров в цикле.
ТГ бот работает параллельно в отдельной задаче (всегда включен).
"""

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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


_MSK = ZoneInfo("Europe/Moscow")


def is_night_time() -> bool:
    """Проверяет если сейчас ночное время (22:00-6:00 МСК)."""
    hour = datetime.now(_MSK).hour
    return hour >= 22 or hour < 6


def calculate_next_sync_sleep(interval_sec: int) -> int:
    """Рассчитывает сколько спать до следующего синхронного времени (как крон).

    Если интервал 3600 (час), то запускать в 0, 60, 120 минут
    Если интервал 1800 (30 мин), то запускать в 0, 30 минут часа
    Если интервал 900 (15 мин), то запускать в 0, 15, 30, 45 минут часа
    """
    now = datetime.now(_MSK)
    now_seconds = now.hour * 3600 + now.minute * 60 + now.second

    # Следующее синхронное время
    # Расстояние до следующего кратного интервалу момента времени
    remainder = now_seconds % interval_sec
    if remainder == 0:
        return interval_sec  # Если ровно на границе, ждем полный интервал
    return interval_sec - remainder


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
    logger.info("[RUN] Режим: БЕЗ БРАУЗЕРА (Playwright + Node.js для Qrator)")
    logger.info("[RUN] Интервал обновления: %d сек", config.parse_interval)
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
        logger.info("[RUN] Итерация #%d [%s]", iteration, timestamp)
        if consecutive_errors > 0:
            logger.warning("[RUN] Подряд ошибок: %d/%d", consecutive_errors, max_consecutive_errors)
        logger.info("="*70)

        if await run_parser():
            consecutive_errors = 0
            logger.info("[RUN] ✅ Парсер завершен успешно")
        else:
            consecutive_errors += 1
            logger.error("[RUN] ❌ Парсер завершен с ошибкой (%d/%d)", consecutive_errors, max_consecutive_errors)

            if consecutive_errors >= max_consecutive_errors:
                logger.critical("[RUN] 🔴 Достигнуто максимальное число ошибок. Требуется вмешательство!")
                await asyncio.sleep(60)

        # Проверяем новый интервал (если админ изменил)
        new_interval = parser_controller.get_pending_interval()
        if new_interval:
            wait_time = new_interval
            logger.info("[RUN] ⏱️  Новый интервал: %d сек", wait_time)

        # Проверяем ночное время (22:00-6:00)
        if is_night_time():
            now = datetime.now(_MSK)
            next_morning = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now.hour >= 22:
                # После 22:00 - спим до 6:00 следующего дня
                next_morning += timedelta(days=1)
            sleep_seconds = int((next_morning - now).total_seconds())
            logger.info("[RUN] 🌙 Ночное время (22:00-6:00), ожидание до 6:00 (%d сек)...", sleep_seconds)
            try:
                await asyncio.sleep(sleep_seconds)
            except KeyboardInterrupt:
                logger.info("[RUN] Остановлено пользователем (Ctrl+C)")
                break
            continue

        # Синхронизируем запуски с крон (как будто настроен крон с интервалом)
        sync_sleep = calculate_next_sync_sleep(wait_time)
        logger.info("[RUN] Синхронный запуск через %d сек (интервал %d сек)...", sync_sleep, wait_time)
        try:
            await asyncio.sleep(sync_sleep)
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
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[RUN] Остановлено, завершение...")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
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
        logger.error("[RUN] Критическая ошибка: %s", e)
        sys.exit(1)
