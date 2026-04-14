"""
Отправка уведомлений в Telegram о новых товарах.
Использует Telegram бот для broadcast уведомлений всем подписчикам.
"""

import asyncio
from typing import Optional

from utils.logger import logger


class TelegramNotifier:
    """Отправка уведомлений в Telegram о новых товарах всем подписчикам."""

    def __init__(self, bot=None) -> None:
        self.bot = bot
        self.enabled = bool(bot)

    async def send_new_products_notification(
        self,
        category_name: str,
        new_products: list[dict],
    ) -> bool:
        """Отправляет уведомление о новых товарах всем подписчикам."""
        if not self.enabled or not self.bot:
            logger.debug("[TG NOTIF] Telegram отключен")
            return False

        if not new_products:
            return False

        # Форматируем список новых товаров (максимум 10)
        products_text = ""
        for prod in new_products[:10]:
            title = prod['title'][:50]
            price = prod['price']
            price_old = prod.get('price_old', 0)
            url = prod.get('url', '')

            # Формат: Категория - Название - цена руб. прайс старая_цена
            price_str = f"{price} руб."
            if price_old and price_old > price:
                price_str += f" прайс {price_old}"

            products_text += f"{title} - {price_str}\n"
            if url:
                products_text += f"{url}\n"
            products_text += "\n"

        if len(new_products) > 10:
            products_text += f"... и еще {len(new_products) - 10} товаров"

        message = (
            f"<b>Новые товары в {category_name}!</b>\n\n"
            f"<b>Добавлено:</b> {len(new_products)} шт\n\n"
            f"{products_text}"
        )

        # Отправляем всем подписчикам
        try:
            sent_count = await self.bot.broadcast_message(message)
            logger.info(
                "[TG NOTIF] Уведомление отправлено %d подписчикам",
                sent_count,
            )
            return sent_count > 0
        except Exception as exc:
            logger.error("[TG NOTIF] Ошибка при отправке уведомления: %s", exc)
            return False

    async def close(self) -> None:
        """Закрывает Telegram notifier."""
        if self.bot:
            await self.bot.close()
