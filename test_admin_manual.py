#!/usr/bin/env python3
"""
Диагностический скрипт для проверки админ-панели.
Запустить: python test_admin_manual.py
"""

import asyncio
import json
from config import config
from services.admin_panel import ParserController
from services.telegram_bot import TelegramBot, init_telegram_bot
from parser.db_manager import DBManager
from utils.logger import logger

async def test_admin_panel():
    """Тест админ панели."""
    print("\n" + "="*70)
    print("[TEST] DIAGNOSTIKA ADMIN-PANELI")
    print("="*70 + "\n")

    # 1. Proverkka konfiga
    print("[OK] KONFIG")
    print(f"  telegram_token: {'OK' if config.telegram_token else 'MISSING'}")
    print(f"  telegram_chat_id: {config.telegram_chat_id}")
    print(f"  telegram_chat_admin: {config.telegram_chat_admin}")
    print()

    # 2. Inicializacija kontrollera
    print("[OK] PARSER KONTROLLER")
    controller = ParserController()
    print(f"  Inicijalizovan: OK")
    print(f"  is_running: {controller.state.is_running}")
    print()

    # 3. Test komandi
    print("[OK] KOMANDY KONTROLLLERA")

    # Start
    result = await controller.start()
    print(f"  start(): {result} -> is_running={controller.state.is_running}")

    # Set interval
    result = await controller.set_interval(1800)
    print(f"  set_interval(1800): {result}")

    # Get status
    status = controller.get_status()
    print(f"  get_status(): [emoji status here]")

    # Get pending interval
    interval = controller.get_pending_interval()
    print(f"  get_pending_interval(): {interval}")
    print()

    # 4. Inicijalizacija DB i bota
    print("[OK] TELEGRAM BOT")
    db = DBManager(config.db_path)
    bot = init_telegram_bot(db, controller)

    print(f"  Token: {'OK' if bot.enabled else 'MISSING'}")
    print(f"  Admin ID: {bot.admin_id}")
    print(f"  Parser Controller: {'OK' if bot.parser_controller else 'MISSING'}")
    print()

    # 5. Emulacija callback zaprosa
    print("[OK] EMULACIJA CALLBACK ZAPROSA")

    callback_query = {
        "id": "test_callback_1",
        "from": {"id": int(config.telegram_chat_admin) if config.telegram_chat_admin else 12345},
        "message": {"chat": {"id": int(config.telegram_chat_id) if config.telegram_chat_id else 67890}},
        "data": "admin_status"
    }

    print(f"  callback_query: {json.dumps(callback_query, indent=4)}")

    # Мокируем методы для тестирования
    original_answer_callback = bot._answer_callback
    original_send_message = bot.send_message

    called_callbacks = []
    called_messages = []

    async def mock_answer_callback(callback_id, text, alert=False):
        called_callbacks.append({"id": callback_id, "text": text, "alert": alert})
        logger.info("[TEST] answer_callback: %s", text)
        return True

    async def mock_send_message(chat_id, text):
        called_messages.append({"chat_id": chat_id, "text": text[:100]})
        logger.info("[TEST] send_message: %s...", text[:100])
        return True

    bot._answer_callback = mock_answer_callback
    bot.send_message = mock_send_message

    print("\n  Obrada callback...")
    await bot._handle_callback_query(callback_query)

    print(f"\n  Odgovori (answer_callback): {len(called_callbacks)}")
    for cb in called_callbacks:
        print(f"    - [callback text with emoji]")

    print(f"\n  Poruke (send_message): {len(called_messages)}")
    for msg in called_messages:
        print(f"    - [message text with emoji]")
    print()

    # 6. Rezultati
    print("="*70)
    print("[DONE] DIAGNOSTIKA ZAVRSENA")
    print("="*70)
    print("\nMOGUCI PROBLEMI:")
    print("  1. TELEGRAM_CHAT_ADMIN se ne podudara sa vasim ID-om")
    print("  2. Callback ne dolazi od Telegram-a (problem sa polling)")
    print("  3. Parser Controller nije inicijalizovan")
    print("\nLOGI:")
    print("  Pogledajte: tail -f logs/app.log | grep ADMIN")
    print()

if __name__ == "__main__":
    asyncio.run(test_admin_panel())
