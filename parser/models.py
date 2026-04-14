from dataclasses import dataclass


@dataclass
class Category:
    id: str
    label: str
    count: int


@dataclass
class Product:
    id: str           # короткий ID (as-upHxKD)
    uuid: str         # UUID товара (9514e56e-1c8c-...)
    title: str
    price: int        # текущая цена
    price_old: int    # обычная цена (до уценки)
    url: str
    category_id: str = ""
    category_name: str = ""
