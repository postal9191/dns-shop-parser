#!/usr/bin/env python3
"""
Автоматический запуск: обновление кук + парсинг товаров в цикле.
ТГ бот работает параллельно в отдельной задаче (всегда включен).
"""

import asyncio
import hashlib
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from config import config
from parser.db_manager import DBManager
from data.cities import CITIES
from services.daily_scheduler import DailyScheduler
from services.telegram_bot import init_telegram_bot
from services.telegram_notifier import TelegramNotifier
from services.admin_panel import ParserController
from utils.logger import logger

# Определяем директорию проекта
PROJECT_DIR = Path(__file__).parent.absolute()


def acquire_single_instance_lock():
    """Не даёт запустить два постоянных run.py для одного проекта."""
    try:
        import fcntl
    except ImportError:
        return None

    lock_id = hashlib.sha256(str(PROJECT_DIR).encode("utf-8")).hexdigest()[:12]
    lock_path = Path("/tmp") / f"dns-parser-{lock_id}.lock"
    lock_file = lock_path.open("a+", encoding="utf-8")

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.seek(0)
        owner = lock_file.read().strip()
        logger.error("[RUN] Уже запущен другой run.py для этого проекта%s", f": {owner}" if owner else "")
        lock_file.close()
        return None

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f"pid={os.getpid()} project={PROJECT_DIR}\n")
    lock_file.flush()
    return lock_file

async def _run_subprocess(script: str, log_name: str, args: list[str] | None = None) -> bool:
    """Запускает Python-скрипт в отдельном процессе асинхронно."""
    logger.info("[RUN] Запускаю: %s", log_name)
    loop = asyncio.get_running_loop()
    command = [sys.executable, str(PROJECT_DIR / script)] + ([] if args is None else args)
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                command,
                cwd=str(PROJECT_DIR),
                check=False,
                timeout=600,
            ),
        )
        if result.returncode == 0:
            logger.info("[RUN] ✓ %s завершено успешно", log_name)
            return True
        else:
            logger.error("[RUN] ✗ %s завершен с кодом %d", script, result.returncode)
            return False
    except asyncio.TimeoutError:
        logger.error("[RUN] ✗ %s превышен timeout (10 минут)", script)
        return False
    except Exception as e:
        logger.error("[RUN] ✗ Ошибка при выполнении %s: %s", script, e)
        return False


_MSK = ZoneInfo("Europe/Moscow")
NIGHT_START_HOUR = 0
NIGHT_START_MINUTE = 0
NIGHT_END_HOUR = 6
NIGHT_END_MINUTE = 0
DAY_START_HOUR = 7
DAY_START_MINUTE = 0
DAY_LAST_RUN_HOUR = 20
DAY_LAST_RUN_MINUTE = 0
DAY_CITY_SLUG = "krasnodar"
NIGHT_CITY_SLUGS = [slug for slug in CITIES.values() if slug != DAY_CITY_SLUG]
NIGHT_CITY_EVENT = "night_city_parse"
NIGHT_LOOP_POLL_SECONDS = 60


def is_night_time(now: datetime | None = None) -> bool:
    """Проверяет если сейчас ночное время (00:00-06:00 МСК)."""
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return (now.hour, now.minute) >= (NIGHT_START_HOUR, NIGHT_START_MINUTE) and (
        now.hour,
        now.minute,
    ) < (NIGHT_END_HOUR, NIGHT_END_MINUTE)


