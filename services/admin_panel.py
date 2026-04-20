"""
Админ-панель для управления парсером.
"""

import asyncio
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from utils.logger import logger


@dataclass
class ParserState:
    """Состояние парсера."""
    is_running: bool = False
    is_paused: bool = False
    current_interval: int = 3600
    last_start_time: Optional[datetime] = None
    iteration_count: int = 0


class ParserController:
    """Контроллер для управления парсером из админ-панели."""

    def __init__(self) -> None:
        self.state = ParserState()
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._interval_changed_event = asyncio.Event()
        self._pending_interval: Optional[int] = None

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
        await self.stop()
        await asyncio.sleep(1)
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
        """Возвращает статус парсера."""
        status = "⏹️  **Остановлен**"

        if self.state.is_running:
            if self.state.is_paused:
                status = "⏸️  **На паузе**"
            else:
                status = "▶️  **Работает**"

        info = f"{status}\n"
        info += f"📊 **Интервал:** {self.state.current_interval} сек\n"

        if self.state.last_start_time:
            info += f"⏰ **Запущен:** {self.state.last_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"

        if self.state.iteration_count > 0:
            info += f"📈 **Итераций:** {self.state.iteration_count}"

        return info

    def increment_iteration(self) -> None:
        """Увеличивает счетчик итераций."""
        self.state.iteration_count += 1
