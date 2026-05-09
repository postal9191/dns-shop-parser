import asyncio
import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from parser.models import Product
from services.daily_scheduler import (
    FREE_DAILY_REPORT,
    FREE_LIMIT_MAINTENANCE,
    DailyScheduler,
    report_bounds_utc,
)
from services.telegram_notifier import TelegramNotifier


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_user_settings_plan_type_defaults_to_free(db_memory):
    db_memory.upsert_user_settings("u1")

    settings = db_memory.get_user_settings("u1")
    rows = db_memory.get_all_subscribers_with_settings()

    assert settings["plan_type"] == "free"
    assert rows == []


def test_get_all_subscribers_includes_plan_type(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="pro", city_slug="kazan")

    rows = db_memory.get_all_subscribers_with_settings()

    assert rows[0]["plan_type"] == "pro"
    assert rows[0]["city_slug"] == "kazan"


def test_free_report_limit_is_one_per_category_per_msk_day(db_memory):
    assert db_memory.consume_free_report_limit("u1", "cat-1", "new_products", "2026-05-07") is True
    assert db_memory.consume_free_report_limit("u1", "cat-1", "new_products", "2026-05-07") is False
    assert db_memory.consume_free_report_limit("u1", "cat-1", "discounts", "2026-05-07") is True
    assert db_memory.consume_free_report_limit("u1", "cat-2", "new_products", "2026-05-07") is True
    assert db_memory.consume_free_report_limit("u1", "cat-1", "new_products", "2026-05-08") is True
    assert db_memory.get_report_limit_usage("u1", "cat-1", "new_products", "2026-05-07") == 1
    assert db_memory.get_report_limit_usage("u1", "cat-1", "discounts", "2026-05-07") == 1


def test_immediate_digest_can_target_only_paid_plans():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value="ok")
    db = MagicMock()
    db.get_all_subscribers_with_settings.return_value = [
        {"user_id": "free", "plan_type": "free", "city_slug": "moscow", "notify_new": True, "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": True},
        {"user_id": "pro", "plan_type": "pro", "city_slug": "moscow", "notify_new": True, "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": True},
        {"user_id": "super", "plan_type": "super", "city_slug": "moscow", "notify_new": True, "notify_price_drop": True, "min_price_drop_pct": 0, "notifications_on": True},
    ]
    db.get_user_categories.return_value = []
    notifier = TelegramNotifier(bot=bot, db=db)

    _run(notifier.send_digest([
        {"category_id": "cat-1", "title": "A", "price": 10, "url": "", "status": "", "city_slug": "moscow"}
    ], [], plan_types={"pro", "super"}))

    sent_to = [call.args[0] for call in bot.send_message.await_args_list]
    assert sent_to == ["pro", "super"]


