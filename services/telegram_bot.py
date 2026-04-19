"""
Telegram бот для управления подписками на уведомления.
"""

import asyncio
import aiohttp
from typing import Optional, Set

from config import config
from utils.logger import logger


class TelegramBot:
    """Telegram бот для управления подписками пользователей."""

    def __init__(self, db_manager=None) -> None:
        self.token = config.telegram_token
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.db = db_manager
        self.enabled = bool(self.token)
        self.subscribed_users: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None

        if self.db and self.enabled:
            self.subscribed_users = self._load_subscribers()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _load_subscribers(self) -> Set[str]:
        """Загружает список подписчиков из БД."""
        try:
            users = self.db.get_telegram_subscribers()
            logger.info("[TG BOT] Загружено %d подписчиков", len(users))
            return set(users)
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при загрузке подписчиков: %s", exc)
            return set()

    def _add_subscriber(self, user_id: str) -> bool:
        """Добавляет пользователя в подписчики."""
        if not self.db or not self.enabled:
            return False

        try:
            self.db.add_telegram_subscriber(user_id)
            self.subscribed_users.add(user_id)
            logger.info("[TG BOT] Добавлен подписчик: %s", user_id)
            return True
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при добавлении подписчика: %s", exc)
            return False

    def _remove_subscriber(self, user_id: str) -> bool:
        """Удаляет пользователя из подписчиков."""
        if not self.db or not self.enabled:
            return False

        try:
            self.db.remove_telegram_subscriber(user_id)
            self.subscribed_users.discard(user_id)
            logger.info("[TG BOT] Удален подписчик: %s", user_id)
            return True
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при удалении подписчика: %s", exc)
            return False

    async def send_message(self, chat_id: str, text: str) -> bool:
        """Отправляет сообщение пользователю."""
        if not self.enabled:
            return False

        try:
            async with self._get_session().post(
                f"{self.api_url}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при отправке сообщения: %s", exc)
            return False

    async def broadcast_message(self, text: str) -> int:
        """Отправляет сообщение всем подписчикам. Возвращает количество успешно отправленных."""
        if not self.enabled or not self.subscribed_users:
            return 0

        success_count = 0
        logger.info("[TG BOT] Отправляем сообщение %d подписчикам...", len(self.subscribed_users))

        for user_id in list(self.subscribed_users):
            if await self.send_message(user_id, text):
                success_count += 1
            else:
                # Попытка удалить неактивного пользователя
                self._remove_subscriber(user_id)
            await asyncio.sleep(0.05)  # Небольшая задержка чтобы не перегрузить API

        logger.info("[TG BOT] Сообщение отправлено %d подписчикам", success_count)
        return success_count

    async def handle_update(self, update: dict) -> None:
        """Обрабатывает обновление от Telegram."""
        if "message" not in update:
            return

        message = update["message"]
        user_id = str(message.get("from", {}).get("id", ""))
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not user_id or not text or not chat_id:
            return

        # Команда /start
        if text == "/start":
            if user_id in self.subscribed_users:
                await self.send_message(
                    chat_id,
                    "Вы уже подписаны на уведомления о новых товарах!\n"
                    "Напишите /stop для отписки."
                )
            else:
                self._add_subscriber(user_id)
                await self.send_message(
                    chat_id,
                    "Подписка включена! Вы будете получать уведомления о новых товарах!\n"
                    "Напишите /stop для отписки."
                )

        # Команда /stop
        elif text == "/stop":
            if user_id in self.subscribed_users:
                self._remove_subscriber(user_id)
                await self.send_message(
                    chat_id,
                    "Подписка отключена. Вы больше не будете получать уведомления.\n"
                    "Напишите /start чтобы снова подписаться."
                )
            else:
                await self.send_message(
                    chat_id,
                    "Вы не подписаны на уведомления.\n"
                    "Напишите /start для подписки."
                )

        # Неизвестная команда
        else:
            await self.send_message(
                chat_id,
                "Доступные команды:\n"
                "/start - подписаться на уведомления о новых товарах\n"
                "/stop - отписаться от уведомлений"
            )

    async def polling_loop(self) -> None:
        """Бесконечный цикл для получения обновлений от Telegram (polling)."""
        if not self.enabled:
            logger.warning("[TG BOT] Telegram бот отключен (нет TELEGRAM_TOKEN)")
            return

        # Удаляем вебхук и получаем начальный offset, чтобы пропустить накопившиеся сообщения
        offset = 0
        try:
            async with self._get_session().post(
                f"{self.api_url}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                logger.debug("[TG BOT] deleteWebhook: %d", resp.status)
        except Exception as exc:
            logger.debug("[TG BOT] deleteWebhook error: %s", exc)

        # Получаем последний update_id чтобы не обрабатывать старые сообщения
        try:
            async with self._get_session().get(
                f"{self.api_url}/getUpdates",
                params={"offset": -1, "timeout": 0},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    updates = data.get("result", [])
                    if updates:
                        offset = updates[-1]["update_id"] + 1
                        logger.debug("[TG BOT] Начинаем с offset=%d (пропускаем старые сообщения)", offset)
        except Exception as exc:
            logger.debug("[TG BOT] Не удалось получить начальный offset: %s", exc)

        logger.info("[TG BOT] Запущен режим polling для получения обновлений...")

        try:
            while True:
                try:
                    async with self._get_session().get(
                        f"{self.api_url}/getUpdates",
                        params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                        timeout=aiohttp.ClientTimeout(total=35),
                    ) as resp:
                        if resp.status == 409:
                            logger.warning("[TG BOT] 409 Conflict - ждём 30 сек пока предыдущий сеанс завершится")
                            await asyncio.sleep(30)
                            continue

                        if resp.status != 200:
                            logger.error("[TG BOT] Ошибка API: статус %d", resp.status)
                            await asyncio.sleep(5)
                            continue

                        data = await resp.json()
                        if not data.get("ok"):
                            logger.error("[TG BOT] API вернул ошибку: %s", data.get("description"))
                            await asyncio.sleep(5)
                            continue

                        updates = data.get("result", [])
                        if updates:
                            logger.debug("[TG BOT] Получено %d обновлений", len(updates))

                            for update in updates:
                                try:
                                    await self.handle_update(update)
                                except Exception as exc:
                                    logger.error("[TG BOT] Ошибка при обработке обновления: %s", exc)

                                offset = update.get("update_id", offset) + 1

                except asyncio.TimeoutError:
                    logger.debug("[TG BOT] Timeout при получении обновлений")
                    continue
                except Exception as exc:
                    logger.error("[TG BOT] Ошибка в polling loop: %s", exc)
                    await asyncio.sleep(5)
                    continue

        except Exception as exc:
            logger.error("[TG BOT] Критическая ошибка в polling: %s", exc)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        logger.debug("[TG BOT] Бот закрыт")


# Глобальная переменная для доступа к боту из main.py
telegram_bot: Optional[TelegramBot] = None


def init_telegram_bot(db_manager) -> TelegramBot:
    """Инициализирует Telegram бот."""
    global telegram_bot
    telegram_bot = TelegramBot(db_manager)
    return telegram_bot


def get_telegram_bot() -> Optional[TelegramBot]:
    """Получает инстанс бота."""
    return telegram_bot
