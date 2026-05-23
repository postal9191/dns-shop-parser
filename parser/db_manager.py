"""
Менеджер БД для хранения товаров и обновления цен.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from parser.models import Product
from utils.logger import logger

MSK = ZoneInfo("Europe/Moscow")


class DBManager:
    """Работа с SQLite: товары и цены."""

    def __init__(self, db_path: str, default_city_slug: str = "") -> None:
        self.db_path = Path(db_path)
        self._default_city_slug = default_city_slug
        self._init_db()

    @staticmethod
    def _report_period_cutoff(period: str) -> str | None:
        """Возвращает начало локального календарного окна в UTC для сравнения с БД."""
        period_days = {"1d": 1, "3d": 3, "7d": 7, "30d": 30}
        days = period_days.get(period)
        if days is None:
            return None
        local_today_start = datetime.now(MSK).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = local_today_start - timedelta(days=days - 1)
        return cutoff.isoformat()

    @staticmethod
    def _now_msk() -> str:
        return datetime.now(MSK).isoformat()

    def _backup_db(self, conn: sqlite3.Connection) -> None:
        """Создает бэкап БД через SQLite online-backup API (безопасно при открытом соединении)."""
        if str(self.db_path) == ":memory:":
            return

        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.db_path.stem}_backup_{timestamp}.db"

        try:
            backup_conn = sqlite3.connect(str(backup_path))
            conn.backup(backup_conn)
            backup_conn.close()
            logger.info("Создан бэкап БД: %s", backup_path)
        except Exception as exc:
            logger.error("Ошибка при создании бэкапа БД: %s", exc)

    def _init_db(self) -> None:
        """Создает таблицы если их нет. Создает бэкап только перед реальными миграциями."""
        # Проверяем до подключения: sqlite3.connect() создаёт файл даже для новой БД
        is_existing_db = (
            str(self.db_path) != ":memory:"
            and self.db_path.exists()
            and self.db_path.stat().st_size > 0
        )
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

            need_migration = (
                'uuid' not in product_cols
                or 'uuid_hash' not in category_cols
                or 'status' not in product_cols
                or 'city_slug' not in product_cols
                or 'city_slug' not in category_cols
                or 'is_sold' not in product_cols
                or 'sold_at' not in product_cols
                or 'seen_at' not in product_cols
                or 'is_sold' not in category_cols
                or 'sold_at' not in category_cols
                or 'seen_at' not in category_cols
            )
            if need_migration and is_existing_db:
                self._backup_db(conn)

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

            # Миграция: добавить city_slug в products
            if 'city_slug' not in product_cols:
                try:
                    conn.execute("ALTER TABLE products ADD COLUMN city_slug TEXT NOT NULL DEFAULT ''")
                    logger.info("Добавлен столбец city_slug в таблицу products")
                except sqlite3.OperationalError:
                    pass

            product_state_migrations = {
                'is_sold': "ALTER TABLE products ADD COLUMN is_sold INTEGER NOT NULL DEFAULT 0",
                'sold_at': "ALTER TABLE products ADD COLUMN sold_at TEXT",
                'seen_at': "ALTER TABLE products ADD COLUMN seen_at TEXT",
            }
            for col, sql in product_state_migrations.items():
                if col not in product_cols:
                    try:
                        conn.execute(sql)
                        logger.info("Добавлен столбец %s в таблицу products", col)
                    except sqlite3.OperationalError:
                        pass

            # Идемпотентный бэкфилл: заполнить пустые city_slug при каждом старте
            # (страховка если первая миграция прошла без default_city_slug)
            if self._default_city_slug:
                conn.execute(
                    "UPDATE products SET city_slug = ? WHERE city_slug = ''",
                    (self._default_city_slug,),
                )
                logger.info(
                    "Существующим товарам с пустым city_slug присвоен город: %s",
                    self._default_city_slug,
                )

            # Миграция: пересоздать category_state с составным PK (category_id, city_slug)
            cursor = conn.execute("PRAGMA table_info(category_state)")
            category_cols = [row[1] for row in cursor.fetchall()]
            if 'city_slug' not in category_cols:
                try:
                    conn.execute("ALTER TABLE category_state RENAME TO category_state_old")
                    conn.execute("""
                        CREATE TABLE category_state (
                            category_id       TEXT NOT NULL,
                            city_slug         TEXT NOT NULL DEFAULT '',
                            category_name     TEXT,
                            last_product_count INTEGER,
                            uuid_hash         TEXT,
                            last_checked_at   TEXT,
                            PRIMARY KEY (category_id, city_slug)
                        )
                    """)
                    city = self._default_city_slug or ''
                    conn.execute(
                        """
                        INSERT INTO category_state
                            (category_id, city_slug, category_name,
                             last_product_count, uuid_hash, last_checked_at)
                        SELECT category_id, ?, category_name,
                               last_product_count, uuid_hash, last_checked_at
                        FROM category_state_old
                        """,
                        (city,),
                    )
                    conn.execute("DROP TABLE category_state_old")
                    logger.info(
                        "Пересоздана таблица category_state с составным PK (category_id, city_slug); "
                        "существующим записям присвоен город: %s",
                        city,
                    )
                except sqlite3.OperationalError as exc:
                    logger.error("Ошибка миграции category_state: %s", exc)

            # Удаляем осиротевшие записи с city_slug='' если для той же категории
            # уже есть запись с реальным городом (артефакт некорректной первой миграции)
            if self._default_city_slug:
                conn.execute("""
                    DELETE FROM category_state
                    WHERE city_slug = ''
                    AND category_id IN (
                        SELECT category_id FROM category_state WHERE city_slug != ''
                    )
                """)

            cursor = conn.execute("PRAGMA table_info(category_state)")
            category_cols = [row[1] for row in cursor.fetchall()]
            category_state_migrations = {
                'is_sold': "ALTER TABLE category_state ADD COLUMN is_sold INTEGER NOT NULL DEFAULT 0",
                'sold_at': "ALTER TABLE category_state ADD COLUMN sold_at TEXT",
                'seen_at': "ALTER TABLE category_state ADD COLUMN seen_at TEXT",
            }
            for col, sql in category_state_migrations.items():
                if col not in category_cols:
                    try:
                        conn.execute(sql)
                        logger.info("Добавлен столбец %s в таблицу category_state", col)
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
                self._backup_db(conn)
                for col, sql in sub_migrations.items():
                    if col not in sub_cols:
                        conn.execute(sql)
                        logger.info("telegram_subscribers: добавлен столбец %s", col)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    city_slug TEXT NOT NULL DEFAULT 'moscow',
                    plan_type TEXT NOT NULL DEFAULT 'free',
                    notify_new INTEGER NOT NULL DEFAULT 1,
                    notify_price_drop INTEGER NOT NULL DEFAULT 1,
                    min_price_drop_pct INTEGER NOT NULL DEFAULT 0,
                    notifications_on INTEGER NOT NULL DEFAULT 1,
                    notify_errors INTEGER NOT NULL DEFAULT 1,
                    notify_parse_finish INTEGER NOT NULL DEFAULT 1
                )
            """)
            user_settings_migrations = {
                'plan_type':           "ALTER TABLE user_settings ADD COLUMN plan_type TEXT NOT NULL DEFAULT 'free'",
                'notify_errors':        'ALTER TABLE user_settings ADD COLUMN notify_errors INTEGER NOT NULL DEFAULT 1',
                'notify_parse_finish': 'ALTER TABLE user_settings ADD COLUMN notify_parse_finish INTEGER NOT NULL DEFAULT 1',
            }
            cursor = conn.execute("PRAGMA table_info(user_settings)")
            us_cols = [row[1] for row in cursor.fetchall()]
            if any(col not in us_cols for col in user_settings_migrations):
                self._backup_db(conn)
                for col, sql in user_settings_migrations.items():
                    if col not in us_cols:
                        conn.execute(sql)
                        logger.info("user_settings: добавлен столбец %s", col)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_categories (
                    user_id TEXT NOT NULL,
                    city_slug TEXT NOT NULL DEFAULT 'moscow',
                    category_id TEXT NOT NULL,
                    category_name TEXT,
                    PRIMARY KEY (user_id, city_slug, category_id)
                )
            """)
            cursor = conn.execute("PRAGMA table_info(user_categories)")
            user_cat_info = cursor.fetchall()
            user_cat_cols = [row[1] for row in user_cat_info]
            user_cat_pk = [row[1] for row in sorted(user_cat_info, key=lambda row: row[5]) if row[5] > 0]
            expected_user_cat_pk = ["user_id", "city_slug", "category_id"]
            if user_cat_cols and (
                "city_slug" not in user_cat_cols or user_cat_pk != expected_user_cat_pk
            ):
                self._backup_db(conn)
                conn.execute("ALTER TABLE user_categories RENAME TO user_categories_old")
                conn.execute("""
                    CREATE TABLE user_categories (
                        user_id TEXT NOT NULL,
                        city_slug TEXT NOT NULL DEFAULT 'moscow',
                        category_id TEXT NOT NULL,
                        category_name TEXT,
                        PRIMARY KEY (user_id, city_slug, category_id)
                    )
                """)
                has_city = "city_slug" in user_cat_cols
                has_name = "category_name" in user_cat_cols
                if has_city and has_name:
                    conn.execute("""
                        INSERT INTO user_categories (user_id, city_slug, category_id, category_name)
                        SELECT user_id, city_slug, category_id, category_name
                        FROM user_categories_old
                    """)
                elif has_city and not has_name:
                    conn.execute("""
                        INSERT INTO user_categories (user_id, city_slug, category_id, category_name)
                        SELECT uco.user_id, uco.city_slug, uco.category_id, cs.category_name
                        FROM user_categories_old uco
                        LEFT JOIN category_state cs
                          ON cs.category_id = uco.category_id AND cs.city_slug = uco.city_slug
                    """)
                elif (not has_city) and has_name:
                    conn.execute("""
                        INSERT INTO user_categories (user_id, city_slug, category_id, category_name)
                        SELECT uco.user_id,
                               COALESCE(us.city_slug, 'moscow') AS city_slug,
                               uco.category_id,
                               uco.category_name
                        FROM user_categories_old uco
                        LEFT JOIN user_settings us ON us.user_id = uco.user_id
                    """)
                else:
                    conn.execute("""
                        INSERT INTO user_categories (user_id, city_slug, category_id, category_name)
                        SELECT uco.user_id,
                               COALESCE(us.city_slug, 'moscow') AS city_slug,
                               uco.category_id,
                               cs.category_name
                        FROM user_categories_old uco
                        LEFT JOIN user_settings us ON us.user_id = uco.user_id
                        LEFT JOIN category_state cs
                          ON cs.category_id = uco.category_id
                         AND cs.city_slug = COALESCE(us.city_slug, 'moscow')
                    """)
                conn.execute("DROP TABLE user_categories_old")
                logger.info("user_categories: migrated to PK (user_id, city_slug, category_id)")
            cursor = conn.execute("PRAGMA table_info(user_categories)")
            user_cat_cols = [row[1] for row in cursor.fetchall()]
            if "category_name" not in user_cat_cols:
                self._backup_db(conn)
                conn.execute("ALTER TABLE user_categories ADD COLUMN category_name TEXT")
                conn.execute("""
                    UPDATE user_categories AS uc SET category_name = (
                        SELECT category_name FROM category_state cs
                        WHERE cs.category_id = uc.category_id
                          AND cs.city_slug = uc.city_slug
                    )
                """)
                logger.info("Добавлен столбец category_name в таблицу user_categories")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_categories_user_city ON user_categories(user_id, city_slug)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS report_limits (
                    user_id TEXT NOT NULL,
                    category_id TEXT NOT NULL,
                    report_type TEXT NOT NULL DEFAULT 'discounts',
                    date_msk TEXT NOT NULL,
                    used_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, category_id, report_type, date_msk)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_events (
                    event_key TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    date_msk TEXT NOT NULL,
                    user_id TEXT,
                    subject_id TEXT,
                    run_at_utc TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    processed_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_uuid ON products(uuid)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_city_slug ON products(city_slug)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_is_sold ON products(is_sold)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category_state_is_sold ON category_state(is_sold)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_product_id ON price_history(product_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_events_status ON scheduled_events(status, event_type, date_msk)")
            cursor = conn.execute("PRAGMA table_info(scheduled_events)")
            scheduled_cols = [row[1] for row in cursor.fetchall()]
            cursor = conn.execute("PRAGMA table_info(report_limits)")
            report_limit_info = cursor.fetchall()
            report_limit_cols = [row[1] for row in report_limit_info]
            report_limit_pk = [row[1] for row in sorted(report_limit_info, key=lambda row: row[5]) if row[5] > 0]
            expected_report_limit_pk = ["user_id", "category_id", "report_type", "date_msk"]
            if report_limit_cols and (
                "report_type" not in report_limit_cols or report_limit_pk != expected_report_limit_pk
            ):
                conn.execute("ALTER TABLE report_limits RENAME TO report_limits_old")
                conn.execute("""
                    CREATE TABLE report_limits (
                        user_id TEXT NOT NULL,
                        category_id TEXT NOT NULL,
                        report_type TEXT NOT NULL DEFAULT 'discounts',
                        date_msk TEXT NOT NULL,
                        used_count INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, category_id, report_type, date_msk)
                    )
                """)
                if "report_type" in report_limit_cols:
                    conn.execute("""
                        INSERT INTO report_limits
                            (user_id, category_id, report_type, date_msk, used_count, created_at, updated_at)
                        SELECT user_id, category_id, report_type, date_msk, used_count, created_at, updated_at
                        FROM report_limits_old
                    """)
                else:
                    conn.execute("""
                        INSERT INTO report_limits
                            (user_id, category_id, report_type, date_msk, used_count, created_at, updated_at)
                        SELECT user_id, category_id, 'discounts', date_msk, used_count, created_at, updated_at
                        FROM report_limits_old
                    """)
                conn.execute("DROP TABLE report_limits_old")
            if "subject_id" not in scheduled_cols:
                conn.execute("ALTER TABLE scheduled_events ADD COLUMN subject_id TEXT")
            if "run_at_utc" not in scheduled_cols:
                conn.execute("ALTER TABLE scheduled_events ADD COLUMN run_at_utc TEXT")
            conn.execute(
                """
                UPDATE scheduled_events
                SET subject_id = user_id, user_id = NULL
                WHERE event_type = 'night_city_parse'
                  AND subject_id IS NULL
                  AND user_id IS NOT NULL
                """
            )
            conn.commit()
        logger.debug("БД инициализирована: %s", self.db_path)

    def upsert_products(self, products: list[Product]) -> tuple[int, list[dict]]:
        """
        Вставляет или обновляет товары.
        Возвращает (количество обновленных записей, список изменений цен).
        """
        if not products:
            return 0, []

        now = self._now_msk()
        price_changes = []

        # Все продукты одного вызова принадлежат одному городу
        city_slug = products[0].city_slug

        with sqlite3.connect(self.db_path) as conn:
            # Batch-SELECT с фильтром по городу
            uuids = [p.uuid for p in products]
            placeholders = ",".join("?" * len(uuids))
            cursor = conn.execute(
                f"SELECT uuid, current_price FROM products WHERE uuid IN ({placeholders}) AND city_slug = ?",
                uuids + [city_slug],
            )
            existing = {row[0]: row[1] for row in cursor.fetchall()}

            update_rows: list[tuple] = []
            insert_rows: list[tuple] = []
            price_history_rows: list[tuple] = []

            for prod in products:
                if prod.uuid in existing:
                    update_rows.append((
                        prod.id, prod.title, prod.price, prod.price_old,
                        prod.category_id, prod.category_name, prod.status, now, now, prod.uuid, prod.city_slug,
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
                            "city_slug": prod.city_slug,
                        })
                else:
                    insert_rows.append((
                        prod.id, prod.uuid, prod.title, prod.url, prod.category_id,
                        prod.category_name, prod.price, prod.price_old, prod.status,
                        prod.city_slug, 0, None, now, now, now,
                    ))

            if update_rows:
                conn.executemany("""
                    UPDATE products
                    SET id = ?, title = ?, current_price = ?, previous_price = ?,
                        category_id = ?, category_name = ?, status = ?,
                        is_sold = 0, sold_at = NULL, updated_at = ?, seen_at = ?
                    WHERE uuid = ? AND city_slug = ?
                """, update_rows)

            if insert_rows:
                conn.executemany("""
                    INSERT INTO products
                    (id, uuid, title, url, category_id, category_name,
                     current_price, previous_price, status, city_slug,
                     is_sold, sold_at, seen_at, updated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_rows)

            if price_history_rows:
                conn.executemany("""
                    INSERT INTO price_history (product_id, price, timestamp)
                    VALUES (?, ?, ?)
                """, price_history_rows)

            conn.commit()

        return len(products), price_changes

    def delete_all_products_in_category(self, category_id: str, city_slug: str) -> int:
        """Помечает категорию и ее товары купленными/исчезнувшими, не удаляя историю."""
        now = self._now_msk()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE products
                SET is_sold = 1,
                    sold_at = COALESCE(sold_at, ?),
                    updated_at = ?
                WHERE category_id = ? AND city_slug = ? AND is_sold = 0
                """,
                (now, now, category_id, city_slug),
            )
            conn.execute(
                """
                UPDATE category_state
                SET is_sold = 1,
                    sold_at = COALESCE(sold_at, ?),
                    last_product_count = 0,
                    last_checked_at = ?
                WHERE category_id = ? AND city_slug = ?
                """,
                (now, now, category_id, city_slug),
            )
            conn.commit()
            return cursor.rowcount

    def delete_products_not_in_uuids(
        self, category_id: str, current_uuids: list[str], city_slug: str
    ) -> int:
        """Помечает купленными товары категории, которых нет в current_uuids."""
        if not current_uuids:
            return 0
        now = self._now_msk()
        placeholders = ",".join("?" * len(current_uuids))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                UPDATE products
                SET is_sold = 1,
                    sold_at = COALESCE(sold_at, ?),
                    updated_at = ?
                WHERE category_id = ? AND city_slug = ?
                  AND is_sold = 0
                  AND uuid NOT IN ({placeholders})
                """,
                [now, now, category_id, city_slug] + list(current_uuids),
            )
            conn.commit()
            return cursor.rowcount

    def get_product_count(self, include_sold: bool = False, city_slug: str | None = None) -> int:
        """Возвращает количество товаров в БД, опционально с фильтром по городу."""
        with sqlite3.connect(self.db_path) as conn:
            where_clauses: list[str] = []
            params: list[str] = []
            if not include_sold:
                where_clauses.append("is_sold = 0")
            if city_slug is not None:
                where_clauses.append("city_slug = ?")
                params.append(city_slug)

            sql = "SELECT COUNT(*) FROM products"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            cursor = conn.execute(sql, params)
            return cursor.fetchone()[0]

    def get_products_by_category(
        self, category_id: str, city_slug: str = None
    ) -> list[Product]:
        """Получает товары по категории. Если city_slug задан — только для этого города."""
        with sqlite3.connect(self.db_path) as conn:
            if city_slug is not None:
                cursor = conn.execute("""
                    SELECT id, uuid, title, url, category_id, category_name,
                           current_price, previous_price, city_slug
                    FROM products WHERE category_id = ? AND city_slug = ? AND is_sold = 0
                """, (category_id, city_slug))
            else:
                cursor = conn.execute("""
                    SELECT id, uuid, title, url, category_id, category_name,
                           current_price, previous_price, city_slug
                    FROM products WHERE category_id = ? AND is_sold = 0
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
                city_slug=row[8],
            )
            for row in rows
        ]

    def get_price_drops(
        self, min_drop_percent: float = 10.0, city_slug: str = None
    ) -> list[dict]:
        """Получает товары с максимальной скидкой."""
        city_clause = "AND city_slug = ?" if city_slug is not None else ""
        params: list = [min_drop_percent]
        if city_slug is not None:
            params.append(city_slug)
        params.append(50)  # LIMIT

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                SELECT id, title, current_price, previous_price,
                       ROUND(100.0 * (previous_price - current_price) / previous_price, 1) as drop_percent
                FROM products
                WHERE previous_price > 0 AND current_price < previous_price
                      AND is_sold = 0
                      AND ROUND(100.0 * (previous_price - current_price) / previous_price, 1) >= ?
                      {city_clause}
                ORDER BY drop_percent DESC
                LIMIT ?
                """,
                params,
            )
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

    def get_category_state(self, category_id: str, city_slug: str) -> dict | None:
        """Получает последнее состояние категории для указанного города."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT category_id, category_name, last_product_count, uuid_hash,
                       last_checked_at, is_sold, sold_at, seen_at
                FROM category_state WHERE category_id = ? AND city_slug = ?
            """, (category_id, city_slug))
            row = cursor.fetchone()

        if row:
            return {
                "category_id": row[0],
                "category_name": row[1],
                "last_product_count": row[2],
                "uuid_hash": row[3],
                "last_checked_at": row[4],
                "is_sold": bool(row[5]),
                "sold_at": row[6],
                "seen_at": row[7],
            }
        return None

    def update_category_state(
        self,
        category_id: str,
        category_name: str,
        product_count: int,
        city_slug: str,
        uuids: list[str] = None,
    ) -> None:
        """Обновляет последнее состояние категории для указанного города."""
        uuid_hash = None
        if uuids is not None:
            uuid_hash = hashlib.sha256(json.dumps(sorted(uuids)).encode()).hexdigest()
        now = self._now_msk()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO category_state
                (category_id, city_slug, category_name, last_product_count, uuid_hash,
                 last_checked_at, is_sold, sold_at, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)
            """, (category_id, city_slug, category_name, product_count, uuid_hash, now, now))
            conn.commit()

    def get_new_products_in_category(
        self, category_id: str, all_product_ids: list[str], city_slug: str
    ) -> list[str]:
        """
        Возвращает UUID товаров которых не было в этой категории ранее.
        all_product_ids - список всех текущих UUID товаров в категории.
        """
        if not all_product_ids:
            return []

        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" * len(all_product_ids))
            cursor = conn.execute(
                f"""
                SELECT uuid FROM products
                WHERE category_id = ? AND city_slug = ? AND uuid IN ({placeholders})
                """,
                [category_id, city_slug] + all_product_ids,
            )
            existing_ids = set(row[0] for row in cursor.fetchall())

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
        now = self._now_msk()
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
        now = self._now_msk()
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

    def get_all_category_states(self, city_slug: str = None) -> dict[str, int]:
        """Возвращает {category_id: last_product_count} для активных категорий в БД.
        Если city_slug задан — только для этого города."""
        with sqlite3.connect(self.db_path) as conn:
            if city_slug is not None:
                cursor = conn.execute("""
                    SELECT category_id, last_product_count FROM category_state
                    WHERE city_slug = ? AND is_sold = 0
                """, (city_slug,))
            else:
                cursor = conn.execute("""
                    SELECT category_id, last_product_count FROM category_state
                    WHERE is_sold = 0
                """)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_report_products(
        self,
        statuses: list[str],
        min_discount_pct: int,
        period: str = "1d",
        category_ids: list[str] = None,
        limit: int = 50,
        city_slug: str = None,
    ) -> list[dict]:
        """Возвращает товары с фильтрацией по статусу, скидке, периоду, категориям и городу.

        period: "1d" / "3d" / "7d" / "30d" — фильтр по updated_at; "all" — без ограничения.
        category_ids: None или [] — все категории; список id — только указанные.
        city_slug: None — все города; строка — только указанный город.
        """
        if not statuses:
            return []

        date_clause = ""
        cat_clause = ""
        city_clause = ""
        params: list = list(statuses) + [min_discount_pct]

        cutoff = self._report_period_cutoff(period) if period != "all" else None
        if cutoff:
            date_clause = "AND updated_at >= ?"
            params.append(cutoff)

        if category_ids:
            cat_placeholders = ",".join("?" * len(category_ids))
            cat_clause = f"AND category_id IN ({cat_placeholders})"
            params.extend(category_ids)

        if city_slug is not None:
            city_clause = "AND city_slug = ?"
            params.append(city_slug)

        params.append(limit)

        placeholders = ",".join("?" * len(statuses))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                SELECT title, url, current_price, previous_price, status, category_name,
                       ROUND(100.0 * (previous_price - current_price) / previous_price, 1) AS discount_pct
                FROM products
                WHERE status IN ({placeholders})
                  AND is_sold = 0
                  AND previous_price > 0
                  AND current_price < previous_price
                  AND ROUND(100.0 * (previous_price - current_price) / previous_price, 1) >= ?
                  {date_clause}
                  {cat_clause}
                  {city_clause}
                ORDER BY discount_pct DESC
                LIMIT ?
                """,
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "title": row[0],
                "url": row[1],
                "current_price": row[2],
                "previous_price": row[3],
                "status": row[4],
                "category_name": row[5],
                "discount_pct": row[6],
            }
            for row in rows
        ]

    def get_new_report_products(
        self,
        statuses: list[str],
        period: str = "1d",
        category_ids: list[str] = None,
        limit: int = 50,
        city_slug: str = None,
    ) -> list[dict]:
        """Возвращает товары, добавленные в БД за выбранный календарный период."""
        if not statuses:
            return []

        date_clause = ""
        cat_clause = ""
        city_clause = ""
        params: list = list(statuses)

        cutoff = self._report_period_cutoff(period) if period != "all" else None
        if cutoff:
            date_clause = "AND created_at >= ?"
            params.append(cutoff)

        if category_ids:
            cat_placeholders = ",".join("?" * len(category_ids))
            cat_clause = f"AND category_id IN ({cat_placeholders})"
            params.extend(category_ids)

        if city_slug is not None:
            city_clause = "AND city_slug = ?"
            params.append(city_slug)

        params.append(limit)

        placeholders = ",".join("?" * len(statuses))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                SELECT title, url, current_price, previous_price, status, category_name, created_at
                FROM products
                WHERE status IN ({placeholders})
                  AND is_sold = 0
                  {date_clause}
                  {cat_clause}
                  {city_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "title": row[0],
                "url": row[1],
                "current_price": row[2],
                "previous_price": row[3],
                "status": row[4],
                "category_name": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    def get_sold_report_products(
        self,
        statuses: list[str],
        period: str = "1d",
        category_ids: list[str] = None,
        limit: int = 50,
        city_slug: str = None,
    ) -> list[dict]:
        """Возвращает купленные/исчезнувшие товары за выбранный период по sold_at."""
        if not statuses:
            return []

        date_clause = ""
        cat_clause = ""
        city_clause = ""
        params: list = list(statuses)

        cutoff = self._report_period_cutoff(period) if period != "all" else None
        if cutoff:
            date_clause = "AND sold_at >= ?"
            params.append(cutoff)

        if category_ids:
            cat_placeholders = ",".join("?" * len(category_ids))
            cat_clause = f"AND category_id IN ({cat_placeholders})"
            params.extend(category_ids)

        if city_slug is not None:
            city_clause = "AND city_slug = ?"
            params.append(city_slug)

        params.append(limit)

        placeholders = ",".join("?" * len(statuses))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                SELECT title, url, current_price, previous_price, status, category_name, sold_at
                FROM products
                WHERE status IN ({placeholders})
                  AND is_sold = 1
                  AND sold_at IS NOT NULL
                  {date_clause}
                  {cat_clause}
                  {city_clause}
                ORDER BY sold_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "title": row[0],
                "url": row[1],
                "current_price": row[2],
                "previous_price": row[3],
                "status": row[4],
                "category_name": row[5],
                "sold_at": row[6],
            }
            for row in rows
        ]

    def get_today_discounts(self, city_slug: str = None) -> list[dict]:
        """Получает товары с обновленными ценами за сегодня (была скидка)."""
        today = datetime.now(MSK).date().isoformat()
        city_clause = "AND city_slug = ?" if city_slug is not None else ""
        params: list = [today]
        if city_slug is not None:
            params.append(city_slug)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                SELECT id, title, url, current_price, previous_price, category_name,
                       ROUND(100.0 * (previous_price - current_price) / previous_price, 1) as drop_percent
                FROM products
                WHERE DATE(updated_at) = ? AND previous_price > 0 AND current_price < previous_price
                      AND is_sold = 0
                      {city_clause}
                ORDER BY drop_percent DESC
                """,
                params,
            )
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

    _SETTING_SQLS = {
        "city_slug":           "UPDATE user_settings SET city_slug = ? WHERE user_id = ?",
        "plan_type":           "UPDATE user_settings SET plan_type = ? WHERE user_id = ?",
        "notify_new":          "UPDATE user_settings SET notify_new = ? WHERE user_id = ?",
        "notify_price_drop":   "UPDATE user_settings SET notify_price_drop = ? WHERE user_id = ?",
        "min_price_drop_pct": "UPDATE user_settings SET min_price_drop_pct = ? WHERE user_id = ?",
        "notifications_on":    "UPDATE user_settings SET notifications_on = ? WHERE user_id = ?",
        "notify_errors":       "UPDATE user_settings SET notify_errors = ? WHERE user_id = ?",
        "notify_parse_finish": "UPDATE user_settings SET notify_parse_finish = ? WHERE user_id = ?",
    }

    def upsert_user_settings(self, user_id: str, **kwargs) -> None:
        """Создает или обновляет настройки пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
            for key, value in kwargs.items():
                sql = self._SETTING_SQLS.get(key)
                if sql:
                    conn.execute(sql, (value, user_id))
            conn.commit()

    def get_user_settings(self, user_id: str) -> dict | None:
        """Получает настройки пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT user_id, city_slug, plan_type, notify_new, notify_price_drop,
                       min_price_drop_pct, notifications_on,
                       notify_errors, notify_parse_finish
                FROM user_settings WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
        if row:
            return {
                "user_id": row[0],
                "city_slug": row[1],
                "plan_type": row[2],
                "notify_new": bool(row[3]),
                "notify_price_drop": bool(row[4]),
                "min_price_drop_pct": row[5],
                "notifications_on": bool(row[6]),
                "notify_errors": bool(row[7]),
                "notify_parse_finish": bool(row[8]),
            }
        return None

    def get_all_subscribers_with_settings(self) -> list[dict]:
        """Возвращает всех подписчиков с их настройками (дефолты если настроек нет)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT ts.user_id,
                       COALESCE(us.city_slug, 'moscow') AS city_slug,
                       COALESCE(us.plan_type, 'free') AS plan_type,
                       COALESCE(us.notify_new, 1) AS notify_new,
                       COALESCE(us.notify_price_drop, 1) AS notify_price_drop,
                       COALESCE(us.min_price_drop_pct, 0) AS min_price_drop_pct,
                       COALESCE(us.notifications_on, 1) AS notifications_on,
                       COALESCE(us.notify_errors, 1) AS notify_errors,
                       COALESCE(us.notify_parse_finish, 1) AS notify_parse_finish
                FROM telegram_subscribers ts
                LEFT JOIN user_settings us ON ts.user_id = us.user_id
                WHERE ts.is_active = 1
                ORDER BY ts.user_id
            """)
            rows = cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "city_slug": row[1],
                "plan_type": row[2],
                "notify_new": bool(row[3]),
                "notify_price_drop": bool(row[4]),
                "min_price_drop_pct": row[5],
                "notifications_on": bool(row[6]),
                "notify_errors": bool(row[7]),
                "notify_parse_finish": bool(row[8]),
            }
            for row in rows
        ]

    def get_active_users_with_plan_types(self) -> list[dict]:
        """Returns active Telegram users for admin plan management."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT ts.user_id,
                       COALESCE(ts.username, '') AS username,
                       COALESCE(us.plan_type, 'free') AS plan_type
                FROM telegram_subscribers ts
                LEFT JOIN user_settings us ON ts.user_id = us.user_id
                WHERE ts.is_active = 1
                ORDER BY
                    CASE COALESCE(us.plan_type, 'free')
                        WHEN 'super' THEN 0
                        WHEN 'pro' THEN 1
                        WHEN 'free' THEN 2
                        ELSE 3
                    END,
                    LOWER(COALESCE(ts.username, '')),
                    ts.user_id
            """)
            rows = cursor.fetchall()
        allowed = {"free", "pro", "super"}
        return [
            {
                "user_id": row[0],
                "username": row[1] or "",
                "plan_type": row[2] if row[2] in allowed else "free",
            }
            for row in rows
        ]

    def set_user_categories(self, user_id: str, category_ids: list[str], city_slug: str) -> None:
        """Устанавливает выбранные категории (пустой список = все категории)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM user_categories WHERE user_id = ? AND city_slug = ?", (user_id, city_slug))
            if category_ids:
                placeholders = ",".join("?" * len(category_ids))
                cursor = conn.execute(
                    f"""
                    SELECT category_id, category_name FROM category_state
                    WHERE is_sold = 0 AND city_slug = ? AND category_id IN ({placeholders})
                    """,
                    [city_slug] + category_ids,
                )
                names = {row[0]: row[1] for row in cursor.fetchall()}
                conn.executemany(
                    "INSERT INTO user_categories (user_id, city_slug, category_id, category_name) VALUES (?, ?, ?, ?)",
                    [(user_id, city_slug, cid, names.get(cid)) for cid in category_ids],
                )
            conn.commit()

    def get_user_categories(self, user_id: str, city_slug: str) -> list[str]:
        """Получает выбранные категории пользователя (пусто = все)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT category_id FROM user_categories WHERE user_id = ? AND city_slug = ?",
                (user_id, city_slug),
            )
            return [row[0] for row in cursor.fetchall()]

    def toggle_user_category(self, user_id: str, category_id: str, city_slug: str) -> bool:
        """Переключает категорию для пользователя. Возвращает True если добавлена, False если удалена."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM user_categories WHERE user_id = ? AND city_slug = ? AND category_id = ?",
                (user_id, city_slug, category_id),
            )
            exists = cursor.fetchone() is not None
            if exists:
                conn.execute(
                    "DELETE FROM user_categories WHERE user_id = ? AND city_slug = ? AND category_id = ?",
                    (user_id, city_slug, category_id),
                )
                conn.commit()
                return False
            else:
                cursor = conn.execute(
                    """
                    SELECT category_name FROM category_state
                    WHERE category_id = ? AND city_slug = ? AND is_sold = 0
                    """,
                    (category_id, city_slug),
                )
                row = cursor.fetchone()
                cat_name = row[0] if row else None
                conn.execute(
                    "INSERT INTO user_categories (user_id, city_slug, category_id, category_name) VALUES (?, ?, ?, ?)",
                    (user_id, city_slug, category_id, cat_name),
                )
                conn.commit()
                return True

    def get_all_known_categories(self, city_slug: str | None = None) -> list[dict]:
        """Получает активные категории из category_state (заполняется при парсинге)."""
        with sqlite3.connect(self.db_path) as conn:
            if city_slug is None:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT category_id, category_name
                    FROM category_state
                    WHERE is_sold = 0
                    ORDER BY category_name
                    """
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT category_id, category_name
                    FROM category_state
                    WHERE is_sold = 0 AND city_slug = ?
                    ORDER BY category_name
                    """,
                    (city_slug,),
                )
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]

    def get_sold_known_categories(self, city_slug: str | None = None) -> list[dict]:
        """Получает категории, связанные с историей купленных/исчезнувших товаров."""
        with sqlite3.connect(self.db_path) as conn:
            if city_slug is None:
                cursor = conn.execute(
                    """
                    SELECT category_id, category_name FROM category_state
                    WHERE is_sold = 1
                    UNION
                    SELECT category_id, category_name FROM products
                    WHERE is_sold = 1
                    ORDER BY category_name
                    """
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT category_id, category_name FROM category_state
                    WHERE is_sold = 1 AND city_slug = ?
                    UNION
                    SELECT category_id, category_name FROM products
                    WHERE is_sold = 1 AND city_slug = ?
                    ORDER BY category_name
                    """,
                    (city_slug, city_slug),
                )
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]

    def get_active_free_subscribers_with_settings(self) -> list[dict]:
        """Returns active free subscribers with their notification settings."""
        return [
            row for row in self.get_all_subscribers_with_settings()
            if row.get("plan_type", "free") == "free"
        ]

    def consume_free_report_limit(
        self,
        user_id: str,
        category_id: str,
        report_type: str,
        date_msk: str,
    ) -> bool:
        """Consumes one free report quota for a user/category/report-type/day. Returns True if limit not exceeded (< 3)."""
        now = self._now_msk()
        with sqlite3.connect(self.db_path) as conn:
            # Сначала проверяем текущее использование
            cursor = conn.execute(
                """
                SELECT used_count FROM report_limits
                WHERE user_id = ? AND category_id = ? AND report_type = ? AND date_msk = ?
                """,
                (user_id, category_id, report_type, date_msk),
            )
            row = cursor.fetchone()
            current_usage = int(row[0]) if row else 0

            # Если уже использованы все 3 попытки, возвращаем False
            if current_usage >= 3:
                return False

            # Иначе увеличиваем счетчик
            if row:
                # Обновляем существующую запись
                conn.execute(
                    """
                    UPDATE report_limits
                    SET used_count = used_count + 1, updated_at = ?
                    WHERE user_id = ? AND category_id = ? AND report_type = ? AND date_msk = ?
                    """,
                    (now, user_id, category_id, report_type, date_msk),
                )
            else:
                # Создаем новую запись
                conn.execute(
                    """
                    INSERT INTO report_limits
                        (user_id, category_id, report_type, date_msk, used_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (user_id, category_id, report_type, date_msk, now, now),
                )

            conn.commit()
            return True

    def get_report_limit_usage(self, user_id: str, category_id: str, report_type: str, date_msk: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT used_count FROM report_limits
                WHERE user_id = ? AND category_id = ? AND report_type = ? AND date_msk = ?
                """,
                (user_id, category_id, report_type, date_msk),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    def _event_key(
        event_type: str,
        date_msk: str,
        user_id: str | None = None,
        subject_id: str | None = None,
    ) -> str:
        identifier = user_id or subject_id or "_global"
        return f"{event_type}:{date_msk}:{identifier}"

    def ensure_scheduled_event(
        self,
        event_type: str,
        date_msk: str,
        user_id: str | None = None,
        subject_id: str | None = None,
        run_at_utc: str | None = None,
    ) -> str:
        now = self._now_msk()
        event_key = self._event_key(event_type, date_msk, user_id, subject_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO scheduled_events
                    (event_key, event_type, date_msk, user_id, subject_id, run_at_utc, status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (event_key, event_type, date_msk, user_id, subject_id, run_at_utc, now, now),
            )
            conn.commit()
        return event_key

    def has_scheduled_event_history(self, include_maintenance: bool = True) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            if include_maintenance:
                cursor = conn.execute("SELECT 1 FROM scheduled_events LIMIT 1")
            else:
                cursor = conn.execute(
                    """
                    SELECT 1
                    FROM scheduled_events
                    WHERE event_type != 'free_limit_maintenance'
                    LIMIT 1
                    """
                )
            return cursor.fetchone() is not None

    def has_scheduled_event_type(self, event_type: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM scheduled_events WHERE event_type = ? LIMIT 1",
                (event_type,),
            )
            return cursor.fetchone() is not None

    def get_pending_scheduled_events(self, max_attempts: int = 3) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT event_key, event_type, date_msk, user_id, subject_id, run_at_utc, status, attempts, last_error
                FROM scheduled_events
                WHERE status IN ('pending', 'failed') AND attempts < ?
                ORDER BY date_msk, event_type, COALESCE(user_id, subject_id, '')
                """,
                (max_attempts,),
            )
            rows = cursor.fetchall()
        return [
            {
                "event_key": row[0],
                "event_type": row[1],
                "date_msk": row[2],
                "user_id": row[3],
                "subject_id": row[4],
                "run_at_utc": row[5],
                "status": row[6],
                "attempts": row[7],
                "last_error": row[8],
            }
            for row in rows
        ]

    def get_scheduled_events(self, event_type: str, date_msk: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT event_key, event_type, date_msk, user_id, subject_id, run_at_utc, status, attempts, last_error, processed_at
                FROM scheduled_events
                WHERE event_type = ? AND date_msk = ?
                ORDER BY run_at_utc, COALESCE(user_id, subject_id, '')
                """,
                (event_type, date_msk),
            )
            rows = cursor.fetchall()
        return [
            {
                "event_key": row[0],
                "event_type": row[1],
                "date_msk": row[2],
                "user_id": row[3],
                "subject_id": row[4],
                "run_at_utc": row[5],
                "status": row[6],
                "attempts": row[7],
                "last_error": row[8],
                "processed_at": row[9],
            }
            for row in rows
        ]

    def mark_scheduled_event_done(self, event_key: str) -> None:
        now = self._now_msk()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE scheduled_events
                SET status = 'done', updated_at = ?, processed_at = ?, last_error = NULL
                WHERE event_key = ?
                """,
                (now, now, event_key),
            )
            conn.commit()

    def mark_scheduled_event_failed(self, event_key: str, error: str) -> None:
        now = self._now_msk()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE scheduled_events
                SET status = 'failed', attempts = attempts + 1, last_error = ?, updated_at = ?
                WHERE event_key = ?
                """,
                (str(error)[:1000], now, event_key),
            )
            conn.commit()

    def mark_scheduled_event_skipped(self, event_key: str, reason: str) -> None:
        now = self._now_msk()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE scheduled_events
                SET status = 'skipped', updated_at = ?, processed_at = ?, last_error = ?
                WHERE event_key = ?
                """,
                (now, now, str(reason)[:1000], event_key),
            )
            conn.commit()

    def get_scheduled_event(self, event_key: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT event_key, event_type, date_msk, user_id, subject_id, run_at_utc, status, attempts, last_error, processed_at
                FROM scheduled_events WHERE event_key = ?
                """,
                (event_key,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return {
            "event_key": row[0],
            "event_type": row[1],
            "date_msk": row[2],
            "user_id": row[3],
            "subject_id": row[4],
            "run_at_utc": row[5],
            "status": row[6],
            "attempts": row[7],
            "last_error": row[8],
            "processed_at": row[9],
        }

    def get_daily_report_data(
        self,
        start_utc: str,
        end_utc: str,
        city_slug: str,
        min_drop_pct: int = 0,
        limit: int = 200,
    ) -> tuple[list[dict], list[dict]]:
        """Returns new products and price drops inside explicit UTC bounds for one city."""
        with sqlite3.connect(self.db_path) as conn:
            new_rows = conn.execute(
                """
                SELECT category_id, category_name, title, current_price, previous_price, url, status, city_slug
                FROM products
                WHERE city_slug = ?
                  AND is_sold = 0
                  AND created_at >= ?
                  AND created_at < ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (city_slug, start_utc, end_utc, limit),
            ).fetchall()
            drop_rows = conn.execute(
                """
                SELECT category_id, title, url, current_price, previous_price, status, city_slug
                FROM products
                WHERE city_slug = ?
                  AND is_sold = 0
                  AND updated_at >= ?
                  AND updated_at < ?
                  AND previous_price > 0
                  AND current_price < previous_price
                  AND ROUND(100.0 * (previous_price - current_price) / previous_price, 1) >= ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (city_slug, start_utc, end_utc, min_drop_pct, limit),
            ).fetchall()
        new_products = [
            {
                "category_id": row[0],
                "category": row[1],
                "title": row[2],
                "price": row[3],
                "price_old": row[4],
                "url": row[5],
                "status": row[6],
                "city_slug": row[7],
            }
            for row in new_rows
        ]
        price_changes = [
            {
                "category_id": row[0],
                "title": row[1],
                "url": row[2],
                "new_price": row[3],
                "old_price": row[4],
                "price_old": row[4],
                "status": row[5],
                "city_slug": row[6],
            }
            for row in drop_rows
        ]
        return new_products, price_changes

    def get_current_digest_data(
        self,
        city_slug: str,
        min_drop_pct: int = 0,
        category_ids: list[str] | None = None,
        limit: int = 100,
    ) -> tuple[list[dict], list[dict]]:
        """Returns current fresh data for digest: new products and price drops without date restrictions."""
        with sqlite3.connect(self.db_path) as conn:
            # Базовые условия для фильтрации
            base_conditions = "city_slug = ? AND is_sold = 0"
            base_params = [city_slug]

            # Добавляем фильтр по категориям если указан
            category_filter = ""
            if category_ids:
                placeholders = ",".join("?" * len(category_ids))
                category_filter = f" AND category_id IN ({placeholders})"
                base_params.extend(category_ids)

            # Получаем новые товары (за последние 7 дней для актуальности)
            new_query = """
                SELECT category_id, category_name, title, current_price, previous_price, url, status, city_slug
                FROM products
                WHERE """ + base_conditions + category_filter + """
                  AND created_at >= datetime('now', '-7 days')
                ORDER BY created_at DESC
                LIMIT ?
                """
            new_rows = conn.execute(new_query, base_params + [limit]).fetchall()

            # Получаем товары со скидками (все актуальные)
            drop_query = """
                SELECT category_id, title, url, current_price, previous_price, status, city_slug
                FROM products
                WHERE """ + base_conditions + category_filter + """
                  AND previous_price > 0
                  AND current_price < previous_price
                  AND ROUND(100.0 * (previous_price - current_price) / previous_price, 1) >= ?
                ORDER BY updated_at DESC
                LIMIT ?
                """
            drop_rows = conn.execute(drop_query, base_params + [min_drop_pct, limit]).fetchall()

        new_products = [
            {
                "category_id": row[0],
                "category": row[1],
                "title": row[2],
                "price": row[3],
                "price_old": row[4],
                "url": row[5],
                "status": row[6],
                "city_slug": row[7],
            }
            for row in new_rows
        ]
        price_changes = [
            {
                "category_id": row[0],
                "title": row[1],
                "url": row[2],
                "new_price": row[3],
                "old_price": row[4],
                "status": row[5],
                "city_slug": row[6],
            }
            for row in drop_rows
        ]
        return new_products, price_changes

    def close(self) -> None:
        """Нет-оп: все методы используют with sqlite3.connect(), соединения закрываются автоматически."""
