"""
TelegramBot — фасад, собирающий все модули бота воедино.
Бывший монолитный telegram_bot.py (~1921 стр.) разбит на:
  utils.py, state.py, keyboards.py, handlers/{reports,settings,admin}.py
"""
import asyncio
import aiohttp
from typing import Any, Optional, Set

from config import config
from utils.logger import logger

from . import keyboards as kb
from . import utils as tg_utils
from .state import ReportMachine, UserState
from .handlers.reports import ReportWizard
from .handlers.settings import SettingsHandler
from .handlers.admin import AdminHandler


class TelegramBot:
    """Telegram бот для управления подписками и админ-панелью.

    Все бизнес-логика делегируется обработчикам:
      - _report_wizard: мастер отчётов
      - _settings: настройки пользователя
      - _admin: админ-панель
    """

    def __init__(self, db_manager=None, parser_controller=None) -> None:
        self.token = config.telegram_token
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.admin_token = config.admin_telegram_token or self.token
        self.admin_api_url = f"https://api.telegram.org/bot{self.admin_token}"
        self.db = db_manager
        self.parser_controller = parser_controller
        self.enabled = bool(self.token)
        self.admin_id = str(config.telegram_chat_admin) if hasattr(config, 'telegram_chat_admin') else None
        self.subscribed_users: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None

        # Единое хранилище состояния пользовательских сессий
        self._user_state = UserState()

        # backward-compat: раскрываем locks как атрибуты (не property),
        # чтобы тесты могли их перезаписывать
        self._broadcast_lock = self._user_state.broadcast_lock
        self._subscriber_lock = self._user_state.subscriber_lock

        # Обработчики (создаются здесь, чтобы избежать циклических импортов)
        self._report_wizard = ReportWizard(self)
        self._settings = SettingsHandler(self, self._report_wizard)
        self._admin = AdminHandler(self)
        self._report_machine = ReportMachine(self._user_state)

        if self.db and self.enabled:
            self.subscribed_users = self._load_subscribers()

        # ── Backward-compat aliases (для тестов и внешнего кода) ───────────

        # State dicts — доступны как атрибуты бота для обратной совместимости
        # NOTE: _waiting_for_interval не дублируем как атрибут т.к. он жестко
        # перекрыт @property ниже; используйте self._user_state.waiting_for_interval
        self._user_cat_page = self._user_state.user_cat_page
        self._report_state = self._user_state.report_state
        self._report_cat_page = self._user_state.report_cat_page
        self._report_search_mode = self._user_state.report_search_mode
        self._settings_search_mode = self._user_state.settings_search_mode
        self._user_cat_query = self._user_state.user_cat_query

        # _handle_report_callback переехал в ReportWizard
        self._handle_report_callback = self._report_wizard.handle
        # _handle_user_settings_callback переехал в SettingsHandler
        self._handle_user_settings_callback = self._settings.handle_callback
        # _handle_interval_input и _send_logs — в AdminHandler
        self._handle_interval_input = self._admin._handle_interval_input
        self._send_logs = self._admin._send_logs

        # _REPORT_PERIODS переехал в state
        from .state import _REPORT_PERIODS as _rp
        self._REPORT_PERIODS = _rp

        # _get_report_state — обёртка над _user_state.report_state
        self._get_report_state = self._report_machine.get_state
        self._new_report_state = self._report_machine.new_state  # для тестов

        # Text input handlers for search mode (were on TelegramBot, now in handlers)
        self._handle_report_search_input = self._report_wizard.handle_search_input
        self._handle_settings_cat_search_input = self._settings.handle_search_input
        self._send_report = self._report_wizard._send_report

    # ── HTTP infrastructure ───────────────────────────────────────────────────

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def _telegram_request(
        self,
        method: str,
        *,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> tuple[int, dict]:
        """Низкоуровневый запрос к Telegram Bot API. Возвращает (status, data)."""
        kwargs: dict = {}
        if json is not None:
            kwargs["json"] = json
        if params is not None:
            kwargs["params"] = params
        if timeout is not None:
            kwargs["timeout"] = aiohttp.ClientTimeout(total=timeout)

        async with self._get_session().post(
            f"{self.api_url}/{method}", **kwargs
        ) as resp:
            return resp.status, await resp.json()

    async def _db_call(self, sync_fn, *args, **kwargs):
        """Обёртка для вызова синхронной DB-функции в отдельном потоке."""
        return await asyncio.to_thread(sync_fn, *args, **kwargs)

    async def _answer_callback(
        self, callback_id: str, text: str = "", alert: bool = False
    ) -> bool:
        """Отвечает на callback_query (снимает "загрузку" у кнопки)."""
        try:
            payload = {
                "callback_query_id": callback_id,
                "text": text,
                "show_alert": alert,
            }
            status, data = await self._telegram_request(
                "answerCallbackQuery",
                json=payload,
                timeout=10,
            )
            if status == 200 and data.get("ok", True):
                return True
            logger.debug(
                "[TG BOT] answerCallbackQuery status=%s description=%s",
                status,
                data.get("description", ""),
            )
            return False
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при отправке callback ответа: %s", exc)
            return False

    # ── Subscriber management ─────────────────────────────────────────────────

    def _load_subscribers(self) -> Set[str]:
        try:
            users = self.db.get_telegram_subscribers()
            logger.info("[TG BOT] Загружено %d подписчиков", len(users))
            return set(users)
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при загрузке подписчиков: %s", exc)
            return set()

    async def _add_subscriber(self, user_id: str, user_info: Optional[dict] = None) -> bool:
        if not self.db or not self.enabled:
            return False
        async with self._user_state.subscriber_lock:
            try:
                info = user_info or {}
                self.db.add_telegram_subscriber(
                    user_id,
                    first_name=info.get("first_name"),
                    last_name=info.get("last_name"),
                    username=info.get("username"),
                    language_code=info.get("language_code"),
                )
                self.subscribed_users.add(user_id)
                logger.info("[TG BOT] Добавлен подписчик: %s", user_id)
                return True
            except Exception as exc:
                logger.error("[TG BOT] Ошибка при добавлении подписчика: %s", exc)
                return False

    async def _remove_subscriber(self, user_id: str) -> bool:
        if not self.db or not self.enabled:
            return False
        async with self._user_state.subscriber_lock:
            try:
                self.db.remove_telegram_subscriber(user_id)
                self.subscribed_users.discard(user_id)
                self._user_state.cleanup(user_id)
                logger.info("[TG BOT] Удален подписчик: %s", user_id)
                return True
            except Exception as exc:
                logger.error("[TG BOT] Ошибка при удалении подписчика: %s", exc)
                return False

    # ── Message sending ───────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> str:
        """Отправляет сообщение. Возвращает: 'ok' | 'blocked' | 'fail'."""
        if not self.enabled:
            return "fail"

        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(3):
            try:
                status, data = await self._telegram_request(
                    "sendMessage", json=payload, timeout=15
                )
                if status == 200 and data.get("ok"):
                    return "ok"
                if status == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", 5)
                    logger.warning("[TG BOT] Rate limit, жду %d сек (попытка %d/3)", retry_after, attempt + 1)
                    await asyncio.sleep(retry_after + 1)
                    continue
                if status == 403:
                    logger.info("[TG BOT] Пользователь %s заблокировал бота (403): %s",
                                chat_id, data.get("description"))
                    return "blocked"
                desc = data.get("description", "")
                if status == 400 and ("chat not found" in desc.lower() or "user is deactivated" in desc.lower()):
                    logger.info("[TG BOT] Чат %s недоступен (%s): %s", chat_id, status, desc)
                    return "blocked"
                logger.warning("[TG BOT] Ответ %d при отправке в %s (попытка %d/3): %s",
                               status, chat_id, attempt + 1, desc)
                if status >= 500:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return "fail"
            except Exception as exc:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning("[TG BOT] Ошибка отправки, retry через %d сек: %s", wait, exc)
                    await asyncio.sleep(wait)
                else:
                    logger.error("[TG BOT] Ошибка при отправке сообщения: %s", exc)
        return "fail"

    async def send_admin_message(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> str:
        """Отправляет админ-сообщение через админ-токен (fallback на основной токен). Возвращает: 'ok' | 'blocked' | 'fail'."""
        if not self.enabled:
            return "fail"

        # Если админ-токен не задан, используем обычный send_message
        if self.admin_token == self.token:
            return await self.send_message(chat_id, text, reply_markup)

        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(3):
            try:
                async with self._get_session().post(
                    f"{self.admin_api_url}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    status = resp.status
                    data = await resp.json()

                    if status == 200 and data.get("ok"):
                        return "ok"
                    if status == 429:
                        retry_after = data.get("parameters", {}).get("retry_after", 5)
                        logger.warning("[TG BOT ADMIN] Rate limit, жду %d сек (попытка %d/3)", retry_after, attempt + 1)
                        await asyncio.sleep(retry_after + 1)
                        continue
                    if status == 403:
                        logger.info("[TG BOT ADMIN] Пользователь %s заблокировал админ-бота (403): %s",
                                    chat_id, data.get("description"))
                        return "blocked"
                    desc = data.get("description", "")
                    if status == 400 and ("chat not found" in desc.lower() or "user is deactivated" in desc.lower()):
                        logger.info("[TG BOT ADMIN] Чат %s недоступен (%s): %s", chat_id, status, desc)
                        return "blocked"
                    logger.warning("[TG BOT ADMIN] Ответ %d при отправке в %s (попытка %d/3): %s",
                                   status, chat_id, attempt + 1, desc)
                    if status >= 500:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    return "fail"
            except Exception as exc:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning("[TG BOT ADMIN] Ошибка отправки, retry через %d сек: %s", wait, exc)
                    await asyncio.sleep(wait)
                else:
                    logger.error("[TG BOT ADMIN] Ошибка при отправке админ-сообщения: %s", exc)
        return "fail"

    async def broadcast_message(self, text: str) -> int:
        """Рассылает сообщение всем подписчикам. Возвращает кол-во успешных."""
        if not self.enabled:
            return 0

        async with self._user_state.broadcast_lock:
            success_count = 0
            blocked_users: list[str] = []
            _BROADCAST_BATCH = 200

            if self.db:
                total = self.db.count_telegram_subscribers()
                if total == 0:
                    return 0
                logger.info("[TG BOT] Отправляем сообщение %d подписчикам...", total)
                offset = 0
                while True:
                    batch = self.db.get_telegram_subscribers(limit=_BROADCAST_BATCH, offset=offset)
                    if not batch:
                        break
                    for user_id in batch:
                        result = await self.send_message(str(user_id), text)
                        if result == "ok":
                            success_count += 1
                        elif result == "blocked":
                            blocked_users.append(str(user_id))
                        await asyncio.sleep(1.1)
                    offset += len(batch)
                    if len(batch) < _BROADCAST_BATCH:
                        break
            else:
                # Fallback если БД недоступна — итерируемся по in-memory set
                users = list(self.subscribed_users)
                if not users:
                    return 0
                logger.info("[TG BOT] Отправляем сообщение %d подписчикам (in-memory)...", len(users))
                for user_id in users:
                    result = await self.send_message(str(user_id), text)
                    if result == "ok":
                        success_count += 1
                    elif result == "blocked":
                        blocked_users.append(str(user_id))
                    await asyncio.sleep(1.1)

            # Удаляем заблокировавших после полного прохода
            for user_id in blocked_users:
                await self._remove_subscriber(user_id)
            if blocked_users:
                logger.info("[TG BOT] Удалено %d заблокировавших подписчиков", len(blocked_users))

            logger.info("[TG BOT] Сообщение отправлено %d подписчикам", success_count)
            return success_count

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            status, data = await self._telegram_request(
                "editMessageText",
                json=payload,
                timeout=10,
            )
            if status == 200 and data.get("ok", True):
                return True
            desc = data.get("description", "")
            if status == 400 and "message is not modified" in desc.lower():
                return True
            logger.debug("[TG BOT] editMessageText status=%s description=%s", status, desc)
            return False
        except Exception as exc:
            logger.debug("[TG BOT] editMessageText error: %s", exc)
            return False

    # ── Main entry point ───────────────────────────────────────────────────────

    async def handle_update(self, update: dict) -> None:
        """Обрабатывает обновление от Telegram (сообщения и callback-кнопки)."""
        # callback_query
        if "callback_query" in update:
            logger.info("[TG BOT] ✉️  Получен callback_query")
            await self._handle_callback_query(update["callback_query"])
            return

        # сообщение без text
        if "message" not in update:
            logger.debug("[TG BOT] Обновление без message/callback_query: %s", list(update.keys()))
            return

        message = update["message"]
        user_id = str(message.get("from", {}).get("id", ""))
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not user_id or not text or not chat_id:
            return

        try:
            # Ожидание ввода интервала
            if user_id in self._user_state.waiting_for_interval:
                await self._admin._handle_interval_input(user_id, chat_id, text)
                return

            # Поиск категорий в отчёте
            if user_id in self._user_state.report_search_mode:
                await self._report_wizard.handle_search_input(user_id, text)
                return

            # Поиск категорий в настройках
            if user_id in self._user_state.settings_search_mode:
                await self._settings.handle_search_input(user_id, text)
                return

            # /admin
            if text == "/admin":
                await self._admin._handle_admin_command(user_id, chat_id)
                return

            # /start
            if text == "/start":
                if user_id in self.subscribed_users:
                    await self.send_message(chat_id, "Вы уже подписаны на уведомления о новых товарах!")
                else:
                    await self._add_subscriber(user_id, user_info=message.get("from", {}))
                    if self.db:
                        self.db.upsert_user_settings(user_id)
                    await self.send_message(chat_id, "✅ Подписка включена! Вы будете получать уведомления о новых товарах!")

                    # Уведомление админу о новом пользователе
                    if self.admin_id:
                        user_info = message.get("from", {})
                        first = user_info.get("first_name", "—")
                        last = user_info.get("last_name", "—")
                        username = user_info.get("username", "—")
                        lang = user_info.get("language_code", "—")
                        admin_text = (
                            f"🆕 <b>Новый пользователь</b>\n"
                            f"Имя: {first} {last}\n"
                            f"Username: @{username}\n"
                            f"TG ID: <code>{user_id}</code>\n"
                            f"Язык: {lang}"
                        )
                        await self.send_admin_message(self.admin_id, admin_text)
                await self.send_message(
                    chat_id, "Выберите действие:",
                    reply_markup=self._build_main_menu_keyboard(user_id, self.admin_id),
                )
                return

            # /stop
            if text == "/stop":
                if user_id in self.subscribed_users:
                    await self._remove_subscriber(user_id)
                    await self.send_message(chat_id, "✅ Подписка отключена. Вы больше не будете получать уведомления.")
                else:
                    await self.send_message(chat_id, "Вы не подписаны на уведомления.")
                return

            # Команды настроек — только подписчикам
            if text in ("/settings", "/city", "/categories", "/status"):
                if user_id not in self.subscribed_users:
                    await self.send_message(
                        chat_id,
                        "❌ Команда доступна только подписчикам. Нажмите /start для подписки"
                    )
                    return
                await self._settings.handle_command(user_id, chat_id, text)
                return

            # Неизвестная команда — меню для подписчиков
            if user_id in self.subscribed_users:
                await self.send_message(
                    chat_id,
                    "Выберите действие:",
                    reply_markup=self._build_main_menu_keyboard(user_id, self.admin_id),
                )
                return

            # Неизвестная команда от неподписчика
            await self.send_message(chat_id, "Нажмите /start для начала работы с ботом.")

        except Exception as exc:
            logger.error("[TG BOT] Ошибка при обработке обновления: %s", exc, exc_info=True)

    def _build_main_menu_keyboard(self, user_id: str, admin_id: str | None = None) -> dict:
        return kb._build_main_menu_keyboard(user_id, admin_id or self.admin_id)

    # ── Callback router ───────────────────────────────────────────────────────

    async def _handle_callback_query(self, callback_query: dict) -> None:
        """Диспетчер callback_query — делигирует в _settings или _admin."""
        try:
            callback_id = callback_query.get("id", "")
            user_id = str(callback_query.get("from", {}).get("id", ""))
            chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
            message_id = callback_query.get("message", {}).get("message_id")
            data = callback_query.get("data", "")

            logger.info("[TG BOT] Callback: user=%s, data=%s", user_id, data)

            # Пользовательские callbacks — не требуют прав админа
            _user_prefixes = (
                "city:", "cat_", "set_new:", "set_drop:", "set_pct:",
                "set_notif:", "set_err:", "set_pf:", "menu_", "report_"
            )
            if any(data.startswith(p) for p in _user_prefixes):
                if user_id not in self.subscribed_users:
                    await self._answer_callback(callback_id, "❌ Сначала подпишитесь через /start", alert=True)
                    return
                await self._settings.handle_callback(callback_id, user_id, chat_id, message_id, data)
                return

            # Админ-часть
            if not self.admin_id:
                logger.warning("[TG BOT ADMIN] ❌ TELEGRAM_CHAT_ADMIN не установлен в .env")
                await self._answer_callback(callback_id, "❌ Админ-панель не сконфигурирована", alert=True)
                return

            if user_id != self.admin_id:
                logger.warning("[TG BOT ADMIN] Попытка доступа от %s (админ: %s)", user_id, self.admin_id)
                await self._answer_callback(callback_id, "❌ Нет доступа", alert=True)
                return

            await self._admin.handle(callback_id, user_id, chat_id, message_id, data)

        except Exception as exc:
            logger.error("[TG BOT ADMIN] Ошибка при обработке callback: %s", exc, exc_info=True)

    # ── Admin command (called from settings handler) ──────────────────────────

    async def _handle_admin_command(
        self,
        user_id: str,
        chat_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        await self._admin._handle_admin_command(user_id, chat_id, message_id)

    # ── Convenience aliases для обратной совместимости с тестами ───────────────

    @staticmethod
    def _escape_html_text(value: Any) -> str:
        return tg_utils._escape_html_text("" if value is None else str(value))

    @staticmethod
    def _escape_html_attr(value: Any) -> str:
        return tg_utils._escape_html_attr("" if value is None else str(value))

    @staticmethod
    def _format_price(value: Any) -> str:
        return tg_utils._format_price(value)

    @staticmethod
    def _truncate_report_title(title: str) -> str:
        return tg_utils._truncate_report_title(title)

    def _cleanup_user_state(self, user_id: str) -> None:
        self._user_state.cleanup(user_id)

    def _is_new_products_report(self, state: dict) -> bool:
        return self._report_machine.is_new_products_report(state)

    def _is_sold_products_report(self, state: dict) -> bool:
        return self._report_machine.is_sold_products_report(state)

    def _is_no_discount_report(self, state: dict) -> bool:
        return self._report_machine.is_no_discount_report(state)

    def _report_title(self, state: dict) -> str:
        return self._report_machine.report_title(state)

    def _report_steps_total(self, state: dict) -> int:
        return self._report_machine.steps_total(state)

    def _report_condition_text(self, state: dict) -> str:
        return self._report_machine.condition_text(state)

    def _report_categories_text(self, state: dict) -> str:
        return self._report_machine.categories_text(state)

    def _report_period_text(self, state: dict) -> str:
        return self._report_machine.period_text(state)

    def _build_report_type_keyboard(self) -> dict:
        return kb._build_report_type_keyboard()

    def _build_report_step1_keyboard(self, state: dict) -> dict:
        return kb._build_report_step1_keyboard(state)

    def _build_report_step2_keyboard(self, state: dict) -> dict:
        return kb._build_report_step2_keyboard(state)

    def _build_report_step3_keyboard(self, state: dict) -> dict:
        return kb._build_report_step3_keyboard(state)

    def _build_report_step4_keyboard(self) -> dict:
        return kb._build_report_step4_keyboard()

    def _build_report_cats_keyboard(self, user_id: str) -> dict:
        if not self.db:
            return {"inline_keyboard": []}
        state = self._get_report_state(user_id)
        settings = self.db.get_user_settings(user_id) or {}
        city_slug = settings.get("city_slug", "")
        all_cats = (
            self.db.get_sold_known_categories(city_slug=city_slug)
            if self._is_sold_products_report(state)
            else self.db.get_all_known_categories(city_slug=city_slug)
        )
        return kb._build_report_cats_keyboard(
            self.db,
            user_id,
            self._report_cat_page.get(user_id, 0),
            state,
            all_cats,
        )

    def _build_settings_submenu_keyboard(self) -> dict:
        return kb._build_settings_submenu_keyboard()

    def _build_settings_keyboard(self, settings: dict) -> dict:
        return kb._build_settings_keyboard(settings)

    def _build_city_keyboard(self, current_slug: str = "") -> dict:
        return kb._build_city_keyboard(current_slug)

    def _build_admin_notify_keyboard(self, settings: dict) -> dict:
        return kb._build_admin_notify_keyboard(settings)

    def _build_categories_keyboard(self, user_id: str, page: int) -> dict:
        if not self.db:
            return {"inline_keyboard": []}
        settings = self.db.get_user_settings(user_id) or {}
        city_slug = settings.get("city_slug", "")
        all_cats = self.db.get_all_known_categories(city_slug=city_slug)
        user_cats = set(self.db.get_user_categories(user_id, city_slug))
        return kb._build_categories_keyboard(
            self.db,
            user_id,
            page,
            self._user_cat_query.get(user_id, ""),
            user_cats,
            all_cats,
        )

    async def _send_report_batches(self, chat_id: str, item_blocks: list[str]) -> bool:
        return await self._report_wizard._send_report_batches(chat_id, item_blocks)

    async def _handle_settings_command(self, user_id: str, chat_id: str) -> None:
        await self._settings._handle_settings_command(user_id, chat_id)

    async def _handle_city_command(self, user_id: str, chat_id: str) -> None:
        await self._settings._handle_city_command(user_id, chat_id)

    async def _handle_categories_command(self, user_id: str, chat_id: str) -> None:
        await self._settings._handle_categories_command(user_id, chat_id)

    async def _handle_status_command(self, user_id: str, chat_id: str) -> None:
        await self._settings._handle_status_command(user_id, chat_id)

    @property
    def _waiting_for_interval(self) -> Set[str]:
        """Алиас для _user_state.waiting_for_interval (обратная совместимость)."""
        return self._user_state.waiting_for_interval

    async def _handle_interval_input(self, user_id: str, chat_id: str, text: str) -> None:
        """Алиас для _admin._handle_interval_input (обратная совместимость)."""
        await self._admin._handle_interval_input(user_id, chat_id, text)

    async def _send_logs(self, chat_id: str) -> None:
        """Алиас для _admin._send_logs (обратная совместимость)."""
        await self._admin._send_logs(chat_id)

    # ── Polling loop ─────────────────────────────────────────────────────────

    async def polling_loop(self) -> None:
        if not self.enabled:
            logger.warning("[TG BOT] Telegram бот отключен (нет TELEGRAM_TOKEN)")
            return

        # deleteWebhook
        try:
            async with self._get_session().post(
                f"{self.api_url}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                logger.debug("[TG BOT] deleteWebhook: %d", resp.status)
        except Exception as exc:
            logger.debug("[TG BOT] deleteWebhook error: %s", exc)

        # Начальный offset — пропуск backlog
        offset = 0
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
                        logger.debug("[TG BOT] Начинаем с offset=%d", offset)
        except Exception as exc:
            logger.debug("[TG BOT] Не удалось получить начальный offset: %s", exc)

        logger.info("[TG BOT] Запущен режим polling для получения обновлений...")

        try:
            while True:
                try:
                    async with self._get_session().get(
                        f"{self.api_url}/getUpdates",
                        params={
                            "offset": offset,
                            "timeout": 30,
                            "allowed_updates": ["message", "callback_query"],
                        },
                        timeout=aiohttp.ClientTimeout(total=35),
                    ) as resp:
                        if resp.status == 409:
                            logger.warning("[TG BOT] 409 Conflict — ждём 30 сек")
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
                        for update in updates:
                            try:
                                await self.handle_update(update)
                            except Exception as exc:
                                logger.error("[TG BOT] Ошибка при обработке обновления: %s", exc, exc_info=True)
                            offset = update.get("update_id", offset) + 1

                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    logger.error("[TG BOT] Ошибка в цикле polling: %s", exc, exc_info=True)
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info("[TG BOT] Polling loop остановлен")
            raise

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("[TG BOT] Сессия закрыта")
