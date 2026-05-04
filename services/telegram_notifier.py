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


def _title_with_count(title: str, count: int) -> str:
    if count > 1:
        return f"{title} ({count} шт.)"
    return title


_BATCH_NEW_PRODUCTS = 10
_BATCH_PRICE_CHANGES = 15
_BATCH_DIGEST_NEW = 10
_BATCH_DIGEST_PRICE = 15


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
                title = _title_with_count(title, count)

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
                title = _title_with_count(title, count)

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
            user_city = sub["city_slug"]
            user_cats = set(self.db.get_user_categories(user_id))  # пусто = все

            filtered_new: list[dict] = []
            if sub["notify_new"]:
                for p in new_products:
                    if user_cats and p.get("category_id") not in user_cats:
                        continue
                    prod_city = p.get("city_slug", "")
                    if prod_city and user_city and prod_city != user_city:
                        continue
                    filtered_new.append(p)

            filtered_drops: list[dict] = []
            if sub["notify_price_drop"]:
                min_pct = sub["min_price_drop_pct"]
                for p in price_changes:
                    if user_cats and p.get("category_id") not in user_cats:
                        continue
                    prod_city = p.get("city_slug", "")
                    if prod_city and user_city and prod_city != user_city:
                        continue
                    old = p.get("old_price", 0)
                    new = p.get("new_price", 0)
                    if old and new < old and min_pct > 0:
                        if (old - new) / old * 100 < min_pct:
                            continue
                    filtered_drops.append(p)

            if not filtered_new and not filtered_drops:
                continue

            chunks = self._build_digest_chunks(filtered_new, filtered_drops)
            for chunk in chunks:
                result = await self.bot.send_message(user_id, chunk)
                if result == "blocked":
                    blocked.append(user_id)
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(0.7)

        for user_id in blocked:
            self.db.remove_telegram_subscriber(user_id)
        if blocked:
            logger.info("[TG DIGEST] Удалено %d заблокировавших подписчиков", len(blocked))

    def _build_digest_chunks(
        self, new_products: list[dict], price_changes: list[dict]
    ) -> list[str]:
        """Разбивает дайджест на чанки — каждый чанк отдельное сообщение."""
        now = datetime.now().strftime("%H:%M")
        chunks: list[str] = []

        if new_products:
            grouped = group_products(new_products)
            total_raw = len(new_products)
            total_grouped = len(grouped)
            batches = [grouped[i : i + _BATCH_DIGEST_NEW] for i in range(0, total_grouped, _BATCH_DIGEST_NEW)]
            for batch_idx, batch in enumerate(batches, 1):
                total_text = str(total_raw)
                if total_grouped != total_raw:
                    total_text += f", показано {total_grouped}"
                header = f"📊 <b>Дайджест DNS — {now}</b>\n\n🆕 <b>Новые товары ({total_text})</b>"
                if len(batches) > 1:
                    header += f" ({batch_idx}/{len(batches)})"
                header += "\n\n"
                body = ""
                for prod in batch:
                    title = _title_with_count(wrap_text(prod["title"]), prod.get("count", 1))
                    price_str = f"{_fmt_price(prod['price'])} ₽"
                    if prod.get("price_old") and prod["price_old"] > prod["price"]:
                        price_str += f" <s>{_fmt_price(prod['price_old'])}</s>"
                    price_str += _status_badge(prod.get("status", ""))
                    body += _format_product_line(title, prod.get("url", ""), price_str)
                chunks.append(header + body)

        if price_changes:
            grouped = group_products(price_changes)
            total = len(grouped)
            batches = [grouped[i : i + _BATCH_DIGEST_PRICE] for i in range(0, total, _BATCH_DIGEST_PRICE)]
            for batch_idx, batch in enumerate(batches, 1):
                header = f"🏷 <b>Снижение цен ({total})</b>"
                if len(batches) > 1:
                    header += f" ({batch_idx}/{len(batches)})"
                header += "\n\n"
                body = ""
                for prod in batch:
                    title = _title_with_count(wrap_text(prod["title"]), prod.get("count", 1))
                    new_p = prod["new_price"]
                    old_p = prod["old_price"]
                    pct = round((old_p - new_p) / old_p * 100) if old_p else 0
                    price_str = f"{_fmt_price(new_p)} ₽ <s>{_fmt_price(old_p)}</s> (−{pct}%)"
                    price_str += _status_badge(prod.get("status", ""))
                    body += _format_product_line(title, prod.get("url", ""), price_str, icon="🔽")
                chunks.append(header + body)

        return chunks

    def _format_digest(self, new_products: list[dict], price_changes: list[dict]) -> str:
        """Форматирует дайджест-сообщение (все чанки объединены, для тестов и превью)."""
        return "\n\n".join(self._build_digest_chunks(new_products, price_changes))

    async def send_admin_alert(self, text: str, msg_type: str = "error") -> None:
        """Отправляет сообщение напрямую администратору (не всем подписчикам).

        msg_type: "error" — проверяет notify_errors; "parse_finish" — notify_parse_finish.
        """
        if not (self.bot and self.bot.admin_id):
            return

        # Проверяем настройки админа
        admin_settings = self._get_admin_settings()
        if msg_type == "error" and not admin_settings.get("notify_errors", True):
            return
        if msg_type == "parse_finish" and not admin_settings.get("notify_parse_finish", True):
            return

        await self.bot.send_message(self.bot.admin_id, text)

    def _get_admin_settings(self) -> dict:
        """Возвращает настройки админа из БД, кеширует результат."""
        if not hasattr(self, "_admin_settings") or self._admin_settings is None:
            self._admin_settings = {}
            if self.db and self.bot and self.bot.admin_id:
                subs = self.db.get_all_subscribers_with_settings()
                for sub in subs:
                    if sub["user_id"] == self.bot.admin_id:
                        self._admin_settings = sub
                        break
        return self._admin_settings

    def _invalidate_admin_settings(self) -> None:
        """Сбрасывает кеш настроек админа (вызывать после изменения настроек)."""
        self._admin_settings = None

    async def send_admin_parse_finish(
        self,
        new_cnt: int,
        updated_cnt: int,
        price_changed: int,
        total_db: int,
        prev_cnt: int,
        delta: int,
    ) -> None:
        """Отправляет админу сводку о завершённом цикле парсинга."""
        delta_str = f"(+{delta})" if delta > 0 else f"({delta})" if delta < 0 else "(0)"
        text = (
            f"📋 <b>Парсинг завершён</b>\n"
            f"🆕 Новых: {new_cnt}\n"
            f"🔄 Обновлено: {updated_cnt}\n"
            f"💰 Цены изменились: {price_changed}\n"
            f"📦 Всего в БД: {total_db} {delta_str}"
        )
        await self.send_admin_alert(text, msg_type="parse_finish")

    async def close(self) -> None:
        """Закрывает сессию."""
        self._admin_settings = None
        if self.bot:
            await self.bot.close()
