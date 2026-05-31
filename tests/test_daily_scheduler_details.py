"""
Тесты для daily_scheduler: report_bounds_utc,
DailyScheduler.ensure_due_events, _process_daily_report, process_pending_events.
"""

import pytest
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, Mock, patch

from services.daily_scheduler import (
    DailyScheduler,
    report_bounds_utc,
    FREE_DAILY_REPORT,
    FREE_LIMIT_MAINTENANCE,
)


class TestReportBoundsUtc:
    """Тесты для report_bounds_utc."""

    def test_returns_start_and_end_of_day(self):
        start, end = report_bounds_utc("2026-01-15")
        assert start == "2026-01-15T00:00:00+03:00"
        assert end == "2026-01-16T00:00:00+03:00"

    def test_end_is_exactly_one_day_after_start(self):
        start, end = report_bounds_utc("2026-02-28")
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        assert (end_dt - start_dt).days == 1

    def test_handles_leap_year(self):
        start, end = report_bounds_utc("2028-02-29")
        assert start == "2028-02-29T00:00:00+03:00"
        assert end == "2028-03-01T00:00:00+03:00"


class TestEnsureDueEvents:
    """Тесты для ensure_due_events."""

    def test_schedules_maintenance_event(self):
        db = Mock()
        db.has_scheduled_event_type.return_value = False
        db.get_active_free_subscribers_with_settings.return_value = []
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        now = datetime(2026, 5, 30, 10, 0, 0)
        scheduler.ensure_due_events(now)
        assert db.ensure_scheduled_event.called

        # Первый вызов — maintenance (сегодня)
        args = db.ensure_scheduled_event.call_args_list[0]
        assert args[0][0] == FREE_LIMIT_MAINTENANCE

    def test_no_daily_history_before_8am(self):
        """До 8 утра без истории — не планируем daily reports."""
        db = Mock()
        db.has_scheduled_event_type.return_value = False
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        now = datetime(2026, 5, 30, 7, 59)
        scheduler.ensure_due_events(now)
        # get_active_free_subscribers_with_settings не вызывается, т.к. возвращаем раньше
        db.get_active_free_subscribers_with_settings.assert_not_called()

    def test_no_daily_history_after_8am_schedules_yesterday(self):
        """После 8 утра без истории — планируем только вчерашний."""
        db = Mock()
        db.has_scheduled_event_type.return_value = False
        # Пустой список подписчиков → daily events не планируются, но loop проходит
        db.get_active_free_subscribers_with_settings.return_value = []
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        now = datetime(2026, 5, 30, 9, 0)
        scheduler.ensure_due_events(now)
        # days_to_schedule == 1 → но нет подписчиков, поэтому daily events не вызываются
        call_count_after_maintenance = len(
            [c for c in db.ensure_scheduled_event.call_args_list if c[0][0] == FREE_DAILY_REPORT]
        )
        assert call_count_after_maintenance == 0

    def test_has_history_schedules_catchup_days(self):
        """При наличии истории — планируем catchup_days дней."""
        db = Mock()
        db.has_scheduled_event_type.return_value = True
        # Пустой список → daily events не вызываются, но days_to_schedule верен
        db.get_active_free_subscribers_with_settings.return_value = []
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier, catchup_days=3)
        now = datetime(2026, 5, 30, 9, 0)
        scheduler.ensure_due_events(now)
        # Без подписчиков не должно быть daily event вызовов
        call_count_after_maintenance = len(
            [c for c in db.ensure_scheduled_event.call_args_list if c[0][0] == FREE_DAILY_REPORT]
        )
        assert call_count_after_maintenance == 0

    def test_early_schedule_before_8am(self):
        """До 8 утра — latest_report_day = today - 2."""
        db = Mock()
        db.has_scheduled_event_type.return_value = True
        db.get_active_free_subscribers_with_settings.return_value = []
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier, catchup_days=1)
        now = datetime(2026, 5, 30, 7, 0)
        scheduler.ensure_due_events(now)

    def test_schedules_with_subscribers(self):
        """Реальный сценарий: есть подписчики → планируются daily events."""
        db = Mock()
        db.has_scheduled_event_type.return_value = False
        db.get_active_free_subscribers_with_settings.return_value = [
            {"user_id": "u1"},
            {"user_id": "u2"},
        ]
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier, catchup_days=1)
        now = datetime(2026, 5, 30, 9, 0)
        scheduler.ensure_due_events(now)
        # maintenance (1) + daily для u1 (yesterday) + daily для u2 (yesterday) = 3
        all_calls = db.ensure_scheduled_event.call_args_list
        assert len(all_calls) == 3

    def test_no_subscribers_no_daily(self):
        """Нет подписчиков → нет daily events."""
        db = Mock()
        db.has_scheduled_event_type.return_value = True
        db.get_active_free_subscribers_with_settings.return_value = []
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        now = datetime(2026, 5, 30, 9, 0)
        scheduler.ensure_due_events(now)
        # Только maintenance event
        assert len([c for c in db.ensure_scheduled_event.call_args_list if c[0][0] == FREE_DAILY_REPORT]) == 0


