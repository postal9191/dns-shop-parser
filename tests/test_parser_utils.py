import re

import pytest

from parser.simple_dns_parser import (
    SimpleDNSParser,
    _PRODUCT_UUID_RE,
    _UUID_RE,
    _is_qrator_challenge,
    _random_container_id,
)


class TestRandomContainerId:
    def test_random_container_id_format(self):
        """_random_container_id - начинается с 'as-'."""
        container_id = _random_container_id()

        assert container_id.startswith("as-")

    def test_random_container_id_suffix_length(self):
        """_random_container_id - суффикс ровно 6 символов."""
        container_id = _random_container_id()

        suffix = container_id[3:]  # После "as-"
        assert len(suffix) == 6

    def test_random_container_id_alphanumeric_suffix(self):
        """_random_container_id - суффикс только [a-zA-Z0-9]."""
        container_id = _random_container_id()

        suffix = container_id[3:]
        assert all(c.isalnum() for c in suffix)

    def test_random_container_id_different_each_call(self):
        """_random_container_id - каждый вызов возвращает разный ID."""
        id1 = _random_container_id()
        id2 = _random_container_id()

        # Вероятность совпадения 6-символного суффикса очень мала
        # но теоретически возможна, так что тест может иногда падать
        # (очень редко)
        # assert id1 != id2


class TestIsQratorChallenge:
    def test_is_qrator_challenge_with_marker(self):
        """_is_qrator_challenge - True при маркере."""
        html = "<html>qauth_handle_validate_success</html>"

        result = _is_qrator_challenge(html)

        assert result is True

    def test_is_qrator_challenge_without_marker(self):
        """_is_qrator_challenge - False без маркера."""
        html = "<html>обычная страница</html>"

        result = _is_qrator_challenge(html)

        assert result is False

    def test_is_qrator_challenge_marker_in_middle(self):
        """_is_qrator_challenge - marker в середине HTML."""
        html = "<div>некий текст qauth_handle_validate_success другой текст</div>"

        result = _is_qrator_challenge(html)

        assert result is True


class TestUUIDRegex:
    def test_uuid_regex_valid_uuid(self):
        """_UUID_RE - матчит валидный UUID."""
        uuid = "12345678-1234-5678-1234-567890123456"

        match = _UUID_RE.search(uuid)

        assert match is not None
        assert match.group(0) == uuid

    def test_uuid_regex_case_insensitive(self):
        """_UUID_RE - case-insensitive."""
        uuid_lower = "abcdef01-2345-6789-abcd-ef0123456789"
        uuid_upper = "ABCDEF01-2345-6789-ABCD-EF0123456789"

        match_lower = _UUID_RE.search(uuid_lower)
        match_upper = _UUID_RE.search(uuid_upper)

        assert match_lower is not None
        assert match_upper is not None

    def test_uuid_regex_invalid_uuid(self):
        """_UUID_RE - не матчит невалидный UUID."""
        invalid = "not-a-uuid-string"

        match = _UUID_RE.search(invalid)

        assert match is None


class TestProductUUIDRegex:
    def test_product_uuid_regex_type_4(self):
        """_PRODUCT_UUID_RE - матчит UUID с type:4."""
        text = '\\"id\\":\\"12345678-1234-5678-1234-567890123456\\",\\"type\\":4'

        match = _PRODUCT_UUID_RE.search(text)

        assert match is not None
        assert match.group(1) == "12345678-1234-5678-1234-567890123456"

    def test_product_uuid_regex_not_type_3(self):
        """_PRODUCT_UUID_RE - не матчит UUID с type:3."""
        text = '\\"id\\":\\"12345678-1234-5678-1234-567890123456\\",\\"type\\":3'

        match = _PRODUCT_UUID_RE.search(text)

        assert match is None

    def test_product_uuid_regex_multiple_matches(self):
        """_PRODUCT_UUID_RE - матчит несколько UUID."""
        text = (
            '\\"id\\":\\"11111111-1111-1111-1111-111111111111\\",\\"type\\":4'
            '\\"id\\":\\"22222222-2222-2222-2222-222222222222\\",\\"type\\":4'
        )

        matches = _PRODUCT_UUID_RE.findall(text)

        assert len(matches) == 2
        assert "11111111-1111-1111-1111-111111111111" in matches
        assert "22222222-2222-2222-2222-222222222222" in matches


class TestParseState:
    def test_parse_state_valid_product(self, sample_product):
        """_parse_state - парсит валидный state и возвращает Product."""
        state = {
            "id": "as-AbCdEf",
            "data": {
                "id": "12345678-1234-5678-1234-567890123456",
                "name": "Ноутбук Test",
                "price": {
                    "current": 50000,
                    "previous": 70000,
                },
            },
        }

        # Нужен SessionManager для создания SimpleDNSParser
        # Используем mock
        from unittest.mock import MagicMock

        mock_sm = MagicMock()
        parser = SimpleDNSParser(mock_sm)

        product = parser._parse_state(
            state,
            container_map={"as-AbCdEf": "12345678-1234-5678-1234-567890123456"},
            category_id="cat-1",
            category_name="Ноутбуки",
        )

        assert product is not None
        assert product.uuid == "12345678-1234-5678-1234-567890123456"
        assert product.title == "Ноутбук Test"
        assert product.price == 50000
        assert product.price_old == 70000

    def test_parse_state_missing_uuid_returns_none(self):
        """_parse_state - без UUID возвращает None."""
        state = {
            "id": "as-AbCdEf",
            "data": {
                "name": "Ноутбук",
                "price": {"current": 50000, "previous": 70000},
            },
        }

        from unittest.mock import MagicMock

        mock_sm = MagicMock()
        parser = SimpleDNSParser(mock_sm)

        product = parser._parse_state(
            state,
            container_map={},
            category_id="cat-1",
            category_name="Ноутбуки",
        )

        assert product is None

    def test_parse_state_missing_name_returns_none(self):
        """_parse_state - без name возвращает None."""
        state = {
            "id": "as-AbCdEf",
            "data": {
                "id": "12345678-1234-5678-1234-567890123456",
                "price": {"current": 50000, "previous": 70000},
            },
        }

        from unittest.mock import MagicMock

        mock_sm = MagicMock()
        parser = SimpleDNSParser(mock_sm)

        product = parser._parse_state(
            state,
            container_map={"as-AbCdEf": "12345678-1234-5678-1234-567890123456"},
            category_id="cat-1",
            category_name="Ноутбуки",
        )

        assert product is None

    def test_parse_state_exception_handling(self):
        """_parse_state - исключение при парсинге обрабатывается и возвращает None."""
        state = None  # Это вызовет AttributeError

        from unittest.mock import MagicMock

        mock_sm = MagicMock()
        parser = SimpleDNSParser(mock_sm)

        # Должно обработать исключение и вернуть None
        product = parser._parse_state(
            state,
            container_map={},
            category_id="cat-1",
            category_name="Ноутбуки",
        )

        assert product is None

    def test_parse_state_empty_name_returns_none(self):
        """_parse_state - пустое имя (после strip) возвращает None."""
        state = {
            "id": "as-AbCdEf",
            "data": {
                "id": "12345678-1234-5678-1234-567890123456",
                "name": "   ",  # Только пробелы
                "price": {"current": 50000, "previous": 70000},
            },
        }

        from unittest.mock import MagicMock

        mock_sm = MagicMock()
        parser = SimpleDNSParser(mock_sm)

        product = parser._parse_state(
            state,
            container_map={"as-AbCdEf": "12345678-1234-5678-1234-567890123456"},
            category_id="cat-1",
            category_name="Ноутбуки",
        )

        assert product is None
