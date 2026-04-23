"""
Отправка уведомлений в Telegram о новых товарах.
Использует Telegram бот для broadcast уведомлений всем подписчикам.
"""

from collections import defaultdict
from html import escape as html_escape
from typing import Optional

from utils.logger import logger


def wrap_text(text: str, width: int = 60) -> str:
    """Разбивает текст на строки заданной ширины, сохраняя слова целыми."""
    if len(text) <= width:
        return text

    words = text.split()
    lines = []
    current_line = []
    current_length = 0

    for word in words:
        if current_length + len(word) + 1 > width:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
        else:
            current_line.append(word)
            current_length += len(word) + 1

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


def group_products(products: list[dict]) -> list[dict]:
    """Группирует одинаковые товары по названию и цене, подсчитывая количество."""

    groups = defaultdict(lambda: {"count": 0, "product": None})

    for prod in products:
        key = (prod["title"], prod.get("price", prod.get("new_price")))
        if groups[key]["product"] is None:
            groups[key]["product"] = prod.copy()
        groups[key]["count"] += 1

    return [
        {**group["product"], "count": group["count"]}
        for group in groups.values()
    ]


def _fmt_price(amount: int) -> str:
    """Форматирует число с пробелами как разделителями тысяч: 4999 → 4 999."""
    return f"{amount:,}".replace(",", " ")


def _status_badge(status: str) -> str:
    """Возвращает эмодзи-бейдж по статусу товара."""
    if status == "Новый":
        return " 🆕"
    if status == "Б/У":
        return " ♻️"
    return f" <b>{html_escape(status, quote=False)}</b>" if status else ""


def _format_product_line(title: str, url: str, price_str: str) -> str:
    safe_title = html_escape(title, quote=False)
    if url:
        safe_url = html_escape(url, quote=True)
        line = f"• <a href=\"{safe_url}\">{safe_title}</a>\n"
    else:
        line = f"• {safe_title}\n"
    return line + f"  💰 {price_str}\n\n"


_BATCH_NEW_PRODUCTS = 10
_BATCH_PRICE_CHANGES = 15


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
        if not self.bot:
            logger.debug("[TG NOTIF] Telegram отключен")
            return False

        if not new_products:
            return False

        grouped_products = group_products(new_products)
        total = len(grouped_products)
        batches = [grouped_products[i : i + _BATCH_NEW_PRODUCTS] for i in range(0, total, _BATCH_NEW_PRODUCTS)]
        total_batches = len(batches)

        for batch_idx, batch in enumerate(batches, 1):
            products_text = ""
            for prod in batch:
                title = wrap_text(prod['title'])
                count = prod.get('count', 1)
                if count > 1:
                    title = f"{title} (х{count})"

                price = prod['price']
                price_old = prod.get('price_old', 0)
                status = prod.get('status', '')

                price_str = f"{_fmt_price(price)} ₽"
                if price_old and price_old > price:
                    price_str += f" <s>{_fmt_price(price_old)}</s>"
                price_str += _status_badge(status)

                products_text += _format_product_line(title, prod.get('url', ''), price_str)

            safe_cat = html_escape(category_name, quote=False)
            header = f"🆕 <b>{safe_cat}</b> • +{len(new_products)}"
            if total_batches > 1:
                header += f" ({batch_idx}/{total_batches})"

            message = f"{header}\n\n{products_text}"

            try:
                sent_count = await self.bot.broadcast_message(message)
                if batch_idx == 1:
                    logger.info("[TG NOTIF] Уведомление отправлено %d подписчикам", sent_count)
            except Exception as exc:
                logger.error("[TG NOTIF] Ошибка при отправке батча %d/%d: %s", batch_idx, total_batches, exc)
                return False

        return True

    async def send_price_changes_notification(self, price_changes: list[dict]) -> bool:
        """Отправляет уведомления об изменениях цен батчами по 15 товаров."""
        if not self.bot or not price_changes:
            return False

        batches = [
            price_changes[i : i + _BATCH_PRICE_CHANGES]
            for i in range(0, len(price_changes), _BATCH_PRICE_CHANGES)
        ]
        total_batches = len(batches)

        for batch_idx, batch in enumerate(batches, 1):
            grouped_batch = group_products(batch)
            products_text = ""
            for prod in grouped_batch:
                title = wrap_text(prod['title'])
                count = prod.get('count', 1)
                if count > 1:
                    title = f"{title} (х{count})"

                new_price = prod['new_price']
                old_price = prod['old_price']
                price_old = prod.get('price_old', 0)
                arrow = "↓" if new_price < old_price else "↑"
                price_str = f"{new_price} руб. {arrow} ({old_price} руб.)"
                if price_old and price_old > new_price:
                    price_str += f" <s>{price_old} руб.</s>"
                status = prod.get('status', '')
                if status:
                    price_str += f" (<b>{html_escape(status, quote=False)}</b>)"

                products_text += _format_product_line(title, prod.get('url', ''), price_str)

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

    async def send_admin_alert(self, text: str) -> None:
        """Отправляет сообщение напрямую администратору (не всем подписчикам)."""
        if self.bot and self.bot.admin_id:
            await self.bot.send_message(self.bot.admin_id, text)

    async def close(self) -> None:
        """Закрывает Telegram notifier."""
        if self.bot:
            await self.bot.close()