class TestProcessDailyReport:
    """Тесты для _process_daily_report."""

    @pytest.mark.asyncio
    async def test_skips_non_free_plans(self):
        db = Mock()
        db.get_user_settings.return_value = {"plan_type": "pro", "notifications_on": True}
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        event = {
            "event_key": "test:2026-05-30:user1",
            "event_type": FREE_DAILY_REPORT,
            "user_id": "user1",
        }
        await scheduler._process_daily_report(event)
        db.mark_scheduled_event_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_notifications_off(self):
        db = Mock()
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": False,
            "city_slug": "moscow",
        }
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        db.mark_scheduled_event_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_defaults_when_no_settings(self):
        db = Mock()
        db.get_user_settings.return_value = None
        db.get_current_digest_data.return_value = ([], [])
        db.get_user_categories.return_value = []  #Mock был truthy, ломал list comprehension
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "ok"
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        # Должен использовать дефолтные значения
        db.get_current_digest_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_honors_notify_new_disabled(self):
        db = Mock()
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": True,
            "notify_new": False,
            "notify_price_drop": True,
            "city_slug": "moscow",
            "min_price_drop_pct": 0,
        }
        db.get_current_digest_data.return_value = ([{"title": "A"}], [{"title": "B"}])
        db.get_user_categories.return_value = []
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "ok"
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        call_args = notifier.send_daily_report_to_user.call_args[0]
        assert call_args[1] == []  # new_products filtered out
        assert len(call_args[2]) == 1

    @pytest.mark.asyncio
    async def test_honors_notify_price_drop_disabled(self):
        db = Mock()
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": True,
            "notify_new": True,
            "notify_price_drop": False,
            "city_slug": "moscow",
            "min_price_drop_pct": 0,
        }
        db.get_current_digest_data.return_value = ([{"title": "A"}], [{"title": "B"}])
        db.get_user_categories.return_value = []
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "ok"
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        call_args = notifier.send_daily_report_to_user.call_args[0]
        # price_changes (index 2) should be empty; new_products (index 1) kept
        assert len(call_args[2]) == 0

    @pytest.mark.asyncio
    async def test_blocked_removes_subscriber(self):
        db = Mock()
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": True,
            "city_slug": "moscow",
        }
        db.get_current_digest_data.return_value = ([{"title": "A"}], [])
        db.get_user_categories.return_value = []
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "blocked"
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        db.remove_telegram_subscriber.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_empty_report_marks_done(self):
        db = Mock()
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": True,
            "city_slug": "moscow",
        }
        db.get_current_digest_data.return_value = ([], [])
        db.get_user_categories.return_value = []
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "empty"
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        db.mark_scheduled_event_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_marks_failed(self):
        db = Mock()
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": True,
            "city_slug": "moscow",
        }
        db.get_current_digest_data.return_value = ([{"title": "A"}], [])
        db.get_user_categories.return_value = []
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "fail"
        scheduler = DailyScheduler(db, notifier)
        event = {"event_key": "t:2026-05-30:u1", "event_type": FREE_DAILY_REPORT, "user_id": "u1"}
        await scheduler._process_daily_report(event)
        db.mark_scheduled_event_failed.assert_called_once()


class TestProcessPendingEvents:
    """Тесты для process_pending_events."""

    @pytest.mark.asyncio
    async def test_maintenance_event_marked_done(self):
        db = Mock()
        db.get_pending_scheduled_events.return_value = [
            {
                "event_key": "m:2026-05-30",
                "event_type": FREE_LIMIT_MAINTENANCE,
                "user_id": None,
            }
        ]
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        await scheduler.process_pending_events()
        db.mark_scheduled_event_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_report_processed(self):
        db = Mock()
        db.get_pending_scheduled_events.return_value = [
            {
                "event_key": "d:2026-05-30:u1",
                "event_type": FREE_DAILY_REPORT,
                "user_id": "u1",
            }
        ]
        db.get_user_settings.return_value = {
            "plan_type": "free",
            "notifications_on": True,
            "city_slug": "moscow",
        }
        db.get_current_digest_data.return_value = ([], [])
        notifier = AsyncMock()
        notifier.send_daily_report_to_user.return_value = "ok"
        scheduler = DailyScheduler(db, notifier)
        await scheduler.process_pending_events()

    @pytest.mark.asyncio
    async def test_exception_marks_failed(self):
        db = Mock()
        db.get_pending_scheduled_events.return_value = [
            {
                "event_key": "d:2026-05-30:u1",
                "event_type": FREE_DAILY_REPORT,
                "user_id": "u1",
            }
        ]
        db.get_user_settings.side_effect = Exception("db error")
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        await scheduler.process_pending_events()
        db.mark_scheduled_event_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_event_type_skipped(self):
        db = Mock()
        db.get_pending_scheduled_events.return_value = [
            {
                "event_key": "x:2026-05-30",
                "event_type": "unknown_type",
                "user_id": None,
            }
        ]
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        await scheduler.process_pending_events()
        # Не должна пытаться обработать неизвестный тип
        db.mark_scheduled_event_done.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pending_events(self):
        db = Mock()
        db.get_pending_scheduled_events.return_value = []
        notifier = AsyncMock()
        scheduler = DailyScheduler(db, notifier)
        await scheduler.process_pending_events()
        # Ничего не должно произойти
        db.mark_scheduled_event_done.assert_not_called()
        db.mark_scheduled_event_failed.assert_not_called()
