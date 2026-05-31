"""
Тесты для simple_dns_parser: вспомогательные функции,
_parse_state, _is_qrator_challenge, _random_container_id.
Большая часть уже покрыта в test_parser_utils.py — это добавляет
покрытие отсутствующих ветвей и edge cases.
"""

import json
import pytest
from unittest.mock import AsyncMock, Mock, patch

from parser.simple_dns_parser import (
    _random_container_id,
    _is_qrator_challenge,
    _PRODUCT_UUID_RE,
    _UUID_RE,
)


class TestRandomContainerId:
    """Тесты для генерации container ID."""

    def test_returns_as_prefix(self):
        cid = _random_container_id()
        assert cid.startswith("as-")

    def test_is_9_chars_total(self):
        cid = _random_container_id()
        assert len(cid) == 9  # "as-" + 6 chars

    def test_suffix_contains_alphanumeric(self):
        cid = _random_container_id()
        suffix = cid[3:]
        assert all(c.isalnum() for c in suffix)

    def test_different_calls_different_ids(self):
        ids = {_random_container_id() for _ in range(50)}
        # Вероятность коллизии мала, но проверим разнообразие
        assert len(ids) >= 48


class TestIsQratorChallenge:
    """Тесты для проверки QRATOR маркера."""

    def test_detects_qrator_challenge(self):
        html = '<html><body>qauth_handle_validate_success</body></html>'
        assert _is_qrator_challenge(html) is True

    def test_returns_false_when_marker_missing(self):
        assert _is_qrator_challenge("<html>nothing here</html>") is False

    def test_returns_false_empty_string(self):
        assert _is_qrator_challenge("") is False


class TestProductUuidRegex:
    """Тесты для regex продукта."""

    def test_matches_product_uuid_in_json(self):
        text = '\\"id\\":\\"12345678-1234-1234-1234-123456789012\\",\\"type\\":4'
        m = _PRODUCT_UUID_RE.search(text)
        assert m is not None
        assert m.group(1) == "12345678-1234-1234-1234-123456789012"

    def test_does_not_match_non_product_type(self):
        text = '\\"id\\":\\"12345678-1234-1234-1234-123456789012\\",\\"type\\":3'
        m = _PRODUCT_UUID_RE.search(text)
        assert m is None

    def test_lowercases_match(self):
        text = '\\"id\\":\\"ABCD1234-EFAB-CDEF-1234-567890ABCDEF\\",\\"type\\":4'
        m = _PRODUCT_UUID_RE.search(text)
        assert m is not None


