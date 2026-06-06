"""
Утилиты для Telegram-бота: константы и чистые функции форматирования.
Не зависит от состояния бота, базы данных или асинхронных операций.
"""
from typing import Optional

_MAX_SEARCH_LEN = 60
_VALID_REPORT_PCTS = {10, 20, 30, 40, 50, 60, 70, 80, 90}
_TELEGRAM_SAFE_MESSAGE_LEN = 3800
_MAX_REPORT_TITLE_LEN = 180


def _escape_html_text(value: str) -> str:
    """Escape < > & для текста в HTML-режиме Telegram."""
    return (value
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _escape_html_attr(value: str) -> str:
    """Escape < > & " для атрибутов в HTML-режиме Telegram (href).
    Также используется для текста внутри <a> — экранирует " в &quot;."""
    return (value
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _format_price(value):
    if value is None:
        return "не указана"
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "?"


def _truncate_report_title(title: str) -> str:
    """Обрезает заголовок товара до MAX_REPORT_TITLE_LEN символов."""
    if len(title) > _MAX_REPORT_TITLE_LEN:
        return title[:_MAX_REPORT_TITLE_LEN - 1] + "…"
    return title


def format_user_status_text(
    settings: dict,
    cats: list[str],
    slug_to_city: dict,
) -> str:
    """Форматирует статус настроек пользователя.

    Используется и в команде /status, и в callback menu_status_cmd —
    устраняет дублирование ~25 строк кода.
    """
    city_slug = settings.get("city_slug", "")
    city_name = slug_to_city.get(city_slug, city_slug)
    cat_text = "все" if not cats else f"{len(cats)} шт."
    notif_on = settings.get("notifications_on", False)
    notif_text = "включены ✅" if notif_on else "выключены 🔕"
    new_text = "✅" if settings.get("notify_new") else "❌"
    drop_text = "✅" if settings.get("notify_price_drop") else "❌"
    pct_val = settings.get("min_price_drop_pct")
    pct_text = f">{pct_val}%" if pct_val else "любое"

    return (
        f"📋 <b>Ваши настройки</b>\n\n"
        f"🏙 Город: {city_name}\n"
        f"📂 Категории: {cat_text}\n"
        f"🔔 Уведомления: {notif_text}\n"
        f"🆕 Новые товары: {new_text}\n"
        f"🏷 Снижение цен: {drop_text} (порог: {pct_text})\n\n"
        f"<i>Парсер работает для города из .env — ваш город сохранён для будущих функций.</i>"
    )
