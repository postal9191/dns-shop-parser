"""
Менеджер БД для хранения товаров и обновления цен.
"""

import hashlib
import json
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
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    language_code TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    subscribed_at TEXT,
                    updated_at TEXT
                )
            """)
            cursor = conn.execute("PRAGMA table_info(telegram_subscribers)")
            sub_cols = [row[1] for row in cursor.fetchall()]
            sub_migrations = {
                'first_name':    'ALTER TABLE telegram_subscribers ADD COLUMN first_name TEXT',
                'last_name':     'ALTER TABLE telegram_subscribers ADD COLUMN last_name TEXT',
                'username':      'ALTER TABLE telegram_subscribers ADD COLUMN username TEXT',
                'language_code': 'ALTER TABLE telegram_subscribers ADD COLUMN language_code TEXT',
                'is_active':     'ALTER TABLE telegram_subscribers ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1',
                'updated_at':    'ALTER TABLE telegram_subscribers ADD COLUMN updated_at TEXT',
            }
            if any(col not in sub_cols for col in sub_migrations):
                self._backup_db()
                for col, sql in sub_migrations.items():
                    if col not in sub_cols:
                        conn.execute(sql)
                        logger.info("telegram_subscribers: добавлен столбец %s", col)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    city_slug TEXT NOT NULL DEFAULT 'moscow',
                    notify_new INTEGER NOT NULL DEFAULT 1,
                    notify_price_drop INTEGER NOT NULL DEFAULT 1,
                    min_price_drop_pct INTEGER NOT NULL DEFAULT 0,
                    notifications_on INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_categories (
                    user_id TEXT NOT NULL,
                    category_id TEXT NOT NULL,
                    category_name TEXT,
                    PRIMARY KEY (user_id, category_id)
                )
            """)
            cursor = conn.execute("PRAGMA table_info(user_categories)")
            user_cat_cols = [row[1] for row in cursor.fetchall()]
            if 'category_name' not in user_cat_cols:
                self._backup_db()
                conn.execute("ALTER TABLE user_categories ADD COLUMN category_name TEXT")
                conn.execute("""
                    UPDATE user_categories SET category_name = (
                        SELECT category_name FROM category_state
                        WHERE category_state.category_id = user_categories.category_id
                    )
                """)
                logger.info("Добавлен столбец category_name в таблицу user_categories")
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

            update_rows: list[tuple] = []
            insert_rows: list[tuple] = []
            price_history_rows: list[tuple] = []

            for prod in products:
                if prod.uuid in existing:
                    update_rows.append((
                        prod.id, prod.title, prod.price, prod.price_old,
                        prod.category_id, prod.category_name, prod.status, now, prod.uuid,
                    ))
                    if existing[prod.uuid] != prod.price:
                        price_history_rows.append((prod.uuid, prod.price, now))
                        price_changes.append({
                            "title": prod.title,
                            "url": prod.url,
                            "new_price": prod.price,
                            "old_price": existing[prod.uuid],
                            "price_old": prod.price_old,
                            "status": prod.status,
                            "category_id": prod.category_id,
                        })
                else:
                    insert_rows.append((
                        prod.id, prod.uuid, prod.title, prod.url, prod.category_id,
                        prod.category_name, prod.price, prod.price_old, prod.status, now, now,
                    ))

            if update_rows:
                conn.executemany("""
                    UPDATE products
                    SET id = ?, title = ?, current_price = ?, previous_price = ?,
                        category_id = ?, category_name = ?, status = ?, updated_at = ?
                    WHERE uuid = ?
                """, update_rows)

            if insert_rows:
                conn.executemany("""
                    INSERT INTO products
                    (id, uuid, title, url, category_id, category_name,
                     current_price, previous_price, status, updated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_rows)

            if price_history_rows:
                conn.executemany("""
                    INSERT INTO price_history (product_id, price, timestamp)
                    VALUES (?, ?, ?)
                """, price_history_rows)

            conn.commit()

        return len(products), price_changes

    def delete_all_products_in_category(self, category_id: str) -> int:
        """Удаляет все товары категории и саму запись category_state (категория исчезла с сайта).
        Также очищает user_categories, чтобы пользователи не зависли на несуществующей категории."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM products WHERE category_id = ?", (category_id,)
            )
            conn.execute("DELETE FROM category_state WHERE category_id = ?", (category_id,))
            conn.execute("DELETE FROM user_categories WHERE category_id = ?", (category_id,))
            conn.commit()
            return cursor.rowcount

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
            uuid_hash = hashlib.sha256(json.dumps(sorted(uuids)).encode()).hexdigest()
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

    def add_telegram_subscriber(
        self,
        user_id: str,
        first_name: str = None,
        last_name: str = None,
        username: str = None,
        language_code: str = None,
    ) -> None:
        """Добавляет или реактивирует подписчика. subscribed_at пишется только при первой вставке."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO telegram_subscribers
                    (user_id, first_name, last_name, username, language_code, is_active, subscribed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """, (user_id, first_name, last_name, username, language_code, now, now))
            # При повторном /start обновляем данные и реактивируем, но НЕ трогаем subscribed_at
            conn.execute("""
                UPDATE telegram_subscribers
                SET first_name = ?, last_name = ?, username = ?, language_code = ?,
                    is_active = 1, updated_at = ?
                WHERE user_id = ?
            """, (first_name, last_name, username, language_code, now, user_id))
            conn.commit()

    def remove_telegram_subscriber(self, user_id: str) -> None:
        """Помечает подписчика неактивным (не удаляет из БД)."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE telegram_subscribers SET is_active = 0, updated_at = ? WHERE user_id = ?
            """, (now, user_id))
            conn.commit()

    def get_telegram_subscribers(self, limit: int | None = None, offset: int = 0) -> list[str]:
        """Получает активных подписчиков с поддержкой пагинации."""
        with sqlite3.connect(self.db_path) as conn:
            if limit is not None:
                cursor = conn.execute(
                    "SELECT user_id FROM telegram_subscribers WHERE is_active = 1 ORDER BY user_id LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            else:
                cursor = conn.execute(
                    "SELECT user_id FROM telegram_subscribers WHERE is_active = 1 ORDER BY user_id"
                )
            return [row[0] for row in cursor.fetchall()]

    def count_telegram_subscribers(self) -> int:
        """Возвращает количество активных подписчиков."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM telegram_subscribers WHERE is_active = 1")
            return cursor.fetchone()[0]

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

    def upsert_user_settings(self, user_id: str, **kwargs) -> None:
        """Создает или обновляет настройки пользователя."""
        allowed = {"city_slug", "notify_new", "notify_price_drop", "min_price_drop_pct", "notifications_on"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
            for key, value in updates.items():
                conn.execute(f"UPDATE user_settings SET {key} = ? WHERE user_id = ?", (value, user_id))
            conn.commit()

    def get_user_settings(self, user_id: str) -> dict | None:
        """Получает настройки пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT user_id, city_slug, notify_new, notify_price_drop, min_price_drop_pct, notifications_on
                FROM user_settings WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
        if row:
            return {
                "user_id": row[0],
                "city_slug": row[1],
                "notify_new": bool(row[2]),
                "notify_price_drop": bool(row[3]),
                "min_price_drop_pct": row[4],
                "notifications_on": bool(row[5]),
            }
        return None

    def get_all_subscribers_with_settings(self) -> list[dict]:
        """Возвращает всех подписчиков с их настройками (дефолты если настроек нет)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT ts.user_id,
                       COALESCE(us.city_slug, 'moscow') AS city_slug,
                       COALESCE(us.notify_new, 1) AS notify_new,
                       COALESCE(us.notify_price_drop, 1) AS notify_price_drop,
                       COALESCE(us.min_price_drop_pct, 0) AS min_price_drop_pct,
                       COALESCE(us.notifications_on, 1) AS notifications_on
                FROM telegram_subscribers ts
                LEFT JOIN user_settings us ON ts.user_id = us.user_id
                ORDER BY ts.user_id
            """)
            rows = cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "city_slug": row[1],
                "notify_new": bool(row[2]),
                "notify_price_drop": bool(row[3]),
                "min_price_drop_pct": row[4],
                "notifications_on": bool(row[5]),
            }
            for row in rows
        ]

    def set_user_categories(self, user_id: str, category_ids: list[str]) -> None:
        """Устанавливает выбранные категории (пустой список = все категории)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM user_categories WHERE user_id = ?", (user_id,))
            if category_ids:
                placeholders = ",".join("?" * len(category_ids))
                cursor = conn.execute(
                    f"SELECT category_id, category_name FROM category_state WHERE category_id IN ({placeholders})",
                    category_ids,
                )
                names = {row[0]: row[1] for row in cursor.fetchall()}
                conn.executemany(
                    "INSERT INTO user_categories (user_id, category_id, category_name) VALUES (?, ?, ?)",
                    [(user_id, cid, names.get(cid)) for cid in category_ids],
                )
            conn.commit()

    def get_user_categories(self, user_id: str) -> list[str]:
        """Получает выбранные категории пользователя (пусто = все)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT category_id FROM user_categories WHERE user_id = ?", (user_id,)
            )
            return [row[0] for row in cursor.fetchall()]

    def toggle_user_category(self, user_id: str, category_id: str) -> bool:
        """Переключает категорию для пользователя. Возвращает True если добавлена, False если удалена."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM user_categories WHERE user_id = ? AND category_id = ?",
                (user_id, category_id),
            )
            exists = cursor.fetchone() is not None
            if exists:
                conn.execute(
                    "DELETE FROM user_categories WHERE user_id = ? AND category_id = ?",
                    (user_id, category_id),
                )
                conn.commit()
                return False
            else:
                cursor = conn.execute(
                    "SELECT category_name FROM category_state WHERE category_id = ?",
                    (category_id,),
                )
                row = cursor.fetchone()
                cat_name = row[0] if row else None
                conn.execute(
                    "INSERT INTO user_categories (user_id, category_id, category_name) VALUES (?, ?, ?)",
                    (user_id, category_id, cat_name),
                )
                conn.commit()
                return True

    def get_all_known_categories(self) -> list[dict]:
        """Получает все известные категории из category_state (заполняется при парсинге)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT category_id, category_name FROM category_state ORDER BY category_name"
            )
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]

    def close(self) -> None:
        """Нет-оп: все методы используют with sqlite3.connect(), соединения закрываются автоматически."""
