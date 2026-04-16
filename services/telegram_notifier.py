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

            # Формат: кликабельная ссылка - цена руб. (зачёркнутая старая цена)
            price_str = f"{price} руб."
            if price_old and price_old > price:
                price_str += f" <s>{price_old}</s>"

            if url:
                products_text += f"• <a href=\"{url}\">{title}</a>\n"
            else:
                products_text += f"• {title}\n"
            products_text += f"  💰 {price_str}\n\n"

        if len(new_products) > 10:
            products_text += f"<i>... и ещё {len(new_products) - 10} товаров</i>"

        message = (
            f"🆕 <b>Новые товары в {category_name}!</b>\n"
            f"Добавлено: {len(new_products)} шт\n\n"
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

    async def send_price_changes_notification(self, price_changes: list[dict]) -> bool:
        """Отправляет уведомления об изменениях цен батчами по 15 товаров."""
        if not self.enabled or not self.bot or not price_changes:
            return False

        BATCH_SIZE = 15
        batches = [
            price_changes[i : i + BATCH_SIZE]
            for i in range(0, len(price_changes), BATCH_SIZE)
        ]
        total_batches = len(batches)

        for batch_idx, batch in enumerate(batches, 1):
            products_text = ""
            for prod in batch:
                title = prod['title'][:50]
                url = prod.get('url', '')
                new_price = prod['new_price']
                old_price = prod['old_price']
                price_old = prod.get('price_old', 0)

                arrow = "↓" if new_price < old_price else "↑"
                price_str = f"{new_price} руб. {arrow} ({old_price} руб.)"
                if price_old and price_old > new_price:
                    price_str += f" <s>{price_old}</s>"

                if url:
                    products_text += f"• <a href=\"{url}\">{title}</a>\n"
                else:
                    products_text += f"• {title}\n"
                products_text += f"  💰 {price_str}\n\n"

            # Формируем заголовок с номером батча
            header = f"📊 <b>Изменение цен</b>"
            if total_batches > 1:
                header += f" ({batch_idx}/{total_batches})"
            # Только в первом батче показываем общее количество товаров
            if batch_idx == 1:
                header += f"\nТоваров: {len(price_changes)} шт"

            message = f"{header}\n\n{products_text}"

            try:
                await self.bot.broadcast_message(message)
            except Exception as exc:
                logger.error(
                    "[TG NOTIF] Ошибка при отправке батча %d/%d: %s",
                    batch_idx,
                    total_batches,
                    exc,
                )
                return False

        logger.info(
            "[TG NOTIF] Уведомления об изменении цен отправлены батчами (%d шт, %d батчей)",
            len(price_changes),
            total_batches,
        )
        return True

    async def close(self) -> None:
        """Закрывает Telegram notifier."""
        if self.bot:
            await self.bot.close()
