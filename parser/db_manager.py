"""
Менеджер БД для хранения товаров и обновления цен.
"""

import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from parser.models import Product
from utils.logger import logger


class DBManager:
    """Работа с SQLite: товары и цены."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _backup_db(self) -> None:
        """Создает бэкап БД перед миграцией."""
        if not self.db_path.exists():
            return

        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.db_path.stem}_backup_{timestamp}.db"

        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info("Создан бэкап БД: %s", backup_path)
        except Exception as exc:
            logger.error("Ошибка при создании бэкапа БД: %s", exc)

    def _init_db(self) -> None:
        """Создает таблицы если их нет. Создает бэкап только перед реальными миграциями."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    uuid TEXT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    category_id TEXT,
                    category_name TEXT,
                    current_price INTEGER,
                    previous_price INTEGER,
                    updated_at TEXT,
                    created_at TEXT
                )
            """)

            cursor = conn.execute("PRAGMA table_info(products)")
            product_cols = [row[1] for row in cursor.fetchall()]

            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    price INTEGER,
                    timestamp TEXT,
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS category_state (
                    category_id TEXT PRIMARY KEY,
                    category_name TEXT,
                    last_product_count INTEGER,
                    last_checked_at TEXT
                )
            """)

            cursor = conn.execute("PRAGMA table_info(category_state)")
            category_cols = [row[1] for row in cursor.fetchall()]

            need_migration = 'uuid' not in product_cols or 'uuid_hash' not in category_cols or 'status' not in product_cols
            if need_migration:
                self._backup_db()

            if 'uuid' not in product_cols:
                try:
                    conn.execute("ALTER TABLE products ADD COLUMN uuid TEXT")
                    logger.info("Добавлен столбец uuid в таблицу products")
                except sqlite3.OperationalError:
                    pass

            if 'uuid_hash' not in category_cols:
                try:
                    conn.execute("ALTER TABLE category_state ADD COLUMN uuid_hash TEXT")
                    logger.info("Добавлен столбец uuid_hash в таблицу category_state")
                except sqlite3.OperationalError:
                    pass

            if 'status' not in product_cols:
                try:
                    conn.execute("ALTER TABLE products ADD COLUMN status TEXT DEFAULT ''")
                    conn.execute("UPDATE category_state SET uuid_hash = NULL")
                    logger.info("Добавлен столбец status, uuid_hash сброшен для перемаркировки товаров")
                except sqlite3.OperationalError:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS telegram_subscribers (
                    user_id TEXT PRIMARY KEY,
                    subscribed_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_uuid ON products(uuid)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_product_id ON price_history(product_id)")
            conn.commit()
        logger.debug("БД инициализирована: %s", self.db_path)

    def upsert_products(self, products: list[Product]) -> tuple[int, list[dict]]:
        """
        Вставляет или обновляет товары.
        Возвращает (количество обновленных записей, список изменений цен).
        """
        if not products:
            return 0, []

        now = datetime.now(timezone.utc).isoformat()
        price_changes = []

        with sqlite3.connect(self.db_path) as conn:
            # Один batch-SELECT вместо N+1 запросов
            uuids = [p.uuid for p in products]
            placeholders = ",".join("?" * len(uuids))
            cursor = conn.execute(
                f"SELECT uuid, current_price FROM products WHERE uuid IN ({placeholders})",
                uuids,
            )
            existing = {row[0]: row[1] for row in cursor.fetchall()}

            for prod in products:
                if prod.uuid in existing:
                    conn.execute("""
                        UPDATE products
                        SET id = ?, title = ?, current_price = ?, previous_price = ?,
                            category_id = ?, category_name = ?, status = ?, updated_at = ?
                        WHERE uuid = ?
                    """, (
                        prod.id, prod.title, prod.price, prod.price_old,
                        prod.category_id, prod.category_name, prod.status, now, prod.uuid
                    ))
                    if existing[prod.uuid] != prod.price:
                        conn.execute("""
                            INSERT INTO price_history (product_id, price, timestamp)
                            VALUES (?, ?, ?)
                        """, (prod.uuid, prod.price, now))
                        price_changes.append({
                            "title": prod.title,
                            "url": prod.url,
                            "new_price": prod.price,
                            "old_price": existing[prod.uuid],
                            "price_old": prod.price_old,
                            "status": prod.status,
                        })
                else:
                    conn.execute("""
                        INSERT INTO products
                        (id, uuid, title, url, category_id, category_name,
                         current_price, previous_price, status, updated_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        prod.id, prod.uuid, prod.title, prod.url, prod.category_id,
                        prod.category_name, prod.price, prod.price_old, prod.status, now, now
                    ))

            conn.commit()

        return len(products), price_changes

    def delete_products_not_in_uuids(self, category_id: str, current_uuids: list[str]) -> int:
        """Удаляет из БД товары категории, которых нет в current_uuids (проданы)."""
        if not current_uuids:
            return 0
        placeholders = ",".join("?" * len(current_uuids))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"DELETE FROM products WHERE category_id = ? AND uuid NOT IN ({placeholders})",
                [category_id] + list(current_uuids),
            )
            conn.commit()
            return cursor.rowcount

    def get_product_count(self) -> int:
        """Возвращает количество товаров в БД."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM products")
            return cursor.fetchone()[0]

    def get_products_by_category(self, category_id: str) -> list[Product]:
        """Получает товары по категории."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, uuid, title, url, category_id, category_name, current_price, previous_price
                FROM products WHERE category_id = ?
            """, (category_id,))
            rows = cursor.fetchall()

        return [
            Product(
                id=row[0],
                uuid=row[1],
                title=row[2],
                url=row[3],
                category_id=row[4],
                category_name=row[5],
                price=row[6],
                price_old=row[7],
            )
            for row in rows
        ]

    def get_price_drops(self, min_drop_percent: float = 10.0) -> list[dict]:
        """Получает товары с максимальной скидкой."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, title, current_price, previous_price,
                       ROUND(100.0 * (previous_price - current_price) / previous_price, 1) as drop_percent
                FROM products
                WHERE previous_price > 0 AND current_price < previous_price
                      AND ROUND(100.0 * (previous_price - current_price) / previous_price, 1) >= ?
                ORDER BY drop_percent DESC
                LIMIT 50
            """, (min_drop_percent,))
            rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "title": row[1],
                "current_price": row[2],
                "previous_price": row[3],
                "drop_percent": row[4],
            }
            for row in rows
        ]

    def get_category_state(self, category_id: str) -> dict | None:
        """Получает последнее состояние категории."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT category_id, category_name, last_product_count, uuid_hash, last_checked_at
                FROM category_state WHERE category_id = ?
            """, (category_id,))
            row = cursor.fetchone()

        if row:
            return {
                "category_id": row[0],
                "category_name": row[1],
                "last_product_count": row[2],
                "uuid_hash": row[3],
                "last_checked_at": row[4],
            }
        return None

    def update_category_state(
        self, category_id: str, category_name: str, product_count: int, uuids: list[str] = None
    ) -> None:
        """Обновляет последнее состояние категории."""
        uuid_hash = None
        if uuids is not None:
            uuid_hash = hashlib.md5(','.join(sorted(uuids)).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO category_state
                (category_id, category_name, last_product_count, uuid_hash, last_checked_at)
                VALUES (?, ?, ?, ?, ?)
            """, (category_id, category_name, product_count, uuid_hash, now))
            conn.commit()

    def get_new_products_in_category(
        self, category_id: str, all_product_ids: list[str]
    ) -> list[str]:
        """
        Возвращает UUID товаров которых не было в этой категории ранее.
        all_product_ids - список всех текущих UUID товаров в категории.
        """
        if not all_product_ids:
            return []

        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" * len(all_product_ids))
            cursor = conn.execute(f"""
                SELECT uuid FROM products
                WHERE category_id = ? AND uuid IN ({placeholders})
            """, [category_id] + all_product_ids)
            existing_ids = set(row[0] for row in cursor.fetchall())

        # Новые товары = все текущие минус существующие
        new_ids = [pid for pid in all_product_ids if pid not in existing_ids]
        return new_ids

    def add_telegram_subscriber(self, user_id: str) -> None:
        """Добавляет Telegram подписчика."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO telegram_subscribers (user_id, subscribed_at)
                VALUES (?, ?)
            """, (user_id, now))
            conn.commit()

    def remove_telegram_subscriber(self, user_id: str) -> None:
        """Удаляет Telegram подписчика."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM telegram_subscribers WHERE user_id = ?
            """, (user_id,))
            conn.commit()

    def get_telegram_subscribers(self) -> list[str]:
        """Получает список всех Telegram подписчиков."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT user_id FROM telegram_subscribers
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_all_category_states(self) -> dict[str, int]:
        """Возвращает {category_id: last_product_count} для всех категорий в БД."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT category_id, last_product_count FROM category_state
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_today_discounts(self) -> list[dict]:
        """Получает товары с обновленными ценами за сегодня (была скидка)."""
        from datetime import date
        today = date.today().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, title, url, current_price, previous_price, category_name,
                       ROUND(100.0 * (previous_price - current_price) / previous_price, 1) as drop_percent
                FROM products
                WHERE DATE(updated_at) = ? AND previous_price > 0 AND current_price < previous_price
                ORDER BY drop_percent DESC
            """, (today,))
            rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "title": row[1],
                "url": row[2],
                "current_price": row[3],
                "previous_price": row[4],
                "category": row[5],
                "drop_percent": row[6],
            }
            for row in rows
        ]

    def close(self) -> None:
        """Нет-оп: все методы используют with sqlite3.connect(), соединения закрываются автоматически."""
