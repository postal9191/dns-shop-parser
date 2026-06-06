"""
Админ-панель для управления парсером.
"""

import asyncio
from datetime import datetime
from typing import Awaitable, Callable, Literal, Optional
from dataclasses import dataclass

from dns_shop_parser.data.cities import CITIES, SLUG_TO_CITY
from dns_shop_parser.utils.logger import logger


@dataclass
class ParserState:
    """Состояние парсера."""
    is_running: bool = False
    is_paused: bool = False
    current_interval: int = 3600
    last_start_time: Optional[datetime] = None
    iteration_count: int = 0


QueueStatus = Literal["queued", "duplicate", "invalid_city", "runner_missing"]


@dataclass(frozen=True)
class QueueResult:
    """Result of a manual city parse enqueue request."""
    status: QueueStatus
    city_slug: str
    position: int = 0


class ParserController:
    """Контроллер для управления парсером из админ-панели."""

    def __init__(self, parser_runner: Callable[[str | None], Awaitable[bool]] | None = None) -> None:
        self.state = ParserState()
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._interval_changed_event = asyncio.Event()
        self._pending_interval: Optional[int] = None
        self._parser_runner = parser_runner
        self._parse_lock = asyncio.Lock()
        self._manual_queue_lock = asyncio.Lock()
        self._manual_city_queue: list[str] = []
        self._manual_queue_task: asyncio.Task | None = None
        self._current_manual_city: str | None = None

    def set_parser_runner(self, parser_runner: Callable[[str | None], Awaitable[bool]]) -> None:
        """Sets async parser runner used by scheduled and manual parses."""
        self._parser_runner = parser_runner

    @property
    def current_manual_city(self) -> str | None:
        return self._current_manual_city

    @property
    def manual_queue(self) -> list[str]:
        return list(self._manual_city_queue)

    async def run_parse(self, city_slug: str | None = None) -> bool:
        """Runs parser through the shared lock, preventing parallel subprocesses."""
        if not self._parser_runner:
            logger.error("[ADMIN] Parser runner is not configured")
            return False
        async with self._parse_lock:
            return await self._parser_runner(city_slug)

    async def enqueue_city_parse(self, city_slug: str) -> QueueResult:
        """Queues a manual parser run for a supported city."""
        if city_slug not in set(CITIES.values()):
            return QueueResult("invalid_city", city_slug)
        if not self._parser_runner:
            return QueueResult("runner_missing", city_slug)

        async with self._manual_queue_lock:
            if city_slug == self._current_manual_city or city_slug in self._manual_city_queue:
                return QueueResult("duplicate", city_slug)
            self._manual_city_queue.append(city_slug)
            position = len(self._manual_city_queue)
            if not self._manual_queue_task or self._manual_queue_task.done():
                self._manual_queue_task = asyncio.create_task(self._manual_queue_worker())

        logger.info("[ADMIN] Manual city parse queued: %s", city_slug)
        return QueueResult("queued", city_slug, position)

    async def _manual_queue_worker(self) -> None:
        while True:
            async with self._manual_queue_lock:
                if not self._manual_city_queue:
                    return
                city_slug = self._manual_city_queue.pop(0)
                self._current_manual_city = city_slug

            try:
                logger.info("[ADMIN] Manual city parse started: %s", city_slug)
                result = await self.run_parse(city_slug)
                if result:
                    logger.info("[ADMIN] Manual city parse finished: %s", city_slug)
                else:
                    logger.error("[ADMIN] Manual city parse failed: %s", city_slug)
            except Exception as exc:
                logger.exception("[ADMIN] Manual city parse crashed for %s: %s", city_slug, exc)
            finally:
                async with self._manual_queue_lock:
                    if self._current_manual_city == city_slug:
                        self._current_manual_city = None

    async def start(self) -> bool:
        """Запускает парсер."""
        if self.state.is_running:
            return False

        self.state.is_running = True
        self.state.is_paused = False
        self.state.last_start_time = datetime.now()
        logger.info("[ADMIN] 🟢 Парсер запущен админом")
        return True

    async def stop(self) -> bool:
        """Останавливает парсер."""
        if not self.state.is_running:
            return False

        self.state.is_running = False
        self.state.is_paused = False
        self._stop_event.set()
        logger.info("[ADMIN] 🔴 Парсер остановлен админом")
        return True

    async def restart(self) -> bool:
        """Перезапускает парсер."""
        logger.info("[ADMIN] 🔄 Перезапуск парсера...")
        self.state.is_running = False
        self.state.is_paused = False
        self._stop_event.clear()
        await self.start()
        return True

    async def pause(self) -> bool:
        """Ставит парсер на паузу."""
        if not self.state.is_running or self.state.is_paused:
            return False

        self.state.is_paused = True
        self._pause_event.set()
        logger.info("[ADMIN] ⏸️  Парсер поставлен на паузу")
        return True

    async def resume(self) -> bool:
        """Возобновляет работу парсера."""
        if not self.state.is_running or not self.state.is_paused:
            return False

        self.state.is_paused = False
        self._pause_event.clear()
        logger.info("[ADMIN] ▶️  Парсер возобновлен")
        return True

    async def set_interval(self, seconds: int) -> bool:
        """Устанавливает новый интервал парсинга."""
        if seconds <= 0:
            return False

        self.state.current_interval = seconds
        self._pending_interval = seconds
        self._interval_changed_event.set()
        logger.info("[ADMIN] ⏱️  Интервал изменен на %d сек", seconds)
        return True

    def should_stop(self) -> bool:
        """Проверяет, нужно ли остановить парсер (для использования в run.py)."""
        return self._stop_event.is_set()

    def get_pending_interval(self) -> Optional[int]:
        """Получает ожидающий интервал и сбрасывает флаг."""
        if self._interval_changed_event.is_set():
            self._interval_changed_event.clear()
            interval = self._pending_interval
            self._pending_interval = None
            return interval
        return None

    async def wait_for_stop(self) -> None:
        """Ждет события остановки."""
        self._stop_event.clear()
        await self._stop_event.wait()

    async def wait_for_interval_change(self, timeout: float = 0.1) -> Optional[int]:
        """Ждет изменения интервала с таймаутом."""
        try:
            await asyncio.wait_for(self._interval_changed_event.wait(), timeout=timeout)
            return self.get_pending_interval()
        except asyncio.TimeoutError:
            return None

    def get_status(self) -> str:
        """Возвращает статус парсера (HTML-форматирование для Telegram)."""
        status = "⏹️  <b>Остановлен</b>"

        if self.state.is_running:
            if self.state.is_paused:
                status = "⏸️  <b>На паузе</b>"
            else:
                status = "▶️  <b>Работает</b>"

        info = f"{status}\n"
        info += f"📊 <b>Интервал:</b> {self.state.current_interval} сек\n"

        if self.state.last_start_time:
            info += f"⏰ <b>Запущен:</b> {self.state.last_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"

        if self.state.iteration_count > 0:
            info += f"📈 <b>Итераций:</b> {self.state.iteration_count}"

        queue = self.manual_queue
        if self._current_manual_city or queue:
            current = (
                SLUG_TO_CITY.get(self._current_manual_city, self._current_manual_city)
                if self._current_manual_city else "-"
            )
            waiting = ", ".join(SLUG_TO_CITY.get(slug, slug) for slug in queue) if queue else "-"
            info += (
                f"\n🏙 <b>Ручной парсинг:</b> {current}\n"
                f"📋 <b>Очередь городов:</b> {waiting}"
            )

        return info

    def increment_iteration(self) -> None:
        """Увеличивает счетчик итераций."""
        self.state.iteration_count += 1