def test_scheduler_ensures_maintenance_and_catchup_daily_events(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="free")
    db_memory.ensure_scheduled_event(FREE_DAILY_REPORT, "2026-05-03", "u1")
    scheduler = DailyScheduler(db_memory, TelegramNotifier(), catchup_days=3)
    now = datetime(2026, 5, 7, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    scheduler.ensure_due_events(now)
    scheduler.ensure_due_events(now)

    assert db_memory.get_scheduled_event(f"{FREE_LIMIT_MAINTENANCE}:2026-05-07:_global")["status"] == "pending"
    assert db_memory.get_scheduled_event(f"{FREE_DAILY_REPORT}:2026-05-06:u1")["status"] == "pending"
    pending = db_memory.get_pending_scheduled_events()
    report_days = sorted(e["date_msk"] for e in pending if e["event_type"] == FREE_DAILY_REPORT)
    assert report_days == ["2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06"]


def test_scheduler_does_not_schedule_yesterday_before_0800(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="free")
    db_memory.ensure_scheduled_event(FREE_DAILY_REPORT, "2026-05-04", "u1")
    scheduler = DailyScheduler(db_memory, TelegramNotifier(), catchup_days=2)
    now = datetime(2026, 5, 7, 7, 59, tzinfo=ZoneInfo("Europe/Moscow"))

    scheduler.ensure_due_events(now)

    assert db_memory.get_scheduled_event(f"{FREE_DAILY_REPORT}:2026-05-06:u1") is None
    assert db_memory.get_scheduled_event(f"{FREE_DAILY_REPORT}:2026-05-05:u1")["status"] == "pending"


def test_scheduler_empty_event_log_does_not_backfill_before_0800(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="free")
    scheduler = DailyScheduler(db_memory, TelegramNotifier(), catchup_days=3)
    now = datetime(2026, 5, 7, 0, 7, tzinfo=ZoneInfo("Europe/Moscow"))

    scheduler.ensure_due_events(now)

    assert db_memory.get_scheduled_event(f"{FREE_LIMIT_MAINTENANCE}:2026-05-07:_global")["status"] == "pending"
    assert db_memory.get_scheduled_event(f"{FREE_DAILY_REPORT}:2026-05-06:u1") is None


def test_scheduler_empty_event_log_bootstraps_only_yesterday_after_0800(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="free")
    scheduler = DailyScheduler(db_memory, TelegramNotifier(), catchup_days=3)
    now = datetime(2026, 5, 7, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    scheduler.ensure_due_events(now)

    assert db_memory.get_scheduled_event(f"{FREE_DAILY_REPORT}:2026-05-06:u1")["status"] == "pending"
    assert db_memory.get_scheduled_event(f"{FREE_DAILY_REPORT}:2026-05-05:u1") is None


def test_scheduler_processes_daily_once_and_marks_done(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="free", city_slug="moscow")
    event_key = db_memory.ensure_scheduled_event(FREE_DAILY_REPORT, "2026-05-06", "u1")
    notifier = MagicMock()
    notifier.send_daily_report_to_user = AsyncMock(return_value="empty")
    scheduler = DailyScheduler(db_memory, notifier)

    _run(scheduler.process_pending_events())
    _run(scheduler.process_pending_events())

    event = db_memory.get_scheduled_event(event_key)
    assert event["status"] == "done"
    assert notifier.send_daily_report_to_user.await_count == 1


def test_scheduler_failed_event_is_retained_for_retry(db_memory):
    db_memory.add_telegram_subscriber("u1")
    db_memory.upsert_user_settings("u1", plan_type="free", city_slug="moscow")
    event_key = db_memory.ensure_scheduled_event(FREE_DAILY_REPORT, "2026-05-06", "u1")
    notifier = MagicMock()
    notifier.send_daily_report_to_user = AsyncMock(return_value="fail")
    scheduler = DailyScheduler(db_memory, notifier)

    _run(scheduler.process_pending_events())

    event = db_memory.get_scheduled_event(event_key)
    assert event["status"] == "failed"
    assert event["attempts"] == 1
    assert event["last_error"] == "fail"


def test_scheduler_ignores_unknown_event_types_without_failing_them(db_memory):
    event_key = db_memory.ensure_scheduled_event("night_city_parse", "2026-05-06", subject_id="moscow")
    notifier = MagicMock()
    scheduler = DailyScheduler(db_memory, notifier)

    _run(scheduler.process_pending_events())

    event = db_memory.get_scheduled_event(event_key)
    assert event["status"] == "pending"
    assert event["attempts"] == 0
    assert event["last_error"] is None


def test_daily_report_data_uses_explicit_utc_bounds(db_memory):
    products = [
        Product(id="p1", uuid="u1", title="inside", price=100, price_old=120, url="", category_id="cat", category_name="Cat", status="Новый", city_slug="moscow"),
        Product(id="p2", uuid="u2", title="outside", price=100, price_old=120, url="", category_id="cat", category_name="Cat", status="Новый", city_slug="moscow"),
    ]
    db_memory.upsert_products(products)
    start_utc, end_utc = report_bounds_utc("2026-05-06")
    with sqlite3.connect(db_memory.db_path) as conn:
        conn.execute("UPDATE products SET created_at = ?, updated_at = ? WHERE uuid = 'u1'", (start_utc, start_utc))
        conn.execute("UPDATE products SET created_at = ?, updated_at = ? WHERE uuid = 'u2'", (end_utc, end_utc))
        conn.commit()

    new_products, price_changes = db_memory.get_daily_report_data(start_utc, end_utc, "moscow")

    assert [p["title"] for p in new_products] == ["inside"]
    assert [p["title"] for p in price_changes] == ["inside"]
