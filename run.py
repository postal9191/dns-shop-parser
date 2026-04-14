#!/usr/bin/env python3
"""
Автоматический запуск: обновление кук + парсинг товаров в цикле.
ТГ бот работает параллельно в отдельной задаче (всегда включен).
"""

import asyncio
import sys
from datetime import datetime

from config import config
from parser.db_manager import DBManager
from services.telegram_bot import init_telegram_bot
from utils.logger import logger


async def run_get_cookies() -> bool:
    """Запускает get_cookies в отдельном процессе асинхронно."""
    logger.info("[RUN] Запускаю: Обновление кук")

    loop = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(
            None,
            lambda: __import__('subprocess').run(
                [sys.executable, 'get_cookies.py'],
                check=False,
                timeout=600
            )
        )

        if result.returncode == 0:
            logger.info("[RUN] ✓ Обновление кук завершено успешно")
            return True
        else:
            logger.error(f"[RUN] ✗ get_cookies завершен с кодом {result.returncode}")
            return False
    except asyncio.TimeoutError:
        logger.error("[RUN] ✗ get_cookies превышен timeout (10 минут)")
        return False
    except Exception as e:
        logger.error(f"[RUN] ✗ Ошибка при выполнении get_cookies: {e}")
        return False


async def run_parser() -> bool:
    """Запускает parser в отдельном процессе асинхронно."""
    logger.info("[RUN] Запускаю: Парсинг товаров")

    loop = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(
            None,
            lambda: __import__('subprocess').run(
                [sys.executable, 'parser.py'],
                check=False,
                timeout=600
            )
        )

        if result.returncode == 0:
            logger.info("[RUN] ✓ Парсинг товаров завершен успешно")
            return True
        else:
            logger.error(f"[RUN] ✗ parser завершен с кодом {result.returncode}")
            return False
    except asyncio.TimeoutError:
        logger.error("[RUN] ✗ parser превышен timeout (10 минут)")
        return False
    except Exception as e:
        logger.error(f"[RUN] ✗ Ошибка при выполнении parser: {e}")
        return False


async def telegram_bot_polling(telegram_bot) -> None:
    """Бесконечный цикл для ТГ бота (работает параллельно)."""
    await telegram_bot.polling_loop()


async def main_cycle() -> None:
    """Главный цикл: обновление кук + парсинг товаров."""
    logger.info("="*70)
    logger.info("[RUN] Запущен автоматический парсер DNS Shop")
    logger.info(f"[RUN] Интервал обновления: {config.parse_interval} сек")
    logger.info("="*70)

    iteration = 0
    while True:
        iteration += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info("")
        logger.info("="*70)
        logger.info(f"[RUN] Итерация #{iteration} [{timestamp}]")
        logger.info("="*70)

        # Шаг 1: Обновить куки через браузер
        if not await run_get_cookies():
            logger.warning("[RUN] Не удалось обновить куки, пропускаю итерацию")
            await asyncio.sleep(config.parse_interval)
            continue

        # Шаг 2: Парсить товары с новыми куками
        await run_parser()

        # Ждем перед следующей итерацией
        logger.info(f"[RUN] Следующее обновление через {config.parse_interval} сек...")
        try:
            await asyncio.sleep(config.parse_interval)
        except KeyboardInterrupt:
            logger.info("[RUN] Остановлено пользователем (Ctrl+C)")
            break


async def main() -> None:
    """Запускает основной цикл и ТГ бота параллельно."""

    # Инициализируем ТГ бота
    db = DBManager(config.db_path)
    telegram_bot = init_telegram_bot(db)

    # Создаем две независимые задачи:
    # 1. Основной цикл (get_cookies + parser)
    # 2. ТГ бот (polling - обработка команд)

    tasks = [
        asyncio.create_task(main_cycle()),
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
