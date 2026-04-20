#!/usr/bin/env python3
"""Тестирование Telegram бота без запуска парсера."""

import asyncio
import sys
from pathlib import Path

from config import config
from parser.db_manager import DBManager
from services.telegram_bot import init_telegram_bot
from utils.logger import logger


async def main() -> None:
    """Запускает только ТГ бота для тестирования."""

    if not config.telegram_token:
        print("❌ ОШИБКА: TELEGRAM_TOKEN не установлен в .env")
        sys.exit(1)

    print("\n" + "="*70)
    print("🤖 Запуск Telegram бота (БЕЗ ПАРСЕРА)")
    print("="*70 + "\n")

    # Инициализируем БД и бота
    db = DBManager(config.db_path)
    telegram_bot = init_telegram_bot(db, parser_controller=None)

    if not telegram_bot.enabled:
        print("❌ Бот отключен - проверьте TELEGRAM_TOKEN в .env")
        sys.exit(1)

    print(f"✅ Бот инициализирован")
    print(f"   Токен: {config.telegram_token[:20]}...")
    print(f"   Admin ID: {telegram_bot.admin_id or 'не установлен'}")
    print(f"   Подписчиков в БД: {len(telegram_bot.subscribed_users)}\n")
    print("⏳ Ожидание сообщений... (Ctrl+C для выхода)\n")

    try:
        await telegram_bot.polling_loop()
    except KeyboardInterrupt:
        print("\n\n⏹️  Остановлено пользователем (Ctrl+C)")
    finally:
        await telegram_bot.close()
        db.close()
        print("✓ Бот закрыт")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✓ Выход")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
