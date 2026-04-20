"""
Telegram бот для управления подписками на уведомления и админ-панель.
"""

import asyncio
import aiohttp
from typing import Optional, Set
import json

from config import config
from utils.logger import logger


class TelegramBot:
    """Telegram бот для управления подписками и админ-панели."""

    def __init__(self, db_manager=None, parser_controller=None) -> None:
        self.token = config.telegram_token
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.db = db_manager
        self.parser_controller = parser_controller
        self.enabled = bool(self.token)
        self.admin_id = str(config.telegram_chat_admin) if hasattr(config, 'telegram_chat_admin') else None
        self.subscribed_users: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._waiting_for_interval: Set[str] = set()

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

    async def send_message(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Отправляет сообщение пользователю с опциональной клавиатурой."""
        if not self.enabled:
            return False

        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            async with self._get_session().post(
                f"{self.api_url}/sendMessage",
                json=payload,
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

    def _get_available_commands(self, user_id: str) -> str:
        """Возвращает список доступных команд для пользователя."""
        commands = (
            "/start - подписаться на уведомления о новых товарах\n"
            "/stop - отписаться от уведомлений"
        )

        if user_id == self.admin_id:
            commands += "\n/admin - панель управления"

        return "Доступные команды:\n" + commands

    async def handle_update(self, update: dict) -> None:
        """Обрабатывает обновление от Telegram (сообщения и callback-кнопки)."""
        # Обработка callback-кнопок (inline)
        if "callback_query" in update:
            await self._handle_callback_query(update["callback_query"])
            return

        # Обработка сообщений
        if "message" not in update:
            return

        message = update["message"]
        user_id = str(message.get("from", {}).get("id", ""))
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not user_id or not text or not chat_id:
            return

        try:
            # Если ждем ответ с новым интервалом
            if user_id in self._waiting_for_interval:
                await self._handle_interval_input(user_id, chat_id, text)
                return

            # Команда /admin (только для администратора)
            if text == "/admin":
                await self._handle_admin_command(user_id, chat_id)
                return

            # Команда /start
            if text == "/start":
                if user_id in self.subscribed_users:
                    await self.send_message(
                        chat_id,
                        "Вы уже подписаны на уведомления о новых товарах!"
                    )
                else:
                    self._add_subscriber(user_id)
                    await self.send_message(
                        chat_id,
                        "✅ Подписка включена! Вы будете получать уведомления о новых товарах!"
                    )

                await self.send_message(chat_id, self._get_available_commands(user_id))
                return

            # Команда /stop
            if text == "/stop":
                if user_id in self.subscribed_users:
                    self._remove_subscriber(user_id)
                    await self.send_message(
                        chat_id,
                        "✅ Подписка отключена. Вы больше не будете получать уведомления."
                    )
                else:
                    await self.send_message(
                        chat_id,
                        "Вы не подписаны на уведомления."
                    )

                await self.send_message(chat_id, self._get_available_commands(user_id))
                return

            # Неизвестная команда
            await self.send_message(
                chat_id,
                self._get_available_commands(user_id)
            )
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при обработке сообщения: %s", exc)

    async def _handle_admin_command(self, user_id: str, chat_id: str) -> None:
        """Обработка команды /admin с меню управления."""
        # Проверка прав администратора
        if user_id != self.admin_id:
            logger.warning("[TG BOT ADMIN] Попытка доступа к админ-панели от пользователя %s", user_id)
            await self.send_message(chat_id, "❌ У вас нет доступа к админ-панели")
            return

        if not self.parser_controller:
            await self.send_message(chat_id, "❌ Контроллер парсера не инициализирован")
            return

        # Создаем inline-кнопки
        markup = {
            "inline_keyboard": [
                [
                    {"text": "▶️ Запустить", "callback_data": "admin_start"},
                    {"text": "⏹ Остановить", "callback_data": "admin_stop"}
                ],
                [
                    {"text": "🔄 Перезапустить", "callback_data": "admin_restart"},
                    {"text": "⏱ Интервал", "callback_data": "admin_interval"}
                ],
                [
                    {"text": "📄 Логи", "callback_data": "admin_logs"}
                ],
                [
                    {"text": "📊 Статус", "callback_data": "admin_status"}
                ]
            ]
        }

        logger.info("[TG BOT ADMIN] Админ-панель открыта для %s", user_id)
        await self.send_message(
            chat_id,
            "🎛️ <b>Админ-панель парсера DNS</b>\n\n"
            "Выберите действие:",
            reply_markup=markup
        )

    async def _handle_callback_query(self, callback_query: dict) -> None:
        """Обработка нажатий inline-кнопок."""
        try:
            callback_id = callback_query.get("id", "")
            user_id = str(callback_query.get("from", {}).get("id", ""))
            chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
            data = callback_query.get("data", "")

            logger.debug(
                "[TG BOT ADMIN] Получен callback: user=%s, chat=%s, data=%s, admin_id=%s",
                user_id, chat_id, data, self.admin_id
            )

            if not self.admin_id:
                logger.warning("[TG BOT ADMIN] ❌ TELEGRAM_CHAT_ADMIN не установлен в .env")
                await self._answer_callback(callback_id, "❌ Админ-панель не сконфигурирована", alert=True)
                return

            if user_id != self.admin_id:
                logger.warning("[TG BOT ADMIN] Попытка доступа от %s (админ: %s)", user_id, self.admin_id)
                await self._answer_callback(callback_id, "❌ Нет доступа", alert=True)
                return

            if not self.parser_controller:
                logger.error("[TG BOT ADMIN] ❌ parser_controller не инициализирован")
                await self._answer_callback(callback_id, "❌ Ошибка: контроллер не готов", alert=True)
                return

            # Обработка команд
            if data == "admin_start":
                if await self.parser_controller.start():
                    await self._answer_callback(callback_id, "✅ Парсер запущен")
                else:
                    await self._answer_callback(callback_id, "⚠️ Парсер уже работает", alert=True)
                logger.info("[TG BOT ADMIN] Парсер запущен админом %s", user_id)

            elif data == "admin_stop":
                if await self.parser_controller.stop():
                    await self._answer_callback(callback_id, "✅ Парсер остановлен")
                else:
                    await self._answer_callback(callback_id, "⚠️ Парсер уже остановлен", alert=True)
                logger.info("[TG BOT ADMIN] Парсер остановлен админом %s", user_id)

            elif data == "admin_restart":
                await self.parser_controller.restart()
                await self._answer_callback(callback_id, "✅ Парсер перезагружен")
                logger.info("[TG BOT ADMIN] Парсер перезагружен админом %s", user_id)

            elif data == "admin_interval":
                self._waiting_for_interval.add(user_id)
                await self._answer_callback(callback_id, "")
                await self.send_message(
                    chat_id,
                    "⏱️ <b>Установка интервала</b>\n\n"
                    "Введите новый интервал в секундах (минимум 60):\n"
                    "<i>Например: 1800</i>"
                )
                logger.info("[TG BOT ADMIN] Запрос интервала от админа %s", user_id)

            elif data == "admin_logs":
                await self._answer_callback(callback_id, "")
                await self._send_logs(chat_id)

            elif data == "admin_status":
                await self._answer_callback(callback_id, "")
                status = self.parser_controller.get_status()
                await self.send_message(
                    chat_id,
                    f"<b>📊 Статус парсера:</b>\n\n{status}"
                )
                logger.info("[TG BOT ADMIN] Статус запрошен админом %s", user_id)

        except Exception as exc:
            logger.error("[TG BOT ADMIN] Ошибка при обработке callback: %s", exc)

    async def _handle_interval_input(self, user_id: str, chat_id: str, text: str) -> None:
        """Обработка ввода нового интервала."""
        self._waiting_for_interval.discard(user_id)

        try:
            interval = int(text.strip())
            if interval < 60:
                await self.send_message(
                    chat_id,
                    "❌ Интервал должен быть минимум 60 секунд"
                )
                return

            if await self.parser_controller.set_interval(interval):
                await self.send_message(
                    chat_id,
                    f"✅ Интервал установлен на {interval} сек\n"
                    f"(будет применен после следующей итерации)"
                )
                logger.info("[TG BOT ADMIN] Интервал изменен на %d сек админом %s", interval, user_id)
            else:
                await self.send_message(chat_id, "❌ Ошибка при установке интервала")
        except ValueError:
            await self.send_message(
                chat_id,
                "❌ Некорректное значение. Введите число секунд"
            )

    async def _send_logs(self, chat_id: str) -> None:
        """Отправляет последние 100 строк логов."""
        try:
            log_file = "logs/app.log"
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    last_lines = lines[-100:] if len(lines) > 100 else lines
                    logs_text = "".join(last_lines)

                if len(logs_text) > 4096:
                    chunks = [logs_text[i:i+4096] for i in range(0, len(logs_text), 4096)]
                    for chunk in chunks:
                        await self.send_message(
                            chat_id,
                            f"<pre>{chunk}</pre>",
                        )
                else:
                    await self.send_message(
                        chat_id,
                        f"<pre>{logs_text}</pre>",
                    )
            except FileNotFoundError:
                await self.send_message(chat_id, "❌ Логи не найдены (logs/app.log)")
        except Exception as exc:
            logger.error("[TG BOT ADMIN] Ошибка при отправке логов: %s", exc)
            await self.send_message(chat_id, f"❌ Ошибка: {exc}")

    async def _answer_callback(self, callback_id: str, text: str, alert: bool = False) -> bool:
        """Отправляет ответ на callback_query (уведомление)."""
        try:
            payload = {
                "callback_query_id": callback_id,
                "text": text,
                "show_alert": alert
            }
            async with self._get_session().post(
                f"{self.api_url}/answerCallbackQuery",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при отправке callback ответа: %s", exc)
            return False

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
                        params={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
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


def init_telegram_bot(db_manager, parser_controller=None) -> TelegramBot:
    """Инициализирует Telegram бот."""
    global telegram_bot
    telegram_bot = TelegramBot(db_manager, parser_controller)
    return telegram_bot


def get_telegram_bot() -> Optional[TelegramBot]:
    """Получает инстанс бота."""
    return telegram_bot
