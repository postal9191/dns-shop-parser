"""
Тесты миграций DBManager:
- бэкап создаётся при любой миграции
- бэкап не создаётся для свежей БД (нет старых колонок)
- city_slug backfill для products с пустым city_slug
- очистка дублей category_state с city_slug=''
- category_state мигрируется с переносом данных
- повторный запуск _init_db идемпотентен
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from parser.db_manager import DBManager
from parser.models import Product


def _make_db(tmpdir: str, default_city_slug: str = "") -> DBManager:
    db_path = str(Path(tmpdir) / "test.db")
    return DBManager(db_path, default_city_slug=default_city_slug)


def _backup_files(db: DBManager) -> list[Path]:
    backup_dir = db.db_path.parent / "backups"
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("*.db"))


def _seed_old_schema(db_path: str) -> None:
    """Создаёт БД со старой схемой (без city_slug, status, uuid_hash)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE products (
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
        conn.execute("""
            CREATE TABLE category_state (
                category_id TEXT PRIMARY KEY,
                category_name TEXT,
                last_product_count INTEGER,
                last_checked_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("p1", "uuid-1", "Товар", "http://x", "cat-1", "Кат", 1000, 2000, None, None),
        )
        conn.execute(
            "INSERT INTO category_state VALUES (?,?,?,?)",
            ("cat-1", "Категория", 5, None),
        )
        conn.commit()


# ─── Бэкап ────────────────────────────────────────────────────────────────────

class TestBackup:
    def test_backup_created_on_migration(self, tmp_path):
        """Бэкап создаётся когда БД требует миграции (старая схема)."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        backups = _backup_files(db)
        assert len(backups) >= 1, "Бэкап должен быть создан при миграции"

    def test_backup_is_valid_sqlite(self, tmp_path):
        """Файл бэкапа является рабочей SQLite БД."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        backup = _backup_files(db)[0]
        with sqlite3.connect(str(backup)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "products" in tables
        assert "category_state" in tables

    def test_backup_preserves_data(self, tmp_path):
        """Бэкап содержит данные, которые были в БД до миграции."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        backup = _backup_files(db)[0]
        with sqlite3.connect(str(backup)) as conn:
            row = conn.execute("SELECT id, title FROM products WHERE id='p1'").fetchone()
        assert row is not None
        assert row[1] == "Товар"

    def test_no_backup_for_fresh_db(self, tmp_path):
        """Бэкап НЕ создаётся для свежей пустой БД (нет миграций)."""
        db_path = str(tmp_path / "test.db")
        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        backups = _backup_files(db)
        assert backups == [], "Для новой БД бэкап не нужен"

    def test_backup_not_created_for_memory_db(self):
        """_backup_db ничего не делает для :memory: БД."""
        db = DBManager(":memory:")
        with sqlite3.connect(":memory:") as conn:
            db._backup_db(conn)  # не должно бросать исключений и не создаёт файлов

    def test_second_init_no_extra_backup(self, tmp_path):
        """Повторный запуск _init_db на уже мигрированной БД не создаёт лишний бэкап."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db1 = DBManager(db_path, default_city_slug="krasnodar")
        db1.close()
        count_after_first = len(_backup_files(db1))

        db2 = DBManager(db_path, default_city_slug="krasnodar")
        db2.close()
        count_after_second = len(_backup_files(db2))

        assert count_after_second == count_after_first, (
            "Повторный запуск не должен создавать лишний бэкап"
        )


# ─── city_slug backfill ────────────────────────────────────────────────────────

class TestCitySlugBackfill:
    def test_products_with_empty_city_get_default(self, tmp_path):
        """Товары с city_slug='' получают default_city_slug при старте."""
        db_path = str(tmp_path / "test.db")

        # Первый запуск без города — колонка добавляется с DEFAULT ''
        db1 = DBManager(db_path)
        db1.upsert_products([Product(
            id="p1", uuid="u1", title="T", price=100, price_old=100,
            url="http://x", city_slug="",
        )])
        db1.close()

        # Второй запуск с городом — бэкфилл должен обновить пустые
        db2 = DBManager(db_path, default_city_slug="krasnodar")
        db2.close()

        with sqlite3.connect(db_path) as conn:
            city = conn.execute(
                "SELECT city_slug FROM products WHERE uuid='u1'"
            ).fetchone()[0]
        assert city == "krasnodar"

    def test_products_with_city_not_overwritten(self, tmp_path):
        """Товары с уже заполненным city_slug не перезаписываются бэкфиллом."""
        db_path = str(tmp_path / "test.db")

        db1 = DBManager(db_path, default_city_slug="moscow")
        db1.upsert_products([Product(
            id="p1", uuid="u1", title="T", price=100, price_old=100,
            url="http://x", city_slug="moscow",
        )])
        db1.close()

        # Запускаем с другим городом — moscow не должен смениться
        db2 = DBManager(db_path, default_city_slug="spb")
        db2.close()

        with sqlite3.connect(db_path) as conn:
            city = conn.execute(
                "SELECT city_slug FROM products WHERE uuid='u1'"
            ).fetchone()[0]
        assert city == "moscow"

    def test_backfill_idempotent(self, tmp_path):
        """Бэкфилл при многократных запусках не ломает данные."""
        db_path = str(tmp_path / "test.db")

        db1 = DBManager(db_path, default_city_slug="krasnodar")
        db1.upsert_products([Product(
            id="p1", uuid="u1", title="T", price=100, price_old=100,
            url="http://x", city_slug="",
        )])
        db1.close()

        for _ in range(3):
            DBManager(db_path, default_city_slug="krasnodar").close()

        with sqlite3.connect(db_path) as conn:
            city = conn.execute(
                "SELECT city_slug FROM products WHERE uuid='u1'"
            ).fetchone()[0]
        assert city == "krasnodar"


# ─── category_state миграция ──────────────────────────────────────────────────

class TestCategoryStateMigration:
    def test_migration_adds_city_slug_column(self, tmp_path):
        """После миграции таблица category_state содержит колонку city_slug."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        with sqlite3.connect(db_path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(category_state)").fetchall()}
        assert "city_slug" in cols

    def test_migration_preserves_existing_categories(self, tmp_path):
        """Существующие записи category_state сохраняются после миграции."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        state = db.get_category_state("cat-1", "krasnodar")
        assert state is not None
        assert state["category_name"] == "Категория"
        assert state["last_product_count"] == 5

    def test_migration_assigns_default_city_to_old_records(self, tmp_path):
        """Старые записи category_state получают default_city_slug при миграции."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT city_slug FROM category_state WHERE category_id='cat-1'"
            ).fetchall()
        cities = [r[0] for r in rows]
        assert cities == ["krasnodar"], f"Ожидался ['krasnodar'], получено {cities}"

    def test_migration_composite_pk(self, tmp_path):
        """category_state имеет составной PK (category_id, city_slug)."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db = DBManager(db_path, default_city_slug="krasnodar")
        db.close()

        with sqlite3.connect(db_path) as conn:
            # Попытка вставить дубликат по (category_id, city_slug) должна падать
            try:
                conn.execute(
                    "INSERT INTO category_state (category_id, city_slug) VALUES ('cat-1', 'krasnodar')"
                )
                conn.commit()
                assert False, "Должно было бросить UNIQUE constraint"
            except sqlite3.IntegrityError:
                pass


# ─── Очистка дублей category_state ───────────────────────────────────────────

class TestCategoryStateDuplicateCleanup:
    def _seed_with_duplicates(self, db_path: str) -> None:
        """Симулирует состояние БД с дублями: (cat-1, '') и (cat-1, 'krasnodar')."""
        _seed_old_schema(db_path)
        # Запустим миграцию БЕЗ города → старые записи станут (cat-1, '')
        DBManager(db_path).close()
        # Добавим вручную запись с реальным городом
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO category_state
                   (category_id, city_slug, category_name, last_product_count)
                   VALUES ('cat-1', 'krasnodar', 'Категория', 5)"""
            )
            conn.commit()

    def test_cleanup_removes_empty_city_slug_duplicates(self, tmp_path):
        """Запись (cat-1, '') удаляется если есть (cat-1, 'krasnodar')."""
        db_path = str(tmp_path / "test.db")
        self._seed_with_duplicates(db_path)

        # Проверяем что дубли есть
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT city_slug FROM category_state WHERE category_id='cat-1'"
            ).fetchall()
        assert len(rows) == 2, "Ожидали 2 записи до очистки"

        # Запускаем с городом — должен почистить дубли
        DBManager(db_path, default_city_slug="krasnodar").close()

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT city_slug FROM category_state WHERE category_id='cat-1'"
            ).fetchall()
        cities = [r[0] for r in rows]
        assert "" not in cities, "Запись с пустым city_slug должна быть удалена"
        assert "krasnodar" in cities

    def test_cleanup_keeps_empty_if_no_real_city(self, tmp_path):
        """Запись с city_slug='' НЕ удаляется если нет записи с реальным городом."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        # Мигрируем без города
        DBManager(db_path).close()

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT city_slug FROM category_state WHERE category_id='cat-1'"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == ""

        # Снова запускаем без города — не должно удалить единственную запись
        DBManager(db_path).close()

        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM category_state WHERE category_id='cat-1'"
            ).fetchone()[0]
        assert count == 1

    def test_cleanup_does_not_run_without_default_city(self, tmp_path):
        """Если default_city_slug не задан — очистка не запускается."""
        db_path = str(tmp_path / "test.db")
        self._seed_with_duplicates(db_path)

        # Запускаем БЕЗ города
        DBManager(db_path).close()

        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM category_state WHERE category_id='cat-1'"
            ).fetchone()[0]
        # Дубли остались — очистка не трогает без явного города
        assert count == 2


# ─── Полная миграция со старых версий ─────────────────────────────────────────

class TestFullMigrationFromLegacy:
    def test_legacy_products_get_all_new_columns(self, tmp_path):
        """Все новые колонки добавляются в products при миграции со старой схемы."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        DBManager(db_path, default_city_slug="krasnodar").close()

        with sqlite3.connect(db_path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()}

        for expected in ("uuid", "status", "city_slug"):
            assert expected in cols, f"Колонка {expected!r} должна быть в products"

    def test_legacy_product_gets_krasnodar(self, tmp_path):
        """Товар из старой БД получает city_slug='krasnodar' при миграции."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        DBManager(db_path, default_city_slug="krasnodar").close()

        with sqlite3.connect(db_path) as conn:
            city = conn.execute(
                "SELECT city_slug FROM products WHERE id='p1'"
            ).fetchone()[0]
        assert city == "krasnodar"

    def test_reinit_after_migration_is_idempotent(self, tmp_path):
        """Повторная инициализация мигрированной БД не ломает данные."""
        db_path = str(tmp_path / "test.db")
        _seed_old_schema(db_path)

        db1 = DBManager(db_path, default_city_slug="krasnodar")
        db1.upsert_products([Product(
            id="p2", uuid="u2", title="Новый", price=500, price_old=500,
            url="http://y", city_slug="krasnodar",
        )])
        db1.close()

        db2 = DBManager(db_path, default_city_slug="krasnodar")
        count = db2.get_product_count()
        db2.close()

        assert count == 2  # p1 (из seed) + p2 (добавленный)
