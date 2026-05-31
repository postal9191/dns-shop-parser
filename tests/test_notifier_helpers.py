"""
Тесты для вспомогательных функций telegram_notifier:
wrap_text, group_products, _fmt_price, _status_badge,
_format_product_line, _title_with_count, TelegramNotifier.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock

from services.telegram_notifier import (
    wrap_text,
    group_products,
    _fmt_price,
    _status_badge,
    _format_product_line,
    _title_with_count,
    TelegramNotifier,
)


class TestWrapText:
    """Тесты для wrap_text."""

    def test_short_text_unchanged(self):
        assert wrap_text("hello") == "hello"

    def test_exact_width_unchanged(self):
        assert wrap_text("123456789012345678901234567890") == "123456789012345678901234567890"

    def test_wraps_long_text(self):
        result = wrap_text("one two three four five", width=10)
        assert "\n" in result

    def test_preserves_words(self):
        result = wrap_text("short words here", width=5)
        lines = result.split("\n")
        for line in lines:
            assert len(line) <= 5

    def test_empty_string(self):
        assert wrap_text("") == ""


class TestGroupProducts:
    """Тесты для group_products."""

    def test_groups_identical_products(self):
        products = [
            {"title": "Laptop", "price": 50000},
            {"title": "Laptop", "price": 50000},
            {"title": "Laptop", "price": 50000},
        ]
        result = group_products(products)
        assert len(result) == 1
        assert result[0]["count"] == 3

    def test_no_grouping_for_unique_products(self):
        products = [
            {"title": "A", "price": 100},
            {"title": "B", "price": 200},
        ]
        result = group_products(products)
        assert len(result) == 2
        assert all(p["count"] == 1 for p in result)

    def test_groups_by_title_and_price(self):
        products = [
            {"title": "A", "price": 100},
            {"title": "A", "price": 200},
            {"title": "A", "price": 100},
        ]
        result = group_products(products)
        assert len(result) == 2

    def test_uses_new_price_when_no_price(self):
        products = [
            {"title": "X", "new_price": 50},
            {"title": "X", "new_price": 50},
        ]
        result = group_products(products)
        assert len(result) == 1
        assert result[0]["count"] == 2

    def test_copy_does_not_share_reference(self):
        products = [
            {"title": "A", "price": 100},
            {"title": "A", "price": 100},
        ]
        result = group_products(products)
        result[0]["count"] = 99
        # products не должна быть изменена
        assert all(p.get("count", 1) == 1 for p in products)


class TestFmtPrice:
    """Тесты для _fmt_price."""

    def test_small_number(self):
        # Функция использует narrow space (U+202F) как разделитель тысяч
        assert _fmt_price(4999) == "4 999"

    def test_large_number(self):
        assert _fmt_price(1234567) == "1 234 567"

    def test_zero(self):
        assert _fmt_price(0) == "0"


class TestStatusBadge:
    """Тесты для _status_badge."""

    def test_new_status(self):
        assert _status_badge("Новый") == " \U0001f195"

    def test_used_status(self):
        # ♻️ = U+267B (Recycling Symbol) + U+FE0F (variation selector)
        assert _status_badge("Б/У") == " ♻️"

    def test_unknown_status_is_bold(self):
        result = _status_badge("Экшен")
        assert "<b>Экшен</b>" in result

    def test_empty_status(self):
        assert _status_badge("") == ""


class TestFormatProductLine:
    """Тесты для _format_product_line."""

    def test_with_url(self):
        result = _format_product_line("Laptop", "https://dns-shop.ru/test", "50 000  рб")
        assert "<a href=" in result
        assert "Laptop" in result

    def test_without_url(self):
        result = _format_product_line("Laptop", "", "50 000  рб")
        assert "<a href=" not in result
        assert "• Laptop" in result

    def test_escapes_html_in_title(self):
        result = _format_product_line("<b>Bad</b>", "", "50  рб")
        assert "<b>Bad</b>" not in result


class TestTitleWithCount:
    """Тесты для _title_with_count."""

    def test_count_one_returns_title(self):
        assert _title_with_count("Laptop", 1) == "Laptop"

    def test_count_more_than_one_appends_count(self):
        result = _title_with_count("Laptop", 5)
        assert "(5 шт.)" in result


class TestTelegramNotifier:
    """Тесты для TelegramNotifier."""

    @pytest.mark.asyncio
    async def test_send_new_products_no_bot(self):
        notifier = TelegramNotifier()
        result = await notifier.send_new_products_notification("Cat", [{"title": "A", "price": 100}])
        assert result is False

    @pytest.mark.asyncio
    async def test_send_new_products_empty_list(self):
        bot = AsyncMock()
        notifier = TelegramNotifier(bot=bot, db=Mock())
        result = await notifier.send_new_products_notification("Cat", [])
        assert result is False

    @pytest.mark.asyncio
    async def test_send_new_products_success(self):
        bot = AsyncMock()
        bot.broadcast_message.return_value = 5
        notifier = TelegramNotifier(bot=bot, db=Mock())
        products = [{"title": f"Product {i}", "price": 1000 + i, "url": ""} for i in range(3)]
        result = await notifier.send_new_products_notification("Cat", products)
        assert result is True
        bot.broadcast_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_new_products_broadcast_failure(self):
        bot = AsyncMock()
        bot.broadcast_message.side_effect = Exception("network error")
        notifier = TelegramNotifier(bot=bot, db=Mock())
        products = [{"title": "X", "price": 100, "url": ""}]
        result = await notifier.send_new_products_notification("Cat", products)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_price_changes_no_bot(self):
        notifier = TelegramNotifier()
        result = await notifier.send_price_changes_notification([{"new_price": 100, "old_price": 200}])
        assert result is False

    @pytest.mark.asyncio
    async def test_send_price_changes_empty_list(self):
        bot = AsyncMock()
        notifier = TelegramNotifier(bot=bot)
        result = await notifier.send_price_changes_notification([])
        assert result is False

    @pytest.mark.asyncio
    async def test_digest_skips_users_with_notifications_off(self):
        bot = AsyncMock()
        db = Mock()
        db.get_all_subscribers_with_settings.return_value = [
            {
                "user_id": "1",
                "city_slug": "moscow",
                "plan_type": "free",
                "notifications_on": False,
                "notify_new": True,
                "notify_price_drop": True,
                "min_price_drop_pct": 0,
            }
        ]
        notifier = TelegramNotifier(bot=bot, db=db)
        await notifier.send_digest(
            [{"title": "X", "price": 100, "city_slug": "moscow"}],
            [],
        )
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_digest_filters_by_city(self):
        bot = AsyncMock()
        bot.send_message.return_value = "ok"
        db = Mock()
        db.get_all_subscribers_with_settings.return_value = [
            {
                "user_id": "1",
                "city_slug": "moscow",
                "plan_type": "free",
                "notifications_on": True,
                "notify_new": True,
                "notify_price_drop": False,
                "min_price_drop_pct": 0,
            }
        ]
        db.get_user_categories.return_value = []
        notifier = TelegramNotifier(bot=bot, db=db)
        await notifier.send_digest(
            [{"title": "X", "price": 100, "city_slug": "spb"}],
            [],
        )
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_digest_filters_by_min_drop_pct(self):
        bot = AsyncMock()
        bot.send_message.return_value = "ok"
        db = Mock()
        db.get_all_subscribers_with_settings.return_value = [
            {
                "user_id": "1",
                "city_slug": "moscow",
                "plan_type": "free",
                "notifications_on": True,
                "notify_new": False,
                "notify_price_drop": True,
                "min_price_drop_pct": 30,
            }
        ]
        db.get_user_categories.return_value = []
        notifier = TelegramNotifier(bot=bot, db=db)
        # Старая цена 100, новая 90 → drop 10% < 30%, должно быть отфильтровано
        await notifier.send_digest(
            [],
            [{"new_price": 90, "old_price": 100}],
        )
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_digest_handles_blocked_user(self):
        bot = AsyncMock()
        bot.send_message.return_value = "blocked"
        db = Mock()
        db.get_all_subscribers_with_settings.return_value = [
            {
                "user_id": "1",
                "city_slug": "moscow",
                "plan_type": "free",
                "notifications_on": True,
                "notify_new": True,
                "notify_price_drop": False,
                "min_price_drop_pct": 0,
            }
        ]
        db.get_user_categories.return_value = []
        notifier = TelegramNotifier(bot=bot, db=db)
        await notifier.send_digest(
            [{"title": "X", "price": 100, "city_slug": "moscow"}],
            [],
        )
        db.remove_telegram_subscriber.assert_called_once_with("1")

    @pytest.mark.asyncio
    async def test_build_digest_chunks_new_products(self):
        notifier = TelegramNotifier()
        chunks = notifier._build_digest_chunks(
            [{"title": "A", "price": 100, "price_old": 200}],
            [],
        )
        assert len(chunks) == 1
        assert "\U0001f4ca" in chunks[0]
        assert "<b>" in chunks[0]

    @pytest.mark.asyncio
    async def test_build_digest_chunks_price_changes(self):
        notifier = TelegramNotifier()
        chunks = notifier._build_digest_chunks(
            [],
            [{"title": "Product", "new_price": 100, "old_price": 200}],
        )
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_build_digest_chunks_empty(self):
        notifier = TelegramNotifier()
        chunks = notifier._build_digest_chunks([], [])
        assert chunks == []

    @pytest.mark.asyncio
    async def test_format_digest_returns_joined_chunks(self):
        notifier = TelegramNotifier()
        result = notifier._format_digest(
            [{"title": "A", "price": 100, "price_old": 200}],
            [],
        )
        assert "A" in result

    @pytest.mark.asyncio
    async def test_send_daily_report_no_bot(self):
        notifier = TelegramNotifier()
        result = await notifier.send_daily_report_to_user("1", [], [])
        assert result == "fail"

    @pytest.mark.asyncio
    async def test_send_daily_report_empty(self):
        bot = AsyncMock()
        notifier = TelegramNotifier(bot=bot, db=Mock())
        result = await notifier.send_daily_report_to_user("1", [], [])
        assert result == "empty"

    @pytest.mark.asyncio
    async def test_send_daily_report_fail_on_blocked(self):
        bot = AsyncMock()
        bot.send_message.return_value = "blocked"
        db = Mock()
        notifier = TelegramNotifier(bot=bot, db=db)
        result = await notifier.send_daily_report_to_user(
            "1",
            [{"title": "A", "price": 100}],
            [],
        )
        assert result == "blocked"

    @pytest.mark.asyncio
    async def test_admin_alert_no_admin_id(self):
        bot = Mock(admin_id=None)
        notifier = TelegramNotifier(bot=bot, db=Mock())
        await notifier.send_admin_alert("test", msg_type="error")

    @pytest.mark.asyncio
    async def test_admin_alert_error_when_disabled(self):
        bot = Mock(admin_id="admin1")
        db = Mock()
        db.get_all_subscribers_with_settings.return_value = [
            {
                "user_id": "admin1",
                "city_slug": "moscow",
                "plan_type": "free",
                "notifications_on": True,
                "notify_new": True,
                "notify_price_drop": True,
                "min_price_drop_pct": 0,
                "notify_errors": False,
                "notify_parse_finish": True,
            }
        ]
        notifier = TelegramNotifier(bot=bot, db=db)
        await notifier.send_admin_alert("error msg", msg_type="error")
        bot.send_admin_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalidate_admin_settings(self):
        bot = Mock(admin_id="admin1")
        db = Mock()
        notifier = TelegramNotifier(bot=bot, db=db)
        # Установим кеш
        notifier._admin_settings = {"test": True}
        notifier._invalidate_admin_settings()
        assert notifier._admin_settings is None

    @pytest.mark.asyncio
    async def test_close(self):
        bot = AsyncMock()
        notifier = TelegramNotifier(bot=bot, db=Mock())
        await notifier.close()
        bot.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_admin_parse_finish(self):
        bot = AsyncMock(admin_id="admin1")
        db = Mock()
        # send_admin_alert → _get_admin_settings iterates over subscribers
        db.get_all_subscribers_with_settings.return_value = [
            {"user_id": "admin1", "plan_type": "free", "notifications_on": True, "notify_errors": True}
        ]
        notifier = TelegramNotifier(bot=bot, db=db)
        await notifier.send_admin_parse_finish(
            new_cnt=5, updated_cnt=3, price_changed=2, total_db=100, prev_cnt=90, delta=10, city_name="Moscow",
        )
        bot.send_admin_message.assert_called_once()
