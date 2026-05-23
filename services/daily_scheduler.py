from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from services.telegram_notifier import TelegramNotifier
from utils.logger import logger


MSK = ZoneInfo("Europe/Moscow")
FREE_DAILY_REPORT = "free_daily_report"
FREE_LIMIT_MAINTENANCE = "free_limit_maintenance"


def report_bounds_utc(date_msk: str) -> tuple[str, str]:
    day = date.fromisoformat(date_msk)
    start = datetime.combine(day, time.min, tzinfo=MSK)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


class DailyScheduler:
    def __init__(
        self,
        db,
        notifier: TelegramNotifier,
        catchup_days: int = 3,
        daily_hour: int = 8,
        max_attempts: int = 3,
    ) -> None:
        self.db = db
        self.notifier = notifier
        self.catchup_days = catchup_days
        self.daily_hour = daily_hour
        self.max_attempts = max_attempts

    def ensure_due_events(self, now: datetime | None = None) -> None:
        now_msk = (now or datetime.now(MSK)).astimezone(MSK)
        today = now_msk.date()
        has_daily_history = self.db.has_scheduled_event_type(FREE_DAILY_REPORT)

        self.db.ensure_scheduled_event(FREE_LIMIT_MAINTENANCE, today.isoformat())

        # If the event log was wiped, do not replay historical digests before 08:00.
        # After 08:00 bootstrap only yesterday's daily report.
        if not has_daily_history and now_msk.time() < time(self.daily_hour, 0):
            return

        if now_msk.time() < time(self.daily_hour, 0):
            latest_report_day = today - timedelta(days=2)
            days_to_schedule = self.catchup_days
        else:
            latest_report_day = today - timedelta(days=1)
            days_to_schedule = self.catchup_days if has_daily_history else 1

        subscribers = self.db.get_active_free_subscribers_with_settings()
        for offset in range(days_to_schedule):
            report_day = latest_report_day - timedelta(days=offset)
            for sub in subscribers:
                self.db.ensure_scheduled_event(
                    FREE_DAILY_REPORT,
                    report_day.isoformat(),
                    str(sub["user_id"]),
                )

    async def process_pending_events(self) -> None:
        events = self.db.get_pending_scheduled_events(max_attempts=self.max_attempts)
        for event in events:
            try:
                if event["event_type"] == FREE_LIMIT_MAINTENANCE:
                    self.db.mark_scheduled_event_done(event["event_key"])
                elif event["event_type"] == FREE_DAILY_REPORT:
                    await self._process_daily_report(event)
                else:
                    continue
            except Exception as exc:
                logger.error("[SCHEDULER] event %s failed: %s", event.get("event_key"), exc)
                self.db.mark_scheduled_event_failed(event["event_key"], str(exc))

    async def _process_daily_report(self, event: dict) -> None:
        user_id = str(event["user_id"])
        settings = self.db.get_user_settings(user_id)
        if not settings:
            settings = {
                "user_id": user_id,
                "city_slug": "moscow",
                "plan_type": "free",
                "notify_new": True,
                "notify_price_drop": True,
                "min_price_drop_pct": 0,
                "notifications_on": True,
            }
        if settings.get("plan_type", "free") != "free":
            self.db.mark_scheduled_event_done(event["event_key"])
            return
        if not settings.get("notifications_on", True):
            self.db.mark_scheduled_event_done(event["event_key"])
            return

        # Получаем категории пользователя
        city_slug = settings.get("city_slug", "moscow")
        user_categories = self.db.get_user_categories(user_id, city_slug)
        category_ids = [cat["category_id"] for cat in user_categories] if user_categories else None

        # Получаем текущие актуальные данные вместо данных за конкретный день
        new_products, price_changes = self.db.get_current_digest_data(
            settings["city_slug"],
            min_drop_pct=settings.get("min_price_drop_pct", 0),
            category_ids=category_ids,
        )

        if not settings.get("notify_new", True):
            new_products = []
        if not settings.get("notify_price_drop", True):
            price_changes = []

        result = await self.notifier.send_daily_report_to_user(user_id, new_products, price_changes)
        if result in ("ok", "empty"):
            self.db.mark_scheduled_event_done(event["event_key"])
        elif result == "blocked":
            self.db.remove_telegram_subscriber(user_id)
            self.db.mark_scheduled_event_done(event["event_key"])
        else:
            self.db.mark_scheduled_event_failed(event["event_key"], result)

    async def run_forever(self, interval_seconds: int = 300) -> None:
        import asyncio

        while True:
            self.ensure_due_events()
            await self.process_pending_events()
            await asyncio.sleep(interval_seconds)
