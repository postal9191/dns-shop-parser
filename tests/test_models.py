import pytest

from parser.models import Category, Product


def test_product_creation_with_required_fields():
    """Product создаётся с обязательными полями."""
    product = Product(
        id="as-AbCdEf",
        uuid="12345678-1234-1234-1234-123456789012",
        title="Ноутбук",
        price=50000,
        price_old=70000,
        url="https://example.com",
    )

    assert product.id == "as-AbCdEf"
    assert product.uuid == "12345678-1234-1234-1234-123456789012"
    assert product.title == "Ноутбук"
    assert product.price == 50000
    assert product.price_old == 70000
    assert product.url == "https://example.com"


def test_product_has_default_optional_fields():
    """Product имеет дефолты для опциональных полей."""
    product = Product(
        id="as-AbCdEf",
        uuid="12345678-1234-1234-1234-123456789012",
        title="Ноутбук",
        price=50000,
        price_old=70000,
        url="https://example.com",
    )

    assert product.category_id == ""
    assert product.category_name == ""
    assert product.status == ""


def test_product_equality():
    """Два одинаковых Product равны."""
    p1 = Product(
        id="as-AbCdEf",
        uuid="uuid-1",
        title="Товар",
        price=100,
        price_old=200,
        url="https://example.com",
    )
    p2 = Product(
        id="as-AbCdEf",
        uuid="uuid-1",
        title="Товар",
        price=100,
        price_old=200,
        url="https://example.com",
    )

    assert p1 == p2


def test_category_creation():
    """Category создаётся со всеми полями."""
    category = Category(id="cat-123", label="Ноутбуки", count=42)

    assert category.id == "cat-123"
    assert category.label == "Ноутбуки"
    assert category.count == 42


def test_category_equality():
    """Две одинаковые Category равны."""
    c1 = Category(id="cat-1", label="Категория", count=10)
    c2 = Category(id="cat-1", label="Категория", count=10)

    assert c1 == c2
