"""
Отправка уведомлений в Telegram о новых товарах.
Использует Telegram бот для broadcast уведомлений всем подписчикам.
"""

import asyncio
from collections import defaultdict
from datetime import datetime
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


def _format_product_line(title: str, url: str, price_str: str, icon: str = "💰") -> str:
    safe_title = html_escape(title, quote=False)
    if url:
        safe_url = html_escape(url, quote=True)
        line = f"• <a href=\"{safe_url}\">{safe_title}</a>\n"
    else:
        line = f"• {safe_title}\n"
    return line + f"  {icon} {price_str}\n\n"


_BATCH_NEW_PRODUCTS = 10
_BATCH_PRICE_CHANGES = 15


class TelegramNotifier:
    """Отправка уведомлений в Telegram о новых товарах всем подписчикам."""

    def __init__(self, bot=None, db=None) -> None:
        self.bot = bot
        self.db = db
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
                status = prod.get('status', '')

                icon = "🔽" if new_price < old_price else "🔼"
                price_str = f"{_fmt_price(new_price)} ₽ <s>{_fmt_price(old_price)}</s>"
                price_str += _status_badge(status)

                products_text += _format_product_line(title, prod.get('url', ''), price_str, icon=icon)

            header = f"🏷️ <i>Изменение цен</i>"
            if total_batches > 1:
                header += f" ({batch_idx}/{total_batches})"

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

    async def send_digest(
        self,
        new_products: list[dict],
        price_changes: list[dict],
    ) -> None:
        """Отправляет персональный дайджест каждому подписчику с учётом его настроек.

        new_products: [{category_id, category, title, price, price_old, url, status}]
        price_changes: [{category_id, title, url, new_price, old_price, price_old, status}]
        """
        if not self.bot or not self.db:
            return
        if not new_products and not price_changes:
            return

        subscribers = self.db.get_all_subscribers_with_settings()
        if not subscribers:
            return

        logger.info("[TG DIGEST] Рассылка дайджеста %d подписчикам", len(subscribers))
        blocked: list[str] = []

        for sub in subscribers:
            if not sub["notifications_on"]:
                continue

            user_id = sub["user_id"]
            user_cats = set(self.db.get_user_categories(user_id))  # пусто = все

            filtered_new: list[dict] = []
            if sub["notify_new"]:
                for p in new_products:
                    if user_cats and p.get("category_id") not in user_cats:
                        continue
                    filtered_new.append(p)

            filtered_drops: list[dict] = []
            if sub["notify_price_drop"]:
                min_pct = sub["min_price_drop_pct"]
                for p in price_changes:
                    if user_cats and p.get("category_id") not in user_cats:
                        continue
                    old = p.get("old_price", 0)
                    new = p.get("new_price", 0)
                    if old and new < old and min_pct > 0:
                        if (old - new) / old * 100 < min_pct:
                            continue
                    filtered_drops.append(p)

            if not filtered_new and not filtered_drops:
                continue

            message = self._format_digest(filtered_new, filtered_drops)
            result = await self.bot.send_message(user_id, message)
            if result == "blocked":
                blocked.append(user_id)
            await asyncio.sleep(1.1)

        for user_id in blocked:
            self.db.remove_telegram_subscriber(user_id)
        if blocked:
            logger.info("[TG DIGEST] Удалено %d заблокировавших подписчиков", len(blocked))

    def _format_digest(self, new_products: list[dict], price_changes: list[dict]) -> str:
        """Форматирует единое дайджест-сообщение."""
        now = datetime.now().strftime("%H:%M")
        parts = [f"📊 <b>Дайджест DNS — {now}</b>\n"]

        if new_products:
            grouped = group_products(new_products)
            parts.append(f"🆕 <b>Новые товары ({len(grouped)}):</b>")
            for prod in grouped[:20]:
                title = html_escape(prod["title"][:60], quote=False)
                price_str = f"{_fmt_price(prod['price'])} ₽"
                if prod.get("price_old") and prod["price_old"] > prod["price"]:
                    price_str += f" <s>{_fmt_price(prod['price_old'])}</s>"
                price_str += _status_badge(prod.get("status", ""))
                url = prod.get("url", "")
                if url:
                    parts.append(f'• <a href="{html_escape(url, quote=True)}">{title}</a> — {price_str}')
                else:
                    parts.append(f"• {title} — {price_str}")
            if len(grouped) > 20:
                parts.append(f"<i>...и ещё {len(grouped) - 20}</i>")
            parts.append("")

        if price_changes:
            grouped = group_products(price_changes)
            parts.append(f"🏷 <b>Снижение цен ({len(grouped)}):</b>")
            for prod in grouped[:20]:
                title = html_escape(prod["title"][:60], quote=False)
                new_p = prod["new_price"]
                old_p = prod["old_price"]
                pct = round((old_p - new_p) / old_p * 100) if old_p else 0
                price_str = f"{_fmt_price(new_p)} ₽ <s>{_fmt_price(old_p)}</s> (−{pct}%)"
                price_str += _status_badge(prod.get("status", ""))
                url = prod.get("url", "")
                if url:
                    parts.append(f'• <a href="{html_escape(url, quote=True)}">{title}</a> — {price_str}')
                else:
                    parts.append(f"• {title} — {price_str}")
            if len(grouped) > 20:
                parts.append(f"<i>...и ещё {len(grouped) - 20}</i>")

        return "\n".join(parts)

    async def send_admin_alert(self, text: str) -> None:
        """Отправляет сообщение напрямую администратору (не всем подписчикам)."""
        if self.bot and self.bot.admin_id:
            await self.bot.send_message(self.bot.admin_id, text)

    async def close(self) -> None:
        """Закрывает Telegram notifier."""
        if self.bot:
            await self.bot.close()