class TestParseState:
    """Тесты для SimpleDNSParser._parse_state."""

    def _make_parser(self):
        sm = Mock()
        parser_cls = __import__("parser.simple_dns_parser", fromlist=["SimpleDNSParser"])
        return parser_cls.SimpleDNSParser(sm, city_slug="moscow")

    def test_parses_valid_state(self):
        parser = self._make_parser()
        state = {
            "id": "as-abc123",
            "data": {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "Test Product",
                "price": {"current": 5000, "previous": 7000},
            },
        }
        container_map = {"as-abc123": "11111111-1111-1111-1111-111111111111"}
        result = parser._parse_state(state, container_map, "cat-1", "Cat")
        assert result is not None
        assert result.title == "Test Product"
        assert result.price == 5000
        assert result.price_old == 7000

    def test_returns_none_when_no_uuid(self):
        parser = self._make_parser()
        state = {"id": "as-abc123", "data": {}}
        container_map = {}
        result = parser._parse_state(state, container_map, "cat-1", "Cat")
        assert result is None

    def test_returns_none_when_no_name(self):
        parser = self._make_parser()
        state = {"id": "as-abc123", "data": {"id": "uuid-1"}}
        container_map = {"as-abc123": "uuid-1"}
        result = parser._parse_state(state, container_map, "cat-1", "Cat")
        assert result is None

    def test_uses_container_map_for_uuid(self):
        parser = self._make_parser()
        state = {"id": "as-xyz", "data": {"name": "Mapped Product"}}  # data без id
        container_map = {"as-xyz": "container-uuid"}
        result = parser._parse_state(state, container_map, "cat-1", "Cat")
        assert result is not None
        assert result.uuid == "container-uuid"

    def test_handles_zero_price(self):
        parser = self._make_parser()
        state = {
            "id": "as-abc",
            "data": {
                "id": "u1",
                "name": "Free",
                "price": {"current": 0, "previous": 0},
            },
        }
        container_map = {"as-abc": "u1"}
        result = parser._parse_state(state, container_map, "c1", "C")
        assert result is not None
        assert result.price == 0

    def test_handles_missing_price_obj(self):
        parser = self._make_parser()
        state = {"id": "as-abc", "data": {"id": "u1", "name": "X", "price": None}}
        container_map = {"as-abc": "u1"}
        result = parser._parse_state(state, container_map, "c1", "C")
        assert result is not None
        assert result.price == 0

    def test_handles_invalid_price_type(self):
        parser = self._make_parser()
        state = {"id": "as-abc", "data": {"id": "u1", "name": "X", "price": {"current": "bad"}}}
        container_map = {"as-abc": "u1"}
        result = parser._parse_state(state, container_map, "c1", "C")
        # int("bad") должен выбросить ValueError → _parse_state вернёт None
        assert result is None

    def test_uses_uuid_to_status(self):
        parser = self._make_parser()
        state = {
            "id": "as-abc",
            "data": {"id": "u1", "name": "X", "price": {"current": 100}},
        }
        container_map = {"as-abc": "u1"}
        result = parser._parse_state(state, container_map, "c1", "C", {"u1": "Новый"})
        assert result.status == "Новый"

    def test_handles_general_exception(self):
        parser = self._make_parser()
        # Состояние с non-dict data вызовет AttributeError при .get()
        state = None  # type: ignore
        container_map = {}
        result = parser._parse_state(state, container_map, "c1", "C")
        assert result is None


