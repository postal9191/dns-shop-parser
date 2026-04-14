#!/usr/bin/env python3
"""Настройка Telegram бота - сброс webhook и запуск polling."""

import asyncio
import aiohttp
from config import config

async def setup_bot():
    """Сбрасывает webhook и выводит информацию о боте."""

    if not config.telegram_token:
        print("✗ ОШИБКА: TELEGRAM_TOKEN не установлен в .env")
        return False

    api_url = f"https://api.telegram.org/bot{config.telegram_token}"

    print("\n[*] Проверка Telegram бота...\n")

    # 1. Получаем информацию о боте
    print("[1] Информация о боте:")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/getMe") as resp:
                data = await resp.json()
                if data.get("ok"):
                    bot_info = data.get("result", {})
                    print(f"    ✓ Токен валидный")
                    print(f"    Бот: {bot_info.get('first_name')} (@{bot_info.get('username')})")
                    print(f"    ID: {bot_info.get('id')}\n")
                else:
                    print(f"    ✗ Ошибка: {data.get('description')}\n")
                    return False
    except Exception as e:
        print(f"    ✗ Ошибка подключения: {e}\n")
        return False

    # 2. Удаляем webhook (чтобы использовать polling)
    print("[2] Сброс webhook:")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{api_url}/deleteWebhook") as resp:
                data = await resp.json()
                if data.get("ok"):
                    print(f"    ✓ Webhook удален\n")
                else:
                    print(f"    ⚠ {data.get('description')}\n")
    except Exception as e:
        print(f"    ✗ Ошибка: {e}\n")
        return False

    # 3. Проверяем webhook статус
    print("[3] Проверка webhook статуса:")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/getWebhookInfo") as resp:
                data = await resp.json()
                if data.get("ok"):
                    webhook = data.get("result", {})
                    if webhook.get("url"):
                        print(f"    ⚠ Webhook еще установлен: {webhook.get('url')}\n")
                    else:
                        print(f"    ✓ Webhook не установлен (polling включен)\n")
                else:
                    print(f"    ✗ Ошибка: {data.get('description')}\n")
    except Exception as e:
        print(f"    ✗ Ошибка: {e}\n")
        return False

    # 4. Проверяем TELEGRAM_CHAT_ID
    print("[4] Проверка TELEGRAM_CHAT_ID:")
    if config.telegram_chat_id:
        print(f"    ✓ TELEGRAM_CHAT_ID установлен: {config.telegram_chat_id}\n")
    else:
        print(f"    ⚠ TELEGRAM_CHAT_ID пуст")
        print(f"    Первый пользователь который напишет /start будет добавлен\n")

    print("[✓] Бот готов к запуску!\n")
    print("Запустить парсер:")
    print("  python run.py\n")

    return True


if __name__ == "__main__":
    asyncio.run(setup_bot())
