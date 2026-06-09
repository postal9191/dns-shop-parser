from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from dns_shop_parser.entrypoints import run


def test_can_start_city_parse_allows_start_until_0600_deadline():
    msk = ZoneInfo("Europe/Moscow")

    assert run.can_start_city_parse(datetime(2026, 5, 7, 5, 59, tzinfo=msk)) is True
    assert run.can_start_city_parse(datetime(2026, 5, 7, 6, 0, tzinfo=msk)) is False


def test_night_window_end_is_0600_same_day():
    msk = ZoneInfo("Europe/Moscow")

    end = run.night_window_end(datetime(2026, 5, 7, 1, 5, tzinfo=msk))

    assert end == datetime(2026, 5, 7, 6, 0, tzinfo=msk)


def test_day_city_time_allows_krasnodar_0700_to_2000():
    msk = ZoneInfo("Europe/Moscow")

    assert run.is_day_city_time(datetime(2026, 5, 7, 7, 0, tzinfo=msk)) is True
    assert run.is_day_city_time(datetime(2026, 5, 7, 19, 59, tzinfo=msk)) is True
    assert run.is_day_city_time(datetime(2026, 5, 7, 20, 0, tzinfo=msk)) is True


def test_day_city_time_rejects_outside_krasnodar_window():
    msk = ZoneInfo("Europe/Moscow")

    assert run.is_day_city_time(datetime(2026, 5, 7, 6, 59, tzinfo=msk)) is False
    assert run.is_day_city_time(datetime(2026, 5, 7, 20, 1, tzinfo=msk)) is False
    assert run.is_day_city_time(datetime(2026, 5, 7, 23, 0, tzinfo=msk)) is False


def test_after_2000_day_sync_sleep_goes_to_midnight():
    msk = ZoneInfo("Europe/Moscow")

    sleep_seconds = run.calculate_day_sync_sleep(
        3600,
        datetime(2026, 5, 7, 20, 3, tzinfo=msk),
    )

    assert sleep_seconds == 14220


@pytest.mark.asyncio
async def test_restart_inside_day_window_waits_for_env_timer_before_krasnodar(monkeypatch, db_memory):
    msk = ZoneInfo("Europe/Moscow")
    sleep_calls = []
    parser_calls = []

    class State:
        is_running = True
        iteration_count = 0

    class Controller:
        state = State()

        def __init__(self):
            self._should_stop = False

        def should_stop(self):
            return self._should_stop

        def get_pending_interval(self):
            return None

    controller = Controller()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 5, 7, 10, 3, tzinfo=msk)
            return value if tz is None else value.astimezone(tz)

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        controller._should_stop = True

    async def fake_run_parser(city_slug=None):
        parser_calls.append(city_slug)
        return True

    monkeypatch.setattr(run, "datetime", FixedDateTime)
    monkeypatch.setattr(run.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(run, "run_parser", fake_run_parser)

    await run.main_cycle(controller, db_memory)

    assert sleep_calls == [3420]
    assert parser_calls == []


def test_night_schedule_date_uses_current_day_after_midnight():
    msk = ZoneInfo("Europe/Moscow")

    schedule_date = run.night_schedule_date(datetime(2026, 5, 8, 1, 15, tzinfo=msk))

    assert schedule_date.isoformat() == "2026-05-08"


def test_ensure_night_city_schedule_is_idempotent(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    monkeypatch.setattr(run.random, "randrange", lambda span: 0)

    first = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 0, 1, tzinfo=msk))
    second = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 5, 50, tzinfo=msk))

    assert len(first) == 2
    assert len(second) == 2
    assert [event["event_key"] for event in first] == [event["event_key"] for event in second]
    assert [event["subject_id"] for event in first] == ["moscow", "spb"]
    assert all(event["user_id"] is None for event in first)
    assert first[0]["run_at_utc"] == "2026-05-06T21:00:00+00:00"
    assert first[1]["run_at_utc"] == "2026-05-07T00:00:00+00:00"


def test_restart_before_0600_does_not_skip_due_night_events(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    values = iter([0, 3600])
    monkeypatch.setattr(run.random, "randrange", lambda span: next(values))

    run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 0, 0, tzinfo=msk))
    restart_now = datetime(2026, 5, 7, 3, 50, tzinfo=msk).astimezone(timezone.utc)

    skipped = run.skip_missed_night_city_events(db_memory, restart_now)
    due_event = run.get_due_night_city_event(db_memory, restart_now)

    assert skipped == []
    assert due_event["subject_id"] == "moscow"


def test_restart_after_0600_skips_pending_night_events(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    values = iter([0, 3600])
    monkeypatch.setattr(run.random, "randrange", lambda span: next(values))

    run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 0, 0, tzinfo=msk))
    restart_now = datetime(2026, 5, 7, 6, 5, tzinfo=msk).astimezone(timezone.utc)

    skipped = run.skip_missed_night_city_events(db_memory, restart_now)
    due_event = run.get_due_night_city_event(db_memory, restart_now)

    assert skipped == ["moscow", "spb"]
    assert due_event is None


def test_existing_night_event_outside_new_window_is_skipped(db_memory):
    msk = ZoneInfo("Europe/Moscow")
    run_at = datetime(2026, 5, 7, 6, 30, tzinfo=msk).astimezone(timezone.utc)
    event_key = db_memory.ensure_scheduled_event(
        run.NIGHT_CITY_EVENT,
        "2026-05-07",
        subject_id="moscow",
        run_at_utc=run_at.isoformat(),
    )

    events = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 0, 1, tzinfo=msk))

    assert events[0]["event_key"] == event_key
    assert events[0]["status"] == "skipped"


def test_done_city_is_not_selected_again_same_night(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    values = iter([0, 7200])
    monkeypatch.setattr(run.random, "randrange", lambda span: next(values))

    events = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 0, 0, tzinfo=msk))
    db_memory.mark_scheduled_event_done(events[0]["event_key"])

    due_event = run.get_due_night_city_event(db_memory, datetime(2026, 5, 7, 0, 30, tzinfo=timezone.utc))

    assert due_event is None


@pytest.mark.asyncio
async def test_main_cycle_runs_scheduled_parse_through_controller(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    monkeypatch.setattr(run.random, "randrange", lambda span: 0)
    parser_calls = []

    class State:
        is_running = True
        iteration_count = 0

    class Controller:
        state = State()

        def __init__(self):
            self._should_stop = False

        def should_stop(self):
            return self._should_stop

        def get_pending_interval(self):
            return None

        async def run_parse(self, city_slug=None):
            parser_calls.append(city_slug)
            return True

    controller = Controller()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 5, 7, 0, 30, tzinfo=msk)
            return value if tz is None else value.astimezone(tz)

    async def fake_sleep(seconds):
        controller._should_stop = True

    async def forbidden_run_parser(city_slug=None):
        raise AssertionError("main_cycle must use parser_controller.run_parse")

    monkeypatch.setattr(run, "datetime", FixedDateTime)
    monkeypatch.setattr(run.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(run, "run_parser", forbidden_run_parser)

    await run.main_cycle(controller, db_memory)

    assert parser_calls == ["moscow"]