class TestCategoryParsingJson:
    """Тесты парсинга категорий из JSON."""

    @pytest.mark.asyncio
    async def test_parses_left_blocks_categories(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        sm._cookies = {}
        sm._build_headers.return_value = {}
        sm._extract_cookies_from_response = Mock()
        sm.request = AsyncMock()

        html = (
            '{"data": {"blocks": {'
            '"left": [{"label": "Категории", '
            '"variants": [{"id": "cat-a", "label": "Laptops", "count": 5}, '
            '{"id": "cat-b", "label": "Phones", "count": 3}]}]}}}'
        )

        response = Mock(status=200, content_type="application/json")
        response.raise_for_status = Mock()
        response.text = AsyncMock(return_value=html)
        response.json = AsyncMock(return_value=json.loads(html))
        sm.request.return_value.__aenter__ = AsyncMock(return_value=response)
        sm.request.return_value.__aexit__ = AsyncMock(return_value=None)

        parser = SimpleDNSParser(sm, city_slug="test")
        cats = await parser.fetch_categories()
        assert len(cats) == 2


class TestCategoryParsingFallback:
    """Тесты fallback парсинга категорий из HTML."""

    @pytest.mark.asyncio
    async def test_fallback_uuid_parsing(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        sm._cookies = {}
        sm._build_headers.return_value = {}
        sm._extract_cookies_from_response = Mock()
        sm.request = AsyncMock()

        html = '<div id="cat-123">Laptops</div><div id="456abcde-f012-3456-7890-abcdef123456">Phones</div>'
        # HTML не является JSON → fallback парсит UUID

        response = Mock(status=200, content_type="text/html")
        response.raise_for_status = Mock()
        response.text = AsyncMock(return_value=html)
        sm.request.return_value.__aenter__ = AsyncMock(return_value=response)
        sm.request.return_value.__aexit__ = AsyncMock(return_value=None)

        parser = SimpleDNSParser(sm, city_slug="test")
        cats = await parser.fetch_categories()
        # Fallback должен найти UUIDs из HTML
        assert len(cats) >= 1


class TestFetchProductUuids:
    """Тесты для fetch_product_uuids."""

    @pytest.mark.asyncio
    async def test_empty_when_exception(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        sm._cookies = {}
        sm.request = AsyncMock()
        sm.request.side_effect = Exception("network")

        parser = SimpleDNSParser(sm, city_slug="test")
        uuids = await parser.fetch_product_uuids("cat-1", expected_count=10)
        assert uuids == []


class TestFetchProductsDetails:
    """Тесты для fetch_products_details."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        sm._cookies = {}
        parser = SimpleDNSParser(sm, city_slug="test")
        products = await parser.fetch_products_details([], "cat-1", "Cat")
        assert products == []

    @pytest.mark.asyncio
    async def test_skips_failed_batches(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        sm._cookies = {}
        sm.request = AsyncMock()
        sm.request.side_effect = Exception("batch fail")

        parser = SimpleDNSParser(sm, city_slug="test")
        products = await parser.fetch_products_details(["uuid1", "uuid2"], "cat-1", "Cat")
        # Батч должен быть пропущен (continue) → пустой список
        assert products == []


class TestFetchProducts:
    """Тесты для fetch_products (шаги 2+3)."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_uuids(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        sm._cookies = {}
        sm.request = AsyncMock()
        sm.request.side_effect = Exception("no uuids")

        parser = SimpleDNSParser(sm, city_slug="test")
        products = await parser.fetch_products("cat-1", "Cat")
        assert products == []


class TestClose:
    """Тесты для close()."""

    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        from parser.simple_dns_parser import SimpleDNSParser

        sm = Mock()
        parser = SimpleDNSParser(sm, city_slug="test")
        # Не должна выбросить исключение
        await parser.close()


class TestCheckStatus:
    """Тесты для _check_status."""

    def test_cookies_expired_401(self):
        from parser.simple_dns_parser import SimpleDNSParser
        from parser.exceptions import CookiesExpiredError

        sm = Mock()
        parser = SimpleDNSParser(sm, city_slug="test")
        resp = Mock(status=401)
        with pytest.raises(CookiesExpiredError):
            parser._check_status(resp, "http://test.com")

    def test_cookies_expired_403(self):
        from parser.simple_dns_parser import SimpleDNSParser
        from parser.exceptions import CookiesExpiredError

        sm = Mock()
        parser = SimpleDNSParser(sm, city_slug="test")
        resp = Mock(status=403)
        with pytest.raises(CookiesExpiredError):
            parser._check_status(resp, "http://test.com")

    def test_rate_limit_429(self):
        from parser.simple_dns_parser import SimpleDNSParser
        import aiohttp

        sm = Mock()
        parser = SimpleDNSParser(sm, city_slug="test")
        resp = Mock(status=429)
        with pytest.raises(aiohttp.ClientError):
            parser._check_status(resp, "http://test.com")


class TestProductUuidRegexEdgeCases:
    """Тесты для regex с edge cases."""

    def test_uuid_re_matches_lowercase(self):
        text = "abc12345-def0-1234-abcd-ef0123456789"
        assert _UUID_RE.search(text) is not None

    def test_uuid_re_matches_mixed_case(self):
        text = "ABCDEF12-3456-7890-abcd-ef0123456789"
        assert _UUID_RE.search(text) is not None

    def test_product_uuid_only_type4(self):
        text = '\\"id\\":\\"12345678-1234-1234-1234-123456789012\\",\\"type\\":4'
        assert _PRODUCT_UUID_RE.search(text) is not None

        # type:3 (рекомендации) не должен совпадать
        text_rec = '\\"id\\":\\"12345678-1234-1234-1234-123456789012\\",\\"type\\":3'
        assert _PRODUCT_UUID_RE.search(text_rec) is None
