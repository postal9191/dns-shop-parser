import pytest

from services.telegram_notifier import (
    TelegramNotifier,
    _format_product_line,
    group_products,
    wrap_text,
)


class TestWrapText:
    def test_wrap_text_short_text_unchanged(self):
        """wrap_text - короткий текст возвращается as-is."""
        text = "Короткий текст"
        result = wrap_text(text, width=60)

        assert result == text

    def test_wrap_text_long_text_wrapped(self):
        """wrap_text - длинный текст разбивается по словам."""
        text = "Это очень длинный текст который должен быть разбит на несколько строк"
        result = wrap_text(text, width=20)

        lines = result.split("\n")
        assert len(lines) > 1
        # Каждая строка должна быть не более 20 символов
        for line in lines:
            assert len(line) <= 20

    def test_wrap_text_preserves_words(self):
        """wrap_text - не разрезает слова пополам."""
        text = "Это очень длинный текст"
        result = wrap_text(text, width=10)

        words = text.split()
        for word in words:
            assert word in result

    def test_wrap_text_empty_string(self):
        """wrap_text - пустая строка."""
        result = wrap_text("", width=60)

        assert result == ""


class TestGroupProducts:
    def test_group_products_same_title_and_price(self):
        """group_products - одинаковые товары группируются."""
        products = [
            {"title": "Товар A", "price": 100},
            {"title": "Товар A", "price": 100},
            {"title": "Товар A", "price": 100},
        ]

        result = group_products(products)

        assert len(result) == 1
        assert result[0]["count"] == 3
        assert result[0]["title"] == "Товар A"

    def test_group_products_different_prices(self):
        """group_products - одинаковые товары с разными ценами - отдельные записи."""
        products = [
            {"title": "Товар A", "price": 100},
            {"title": "Товар A", "price": 200},
        ]

        result = group_products(products)

        assert len(result) == 2
        assert result[0]["count"] == 1
        assert result[1]["count"] == 1

    def test_group_products_with_new_price_key(self):
        """group_products - работает с ключом 'new_price' если 'price' нет."""
        products = [
            {"title": "Товар A", "new_price": 100},
            {"title": "Товар A", "new_price": 100},
        ]

        result = group_products(products)

        assert len(result) == 1
        assert result[0]["count"] == 2

    def test_group_products_empty_list(self):
        """group_products - пустой список."""
        result = group_products([])

        assert result == []


class TestFormatProductLine:
    def test_format_product_line_with_url(self):
        """_format_product_line - формат с URL."""
        line = _format_product_line("Товар", "https://example.com", "1000 ₽")

        assert '<a href="https://example.com">Товар</a>' in line
        assert "💰 1000 ₽" in line

    def test_format_product_line_without_url(self):
        """_format_product_line - без URL (пустая строка)."""
        line = _format_product_line("Товар", "", "1000 ₽")

        assert "<a " not in line
        assert "• Товар" in line
        assert "💰 1000 ₽" in line

    def test_format_product_line_none_url(self):
        """_format_product_line - URL=None."""
        line = _format_product_line("Товар", None, "1000 ₽")

        assert "<a " not in line or 'href="None"' in line

    def test_format_product_line_contains_newlines(self):
        """_format_product_line - содержит переносы строк."""
        line = _format_product_line("Товар", "https://example.com", "1000 ₽")

        assert line.count("\n") >= 2


class TestTelegramNotifier:
    def test_telegram_notifier_disabled_when_bot_none(self):
        """TelegramNotifier(bot=None) - disabled."""
        notifier = TelegramNotifier(bot=None)

        assert notifier.enabled is False

    @pytest.mark.asyncio
    async def test_send_new_products_notification_disabled(self):
        """TelegramNotifier.send_new_products_notification - возвращает False если bot=None."""
        notifier = TelegramNotifier(bot=None)

        result = await notifier.send_new_products_notification(
            "Категория",
            [{"title": "Товар", "price": 100}],
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_new_products_notification_empty_products(self):
        """TelegramNotifier.send_new_products_notification - False если товаров нет."""
        notifier = TelegramNotifier(bot=None)

        result = await notifier.send_new_products_notification("Категория", [])

        assert result is False

    @pytest.mark.asyncio
    async def test_send_price_changes_notification_disabled(self):
        """TelegramNotifier.send_price_changes_notification - False если bot=None."""
        notifier = TelegramNotifier(bot=None)

        result = await notifier.send_price_changes_notification(
            [{"title": "Товар", "new_price": 100, "old_price": 200}],
        )

        assert result is False