def night_window_end(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return now.replace(hour=NIGHT_END_HOUR, minute=NIGHT_END_MINUTE, second=0, microsecond=0)


def night_schedule_date(now: datetime | None = None) -> datetime.date:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return now.date()


def night_window_bounds_for_date(schedule_date) -> tuple[datetime, datetime]:
    start = datetime.combine(schedule_date, datetime.min.time(), tzinfo=_MSK).replace(
        hour=NIGHT_START_HOUR, minute=NIGHT_START_MINUTE, second=0, microsecond=0
    )
    end = start.replace(hour=NIGHT_END_HOUR, minute=NIGHT_END_MINUTE)
    return start, end


def can_start_city_parse(now: datetime | None = None) -> bool:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return now < night_window_end(now)


def day_window_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return now.replace(
        hour=DAY_START_HOUR,
        minute=DAY_START_MINUTE,
        second=0,
        microsecond=0,
    )


def day_last_run_time(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return now.replace(
        hour=DAY_LAST_RUN_HOUR,
        minute=DAY_LAST_RUN_MINUTE,
        second=59,
        microsecond=999999,
    )


def is_day_city_time(now: datetime | None = None) -> bool:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    return day_window_start(now) <= now <= day_last_run_time(now)


def next_active_window_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    _, today_night_end = night_window_bounds_for_date(now.date())
    today_day_start = day_window_start(now)

    if now < today_night_end:
        return now
    if now < today_day_start:
        return today_day_start
    if now <= day_last_run_time(now):
        return now

    tomorrow = now.date() + timedelta(days=1)
    tomorrow_night_start, _ = night_window_bounds_for_date(tomorrow)
    return tomorrow_night_start


def calculate_sleep_until_next_active_window(now: datetime | None = None) -> int:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    next_start = next_active_window_start(now)
    return max(1, int((next_start - now).total_seconds()))


def calculate_next_sync_sleep(interval_sec: int, now: datetime | None = None) -> int:
    """Рассчитывает сколько спать до следующего синхронного времени (как крон).

    Если интервал 3600 (час), то запускать в 0, 60, 120 минут
    Если интервал 1800 (30 мин), то запускать в 0, 30 минут часа
    Если интервал 900 (15 мин), то запускать в 0, 15, 30, 45 минут часа
    """
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    now_seconds = now.hour * 3600 + now.minute * 60 + now.second

    # Следующее синхронное время
    # Расстояние до следующего кратного интервалу момента времени
    remainder = now_seconds % interval_sec
    if remainder == 0:
        return interval_sec  # Если ровно на границе, ждем полный интервал
    return interval_sec - remainder


def calculate_day_sync_sleep(interval_sec: int, now: datetime | None = None) -> int:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    sync_sleep = calculate_next_sync_sleep(interval_sec, now)
    next_sync = now + timedelta(seconds=sync_sleep)
    if is_day_city_time(next_sync):
        return sync_sleep
    next_start = next_active_window_start(next_sync)
    return max(1, int((next_start - now).total_seconds()))


async def run_parser(city_slug: str | None = None) -> bool:
    """Запускает parser в отдельном процессе асинхронно."""
    args = ["--city-slug", city_slug] if city_slug else None
    label = f"Парсинг товаров ({city_slug})" if city_slug else "Парсинг товаров"
    return await _run_subprocess("parser.py", label, args=args)


def skip_invalid_night_city_events(db: DBManager, events: list[dict]) -> list[str]:
    skipped: list[str] = []
    for event in events:
        if event["status"] != "pending" or not event.get("run_at_utc"):
            continue
        run_at = datetime.fromisoformat(event["run_at_utc"]).astimezone(_MSK)
        start, end = night_window_bounds_for_date(run_at.date())
        if start <= run_at < end:
            continue
        db.mark_scheduled_event_skipped(event["event_key"], "outside night window")
        skipped.append(str(event["subject_id"]))
    return skipped


def ensure_night_city_schedule(db: DBManager, now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(_MSK)).astimezone(_MSK)
    schedule_date = night_schedule_date(now)
    date_msk = schedule_date.isoformat()
    existing = db.get_scheduled_events(NIGHT_CITY_EVENT, date_msk)
    if existing:
        skipped = skip_invalid_night_city_events(db, existing)
        if skipped:
            return db.get_scheduled_events(NIGHT_CITY_EVENT, date_msk)
        return existing

    start, end = night_window_bounds_for_date(schedule_date)
    slots = max(1, int((end - start).total_seconds()) // max(1, len(NIGHT_CITY_SLUGS)))
    city_slugs = list(NIGHT_CITY_SLUGS)
    for index, city_slug in enumerate(city_slugs):
        slot_start = start + timedelta(seconds=index * slots)
        slot_end = min(end, slot_start + timedelta(seconds=slots))
        span_seconds = max(1, int((slot_end - slot_start).total_seconds()))
        run_at = slot_start + timedelta(seconds=random.randrange(span_seconds))
        db.ensure_scheduled_event(
            NIGHT_CITY_EVENT,
            date_msk,
            subject_id=city_slug,
            run_at_utc=run_at.astimezone(timezone.utc).isoformat(),
        )
    return db.get_scheduled_events(NIGHT_CITY_EVENT, date_msk)


def get_due_night_city_event(db: DBManager, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    now_msk = now.astimezone(_MSK)
    events = ensure_night_city_schedule(db, now_msk)
    for event in events:
        if event["status"] != "pending":
            continue
        run_at_utc = event.get("run_at_utc")
        if run_at_utc is None:
            continue
        run_at = datetime.fromisoformat(run_at_utc)
        if run_at <= now:
            return event
    return None


def skip_missed_night_city_events(db: DBManager, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    now_msk = now.astimezone(_MSK)
    skipped: list[str] = []
    if now_msk < night_window_end(now_msk):
        return skipped
    date_msk = night_schedule_date(now_msk).isoformat()
    for event in db.get_scheduled_events(NIGHT_CITY_EVENT, date_msk):
        if event["status"] != "pending" or not event.get("run_at_utc"):
            continue
        db.mark_scheduled_event_skipped(event["event_key"], "missed during downtime")
        skipped.append(str(event["subject_id"]))
    return skipped


async def telegram_bot_polling(telegram_bot) -> None:
    """Бесконечный цикл для ТГ бота (работает параллельно)."""
    await telegram_bot.polling_loop()


async def main_cycle(parser_controller: ParserController, db: DBManager, telegram_bot=None) -> None:
    """Главный цикл: парсинг товаров с поддержкой управления админом."""
    logger.info("="*70)
    logger.info("[RUN] Запущен автоматический парсер DNS Shop")
    logger.info("[RUN] Режим: БЕЗ БРАУЗЕРА (Playwright + Node.js для Qrator)")
    logger.info("[RUN] Интервал обновления: %d сек", config.parse_interval)
    logger.info("[RUN] Админ-панель активна")
    logger.info("="*70)

    iteration = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    wait_time = config.parse_interval
    startup_day_sync_wait_done = False

    while not parser_controller.should_stop():
        if not parser_controller.state.is_running:
            logger.info("[RUN] ⏸️  Парсер остановлен админом, ожидание команды...")
            await asyncio.sleep(5)
            continue

        iteration += 1
        parser_controller.state.iteration_count = iteration
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info("")
        logger.info("="*70)
        logger.info("[RUN] Итерация #%d [%s]", iteration, timestamp)
        if consecutive_errors > 0:
            logger.warning("[RUN] Подряд ошибок: %d/%d", consecutive_errors, max_consecutive_errors)
        logger.info("="*70)

        parser_success = True
        handled_night_iteration = False
        skipped = skip_missed_night_city_events(db)
        if skipped:
            logger.info("[RUN] Night events skipped after downtime: %s", ", ".join(skipped))

        if is_night_time():
            due_event = get_due_night_city_event(db)
            if due_event is None:
                now_local = datetime.now(_MSK)
                next_morning = night_window_end(now_local)
                pending_events = [
                    event for event in ensure_night_city_schedule(db, now_local)
                    if event["status"] == "pending" and event.get("run_at_utc")
                ]
                if pending_events:
                    next_run_utc = min(datetime.fromisoformat(event["run_at_utc"]) for event in pending_events)
                    sleep_until = min(next_morning, next_run_utc.astimezone(_MSK))
                else:
                    sleep_until = next_morning
                sleep_seconds = max(1, int((sleep_until - now_local).total_seconds()))
                logger.info("[RUN] No due night city parses. Sleeping %d sec.", sleep_seconds)
                try:
                    await asyncio.sleep(sleep_seconds)
                except KeyboardInterrupt:
                    logger.info("[RUN] РћСЃС‚Р°РЅРѕРІР»РµРЅРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»РµРј (Ctrl+C)")
                    break
                continue

            city_slug = str(due_event["subject_id"])
            if not can_start_city_parse():
                db.mark_scheduled_event_skipped(due_event["event_key"], "insufficient night window")
                parser_success = False
            else:
                db.mark_scheduled_event_done(due_event["event_key"])
                parser_success = await parser_controller.run_parse(city_slug)
            handled_night_iteration = True
        elif is_day_city_time():
            if not startup_day_sync_wait_done:
                startup_day_sync_wait_done = True
                now_local = datetime.now(_MSK)
                sleep_seconds = calculate_day_sync_sleep(wait_time, now_local)
                logger.info(
                    "[RUN] Startup inside day window, waiting %d sec until scheduled %s parse.",
                    sleep_seconds,
                    DAY_CITY_SLUG,
                )
                try:
                    await asyncio.sleep(sleep_seconds)
                except KeyboardInterrupt:
                    logger.info("[RUN] Stopped by user (Ctrl+C)")
                    break
                continue
            parser_success = await parser_controller.run_parse(DAY_CITY_SLUG)
        else:
            startup_day_sync_wait_done = True
            now_local = datetime.now(_MSK)
            sleep_seconds = calculate_sleep_until_next_active_window(now_local)
            logger.info("[RUN] Outside parse windows, sleeping %d sec.", sleep_seconds)
            try:
                await asyncio.sleep(sleep_seconds)
            except KeyboardInterrupt:
                logger.info("[RUN] Stopped by user (Ctrl+C)")
                break
            continue

        if parser_success:
            consecutive_errors = 0
            logger.info("[RUN] ✅ Парсер завершен успешно")
        else:
            consecutive_errors += 1
            logger.error("[RUN] ❌ Парсер завершен с ошибкой (%d/%d)", consecutive_errors, max_consecutive_errors)

            if consecutive_errors >= max_consecutive_errors:
                logger.critical("[RUN] 🔴 Достигнуто максимальное число ошибок подряд (%d). Требуется вмешательство!", consecutive_errors)
                if telegram_bot and telegram_bot.admin_id:
                    await telegram_bot.send_message(
                        telegram_bot.admin_id,
                        f"🔴 Парсер: {consecutive_errors} ошибок подряд — требуется вмешательство!\n"
                        f"Парсер приостановлен.",
                    )
                # Экспоненциальный backoff: 2^(N-5) минут, максимум 60 минут
                backoff = min(60 * (2 ** (consecutive_errors - max_consecutive_errors)), 3600)
                logger.warning("[RUN] ⏳ Circuit breaker: ожидание %d сек перед следующей попыткой", backoff)
                await asyncio.sleep(backoff)

        # Проверяем новый интервал (если админ изменил)
        new_interval = parser_controller.get_pending_interval()
        if new_interval:
            wait_time = new_interval
            logger.info("[RUN] ⏱️  Новый интервал: %d сек", wait_time)

        # Проверяем ночное время (00:00-06:00)
        # Night window sleep until next scheduled city or end of window
        if is_night_time() and handled_night_iteration:
            now = datetime.now(_MSK)
            next_morning = night_window_end(now)
            pending_events = [
                event for event in ensure_night_city_schedule(db, now)
                if event["status"] == "pending" and event.get("run_at_utc")
            ]
            if pending_events:
                next_run_utc = min(datetime.fromisoformat(event["run_at_utc"]) for event in pending_events)
                sleep_until = min(next_morning, next_run_utc.astimezone(_MSK))
            else:
                sleep_until = next_morning
            sleep_seconds = max(1, int((sleep_until - now).total_seconds()))
            logger.info("[RUN] Night window active, sleeping %d sec...", sleep_seconds)
            try:
                await asyncio.sleep(sleep_seconds)
            except KeyboardInterrupt:
                logger.info("[RUN] Stopped by user (Ctrl+C)")
                break
            continue

        # Синхронизируем запуски с крон (как будто настроен крон с интервалом)
        sync_sleep = calculate_day_sync_sleep(wait_time)
        logger.info("[RUN] Синхронный запуск через %d сек (интервал %d сек)...", sync_sleep, wait_time)
        try:
            await asyncio.sleep(sync_sleep)
        except KeyboardInterrupt:
            logger.info("[RUN] Остановлено пользователем (Ctrl+C)")
            break


async def main() -> None:
    """Запускает основной цикл и ТГ бота параллельно."""

    # Инициализируем контроллер парсера и БД
    parser_controller = ParserController(run_parser)
    db = DBManager(config.db_path)
    telegram_bot = init_telegram_bot(db, parser_controller)
    notifier = TelegramNotifier(bot=telegram_bot, db=db)
    daily_scheduler = DailyScheduler(db, notifier)
    daily_scheduler.ensure_due_events()

    # Автоматический старт парсера при запуске
    await parser_controller.start()

    # Создаем две независимые задачи:
    # 1. Основной цикл (get_cookies + parser) с поддержкой управления
    # 2. ТГ бот (polling - обработка команд)

    tasks = [
        asyncio.create_task(main_cycle(parser_controller, db, telegram_bot)),
        asyncio.create_task(telegram_bot_polling(telegram_bot)),
        asyncio.create_task(daily_scheduler.run_forever()),
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[RUN] Остановлено, завершение...")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await telegram_bot.close()
        db.close()
        logger.info("[RUN] Выход")


if __name__ == "__main__":
    _single_instance_lock = acquire_single_instance_lock()
    if _single_instance_lock is None and sys.platform.startswith("linux"):
        sys.exit(0)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[RUN] Выход")
        sys.exit(0)
    except Exception as e:
        logger.error("[RUN] Критическая ошибка: %s", e)
        sys.exit(1)
