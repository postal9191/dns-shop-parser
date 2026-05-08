from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import run


def test_can_start_city_parse_respects_0530_budget():
    msk = ZoneInfo("Europe/Moscow")

    assert run.can_start_city_parse(datetime(2026, 5, 7, 5, 0, tzinfo=msk), estimated_seconds=1800) is True
    assert run.can_start_city_parse(datetime(2026, 5, 7, 5, 1, tzinfo=msk), estimated_seconds=1800) is False


def test_night_window_end_rolls_to_next_morning_after_22():
    msk = ZoneInfo("Europe/Moscow")

    end = run.night_window_end(datetime(2026, 5, 7, 22, 5, tzinfo=msk))

    assert end == datetime(2026, 5, 8, 5, 30, tzinfo=msk)


def test_night_schedule_date_uses_previous_day_after_midnight():
    msk = ZoneInfo("Europe/Moscow")

    schedule_date = run.night_schedule_date(datetime(2026, 5, 8, 1, 15, tzinfo=msk))

    assert schedule_date.isoformat() == "2026-05-07"


def test_ensure_night_city_schedule_is_idempotent(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    monkeypatch.setattr(run.random, "shuffle", lambda items: None)
    monkeypatch.setattr(run.random, "randrange", lambda span: 0)

    first = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 22, 1, tzinfo=msk))
    second = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 23, 50, tzinfo=msk))

    assert len(first) == 2
    assert len(second) == 2
    assert [event["event_key"] for event in first] == [event["event_key"] for event in second]
    assert [event["subject_id"] for event in first] == ["moscow", "spb"]
    assert all(event["user_id"] is None for event in first)


def test_restart_skips_missed_night_events_without_immediate_catchup(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    monkeypatch.setattr(run.random, "shuffle", lambda items: None)
    values = iter([0, 3600])
    monkeypatch.setattr(run.random, "randrange", lambda span: next(values))

    run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 22, 0, tzinfo=msk))
    restart_now = datetime(2026, 5, 7, 23, 50, tzinfo=msk).astimezone(timezone.utc)

    skipped = run.skip_missed_night_city_events(db_memory, restart_now)
    due_event = run.get_due_night_city_event(db_memory, restart_now)

    assert skipped == ["moscow"]
    assert due_event is None


def test_done_city_is_not_selected_again_same_night(db_memory, monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    monkeypatch.setattr(run, "NIGHT_CITY_SLUGS", ["moscow", "spb"])
    monkeypatch.setattr(run.random, "shuffle", lambda items: None)
    values = iter([0, 7200])
    monkeypatch.setattr(run.random, "randrange", lambda span: next(values))

    events = run.ensure_night_city_schedule(db_memory, datetime(2026, 5, 7, 22, 0, tzinfo=msk))
    db_memory.mark_scheduled_event_done(events[0]["event_key"])

    due_event = run.get_due_night_city_event(db_memory, datetime(2026, 5, 8, 0, 30, tzinfo=timezone.utc))

    assert due_event is None
