"""
Telegram бот для управления подписками на уведомления и админ-панель.
"""

import asyncio
import html as _html
import aiohttp
from typing import Any, Callable, Optional, Set, TypedDict

_MAX_SEARCH_LEN = 60
_VALID_REPORT_PCTS = {10, 20, 30, 40, 50, 60, 70, 80, 90}
_TELEGRAM_SAFE_MESSAGE_LEN = 3800
_MAX_REPORT_TITLE_LEN = 180

from config import config
from utils.logger import logger


class ReportState(TypedDict):
    kind: str
    new: bool
    bu: bool
    discount: int
    cats: list[str]
    period: str
    cat_query: str


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
        self._broadcast_lock = asyncio.Lock()
        self._subscriber_lock = asyncio.Lock()
        self._user_cat_page: dict[str, int] = {}  # user_id → текущая страница /categories
        self._report_state: dict[str, ReportState] = {}  # user_id → состояние мастера отчёта
        self._report_cat_page: dict[str, int] = {}  # user_id → страница категорий в отчёте
        self._report_search_mode: dict[str, tuple] = {}  # user_id → (chat_id, message_id) ожидание ввода поиска
        self._settings_search_mode: dict[str, tuple] = {}  # то же для /categories настроек
        self._user_cat_query: dict[str, str] = {}  # user_id → поисковый запрос в /categories

        if self.db and self.enabled:
            self.subscribed_users = self._load_subscribers()

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
        timeout: int = 10,
        http_method: str = "post",
    ) -> tuple[int, dict]:
        """Выполняет запрос к Telegram API и возвращает HTTP-статус с JSON-ответом."""
        request = self._get_session().post if http_method.lower() == "post" else self._get_session().get
        async with request(
            f"{self.api_url}/{method}",
            json=json,
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {}
            return resp.status, data

    async def _db_call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(func, *args, **kwargs)

    @staticmethod
    def _escape_html_text(value: Any) -> str:
        return _html.escape("" if value is None else str(value))

    @staticmethod
    def _escape_html_attr(value: Any) -> str:
        return _html.escape("" if value is None else str(value), quote=True)

    @staticmethod
    def _format_price(value: Any) -> str:
        if value is None:
            return "не указана"
        try:
            return f"{int(value):,}".replace(",", "\u00a0")
        except (TypeError, ValueError):
            return _html.escape(str(value))

    @staticmethod
    def _truncate_report_title(title: str) -> str:
        if len(title) <= _MAX_REPORT_TITLE_LEN:
            return title
        return f"{title[:_MAX_REPORT_TITLE_LEN - 1]}…"

    def _cleanup_user_state(self, user_id: str) -> None:
        self._waiting_for_interval.discard(user_id)
        self._user_cat_page.pop(user_id, None)
        self._report_state.pop(user_id, None)
        self._report_cat_page.pop(user_id, None)
        self._report_search_mode.pop(user_id, None)
        self._settings_search_mode.pop(user_id, None)
        self._user_cat_query.pop(user_id, None)

    def _load_subscribers(self) -> Set[str]:
        """Загружает список подписчиков из БД."""
        try:
            users = self.db.get_telegram_subscribers()
            logger.info("[TG BOT] Загружено %d подписчиков", len(users))
            return set(users)
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при загрузке подписчиков: %s", exc)
            return set()

    async def _add_subscriber(self, user_id: str, user_info: Optional[dict] = None) -> bool:
        """Добавляет пользователя в подписчики (атомарно: БД + память)."""
        if not self.db or not self.enabled:
            return False

        async with self._subscriber_lock:
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
        """Удаляет пользователя из подписчиков (атомарно: БД + память)."""
        if not self.db or not self.enabled:
            return False

        async with self._subscriber_lock:
            try:
                self.db.remove_telegram_subscriber(user_id)
                self.subscribed_users.discard(user_id)
                self._cleanup_user_state(user_id)
                logger.info("[TG BOT] Удален подписчик: %s", user_id)
                return True
            except Exception as exc:
                logger.error("[TG BOT] Ошибка при удалении подписчика: %s", exc)
                return False

    async def send_message(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> str:
        """Отправляет сообщение.

        Возвращает:
          'ok'      — сообщение принято Telegram
          'blocked' — чат удалён или пользователь заблокировал бота (можно удалить подписчика)
          'fail'    — временная или форматная ошибка (НЕ повод удалять подписчика)
        """
        if not self.enabled:
            return "fail"

        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(3):
            try:
                status, data = await self._telegram_request(
                    "sendMessage",
                    json=payload,
                    timeout=15,
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

    async def broadcast_message(self, text: str) -> int:
        """Отправляет сообщение всем подписчикам. Возвращает количество успешно отправленных.

        Пагинирует подписчиков из БД батчами по 200 — не держит весь список в памяти.
        Заблокировавших удаляет после полного прохода (избегает смещения offset при удалении).
        Сериализован через lock — параллельные вызовы не флудят чату быстрее 1 msg/sec.
        """
        if not self.enabled:
            return 0

        async with self._broadcast_lock:
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
                        result = await self.send_message(user_id, text)
                        if result == "ok":
                            success_count += 1
                        elif result == "blocked":
                            blocked_users.append(user_id)
                        # Telegram per-chat лимит ~1 msg/sec — соблюдаем с запасом
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
                    result = await self.send_message(user_id, text)
                    if result == "ok":
                        success_count += 1
                    elif result == "blocked":
                        blocked_users.append(user_id)
                    await asyncio.sleep(1.1)

            # Удаляем заблокировавших после полного прохода — offset уже не важен
            for user_id in blocked_users:
                await self._remove_subscriber(user_id)
            if blocked_users:
                logger.info("[TG BOT] Удалено %d заблокировавших подписчиков", len(blocked_users))

            logger.info("[TG BOT] Сообщение отправлено %d подписчикам", success_count)
            return success_count

    def _build_main_menu_keyboard(self, user_id: str) -> dict:
        """Строит главное inline-меню для подписчика."""
        rows = [
            [
                {"text": "⚙️ Настройки", "callback_data": "menu_settings_open"},
                {"text": "📊 Отчеты", "callback_data": "report_open"},
            ],
        ]
        if user_id == self.admin_id:
            rows.append([{"text": "🎛️ Админ-панель", "callback_data": "menu_admin"}])
        return {"inline_keyboard": rows}

    _REPORT_PERIODS = [
        ("1d",  "1 день"),
        ("3d",  "3 дня"),
        ("7d",  "Неделя"),
        ("30d", "Месяц"),
        ("all", "Весь срок"),
    ]

    def _new_report_state(self, kind: str = "discounts") -> ReportState:
        return {
            "kind": kind,
            "new": True,
            "bu": True,
            "discount": 10,
            "cats": [],
            "period": "1d",
            "cat_query": "",
        }

    def _get_report_state(self, user_id: str) -> ReportState:
        if user_id not in self._report_state:
            self._report_state[user_id] = self._new_report_state()
        else:
            self._report_state[user_id].setdefault("kind", "discounts")
            self._report_state[user_id].setdefault("cat_query", "")
        return self._report_state[user_id]

    def _is_new_products_report(self, state: dict) -> bool:
        return state.get("kind") == "new_products"

    def _is_sold_products_report(self, state: dict) -> bool:
        return state.get("kind") == "sold_products"

    def _is_no_discount_report(self, state: dict) -> bool:
        return self._is_new_products_report(state) or self._is_sold_products_report(state)

    def _report_title(self, state: dict) -> str:
        if self._is_new_products_report(state):
            return "Новые товары"
        if self._is_sold_products_report(state):
            return "Проданные товары"
        return "Скидки"

    def _report_steps_total(self, state: dict) -> int:
        return 3 if self._is_no_discount_report(state) else 4

    def _report_condition_text(self, state: dict) -> str:
        return f"📊 <b>{self._report_title(state)} — Шаг 1 из {self._report_steps_total(state)}</b>\nВыберите состояние товара:"

    def _report_categories_text(self, state: dict) -> str:
        step = 2 if self._is_no_discount_report(state) else 3
        return f"📊 <b>{self._report_title(state)} — Шаг {step} из {self._report_steps_total(state)}</b>\nВыберите категории (пусто = все):"

    def _report_period_text(self, state: dict) -> str:
        step = 3 if self._is_no_discount_report(state) else 4
        if self._is_new_products_report(state):
            date_hint = "по дате добавления товара"
        elif self._is_sold_products_report(state):
            date_hint = "по дате продажи/исчезновения товара"
        else:
            date_hint = "по дате последнего обновления цены"
        return f"📊 <b>{self._report_title(state)} — Шаг {step} из {self._report_steps_total(state)}</b>\nВыберите период ({date_hint}):"

    def _build_report_type_keyboard(self) -> dict:
        return {
            "inline_keyboard": [
                [{"text": "🏷 Скидки", "callback_data": "report_kind:discounts"}],
                [{"text": "🆕 Новые товары", "callback_data": "report_kind:new_products"}],
                [{"text": "🛒 Проданные товары", "callback_data": "report_kind:sold_products"}],
                [{"text": "🏠 Главная", "callback_data": "menu_back"}],
            ]
        }

    def _build_report_step1_keyboard(self, state: dict) -> dict:
        new_mark = "✅" if state["new"] else "❌"
        bu_mark = "✅" if state["bu"] else "❌"
        return {
            "inline_keyboard": [
                [
                    {"text": f"{new_mark} Новые", "callback_data": "report_toggle:new"},
                    {"text": f"{bu_mark} Б/У", "callback_data": "report_toggle:bu"},
                ],
                [{"text": "Далее →", "callback_data": "report_next:1"}],
                [{"text": "🏠 Главная", "callback_data": "menu_back"}],
            ]
        }

    def _build_report_step2_keyboard(self, state: dict) -> dict:
        selected = state.get("discount", 10)
        pct_rows = []
        row: list = []
        for p in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
            prefix = "✅ " if p == selected else ""
            row.append({"text": f"{prefix}{p}%", "callback_data": f"report_pct:{p}"})
            if len(row) == 3:
                pct_rows.append(row)
                row = []
        if row:
            pct_rows.append(row)
        return {
            "inline_keyboard": pct_rows + [
                [
                    {"text": "← Назад", "callback_data": "report_back:1"},
                    {"text": "Далее →", "callback_data": "report_next:2"},
                ],
                [{"text": "🏠 Главная", "callback_data": "menu_back"}],
            ]
        }

    def _build_report_cats_keyboard(self, user_id: str) -> dict:
        """Клавиатура выбора категорий для отчёта (пагинация как в /categories)."""
        if not self.db:
            return {"inline_keyboard": []}
        state = self._get_report_state(user_id)
        all_cats = (
            self.db.get_sold_known_categories()
            if self._is_sold_products_report(state)
            else self.db.get_all_known_categories()
        )
        user_cats = set(state.get("cats", []))
        query = state.get("cat_query", "").strip().lower()
        sorted_cats = sorted(all_cats, key=lambda c: (0 if c["id"] in user_cats else 1, c["name"]))
        if query:
            sorted_cats = [c for c in sorted_cats if query in c["name"].lower()]
        page = self._report_cat_page.get(user_id, 0)
        total_pages = max(1, (len(sorted_cats) + self._CATS_PER_PAGE - 1) // self._CATS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        slice_ = sorted_cats[page * self._CATS_PER_PAGE:(page + 1) * self._CATS_PER_PAGE]

        rows = []
        if not query:
            all_mark = "✅" if not user_cats else "❌"
            rows.append([{"text": f"{all_mark} Все категории", "callback_data": "report_cat_all"}])
        for cat in slice_:
            mark = "✅" if cat["id"] in user_cats else "❌"
            rows.append([{"text": f"{mark} {cat['name'][:28]}", "callback_data": f"report_cat_toggle:{cat['id']}"}])
        if not sorted_cats and query:
            rows.append([{"text": "Ничего не найдено", "callback_data": "report_cat_page:noop"}])
        nav = []
        if page > 0:
            nav.append({"text": "← Назад", "callback_data": f"report_cat_page:{page - 1}"})
        nav.append({"text": f"{page + 1}/{total_pages}", "callback_data": "report_cat_page:noop"})
        if page < total_pages - 1:
            nav.append({"text": "Вперёд →", "callback_data": f"report_cat_page:{page + 1}"})
        if nav:
            rows.append(nav)
        if query:
            rows.append([
                {"text": f'🔍 «{query[:20]}»', "callback_data": "report_cat_page:noop"},
                {"text": "❌ Сбросить", "callback_data": "report_cat_search_clear"},
            ])
        else:
            rows.append([{"text": "🔍 Поиск", "callback_data": "report_cat_search"}])
        rows.append([
            {"text": "← Назад", "callback_data": "report_back:2"},
            {"text": "Далее →", "callback_data": "report_next:cats"},
        ])
        rows.append([{"text": "🏠 Главная", "callback_data": "menu_back"}])
        return {"inline_keyboard": rows}

    def _build_report_step3_keyboard(self, state: dict) -> dict:
        selected = state.get("period", "1d")
        rows = []
        for val, label in self._REPORT_PERIODS:
            prefix = "✅ " if val == selected else ""
            rows.append([{"text": f"{prefix}{label}", "callback_data": f"report_period:{val}"}])
        return {
            "inline_keyboard": rows + [
                [
                    {"text": "← Назад", "callback_data": "report_back:cats"},
                    {"text": "Далее →", "callback_data": "report_next:3"},
                ],
                [{"text": "🏠 Главная", "callback_data": "menu_back"}],
            ]
        }

    def _build_report_step4_keyboard(self) -> dict:
        return {
            "inline_keyboard": [
                [{"text": "📥 Получить отчет", "callback_data": "report_get"}],
                [
                    {"text": "← Назад", "callback_data": "report_back:3"},
                    {"text": "🏠 Главная", "callback_data": "menu_back"},
                ],
            ]
        }

    def _build_settings_submenu_keyboard(self) -> dict:
        """Строит inline-подменю настроек."""
        return {
            "inline_keyboard": [
                [
                    {"text": "🔔 Уведомления", "callback_data": "menu_settings_cmd"},
                    {"text": "🏙 Город", "callback_data": "menu_city_cmd"},
                ],
                [
                    {"text": "📂 Категории", "callback_data": "menu_categories_cmd"},
                    {"text": "📋 Статус", "callback_data": "menu_status_cmd"},
                ],
                [{"text": "← Главное меню", "callback_data": "menu_back"}],
            ]
        }

    async def handle_update(self, update: dict) -> None:
        """Обрабатывает обновление от Telegram (сообщения и callback-кнопки)."""
        # Обработка callback-кнопок (inline)
        if "callback_query" in update:
            logger.info("[TG BOT] ✉️  Получен callback_query")
            await self._handle_callback_query(update["callback_query"])
            return

        # Обработка сообщений
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
            # Если ждем ответ с новым интервалом
            if user_id in self._waiting_for_interval:
                await self._handle_interval_input(user_id, chat_id, text)
                return

            # Если ждем поисковый запрос для категорий отчёта
            if user_id in self._report_search_mode:
                await self._handle_report_search_input(user_id, text)
                return

            # Если ждем поисковый запрос для категорий настроек
            if user_id in self._settings_search_mode:
                await self._handle_settings_cat_search_input(user_id, text)
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
                    await self._add_subscriber(user_id, user_info=message.get("from", {}))
                    if self.db:
                        self.db.upsert_user_settings(user_id)
                    await self.send_message(
                        chat_id,
                        "✅ Подписка включена! Вы будете получать уведомления о новых товарах!"
                    )

                await self.send_message(
                    chat_id,
                    "Выберите действие:",
                    reply_markup=self._build_main_menu_keyboard(user_id),
                )
                return

            # Команда /stop
            if text == "/stop":
                if user_id in self.subscribed_users:
                    await self._remove_subscriber(user_id)
                    await self.send_message(
                        chat_id,
                        "✅ Подписка отключена. Вы больше не будете получать уведомления."
                    )
                else:
                    await self.send_message(
                        chat_id,
                        "Вы не подписаны на уведомления."
                    )
                return

            # Команды настроек (только для подписчиков)
            if text in ("/settings", "/city", "/categories", "/status"):
                if user_id not in self.subscribed_users:
                    await self.send_message(
                        chat_id,
                        "❌ Команда доступна только подписчикам. Нажмите /start для подписки"
                    )
                    return
                if text == "/settings":
                    await self._handle_settings_command(user_id, chat_id)
                elif text == "/city":
                    await self._handle_city_command(user_id, chat_id)
                elif text == "/categories":
                    await self._handle_categories_command(user_id, chat_id)
                elif text == "/status":
                    await self._handle_status_command(user_id, chat_id)
                return

            # Неизвестная команда — показываем меню (только подписчикам)
            if user_id in self.subscribed_users:
                await self.send_message(
                    chat_id,
                    "Выберите действие:",
                    reply_markup=self._build_main_menu_keyboard(user_id),
                )
            else:
                await self.send_message(
                    chat_id,
                    "Нажмите /start чтобы подписаться на уведомления."
                )
        except Exception as exc:
            logger.error("[TG BOT] Ошибка при обработке сообщения: %s", exc)

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """Редактирует уже отправленное сообщение."""
        if not self.enabled:
            return False
        payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
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

    # ─── Пользовательские настройки ───────────────────────────────────────────

    _CATS_PER_PAGE = 8

    def _build_settings_keyboard(self, s: dict) -> dict:
        """Строит inline-клавиатуру для /settings на основе текущих настроек."""
        on_off = lambda v: "✅" if v else "❌"
        pct = s["min_price_drop_pct"]
        notif = s["notifications_on"]
        return {
            "inline_keyboard": [
                [{"text": f"{on_off(s['notify_new'])} Новые товары",
                  "callback_data": f"set_new:{0 if s['notify_new'] else 1}"}],
                [{"text": f"{on_off(s['notify_price_drop'])} Снижение цен",
                  "callback_data": f"set_drop:{0 if s['notify_price_drop'] else 1}"}],
                [
                    {"text": f"{'✅' if pct == 0 else ''} Любое снижение", "callback_data": "set_pct:0"},
                    {"text": f"{'✅' if pct == 5 else ''} >5%",  "callback_data": "set_pct:5"},
                    {"text": f"{'✅' if pct == 10 else ''} >10%", "callback_data": "set_pct:10"},
                    {"text": f"{'✅' if pct == 20 else ''} >20%", "callback_data": "set_pct:20"},
                ],
                [{"text": f"{on_off(notif)} Уведомления (мастер)",
                  "callback_data": f"set_notif:{0 if notif else 1}"}],
                [{"text": "← Главное меню", "callback_data": "menu_back"}],
            ]
        }

    def _build_city_keyboard(self, current_slug: str = "") -> dict:
        """Строит inline-клавиатуру выбора города (3 кнопки в ряд)."""
        from data.cities import CITIES
        cities = list(CITIES.items())
        rows = []
        for i in range(0, len(cities), 3):
            rows.append([
                {
                    "text": f"{'✅ ' if slug == current_slug else ''}{name}",
                    "callback_data": f"city:{slug}",
                }
                for name, slug in cities[i:i + 3]
            ])
        rows.append([{"text": "← Главное меню", "callback_data": "menu_back"}])
        return {"inline_keyboard": rows}

    def _build_admin_notify_keyboard(self, s: dict) -> dict:
        """Строит inline-клавиатуру уведомлений админа (✅ вкл / ❌ выкл)."""
        err_on = s.get("notify_errors", True)
        pf_on = s.get("notify_parse_finish", True)
        on_off = lambda v: "✅" if v else "❌"
        return {
            "inline_keyboard": [
                [{"text": f"{on_off(err_on)} Ошибки: {'ВКЛ' if err_on else 'ВЫКЛ'}",
                  "callback_data": f"set_err:{0 if err_on else 1}"},
                 {"text": f"{on_off(pf_on)} Парсинг: {'ВКЛ' if pf_on else 'ВЫКЛ'}",
                  "callback_data": f"set_pf:{0 if pf_on else 1}"}],
                [{"text": "← Назад в админ-панель", "callback_data": "admin_back"}],
            ]
        }

    def _build_categories_keyboard(self, user_id: str, page: int) -> dict:
        """Строит inline-клавиатуру выбора категорий с пагинацией и поиском."""
        if not self.db:
            return {"inline_keyboard": []}
        all_cats = self.db.get_all_known_categories()
        user_cats = set(self.db.get_user_categories(user_id))
        query = self._user_cat_query.get(user_id, "").strip().lower()
        sorted_cats = sorted(all_cats, key=lambda c: (0 if c["id"] in user_cats else 1, c["name"]))
        if query:
            sorted_cats = [c for c in sorted_cats if query in c["name"].lower()]
        total_pages = max(1, (len(sorted_cats) + self._CATS_PER_PAGE - 1) // self._CATS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        slice_ = sorted_cats[page * self._CATS_PER_PAGE:(page + 1) * self._CATS_PER_PAGE]

        rows = []
        if not query:
            all_mark = "✅" if not user_cats else "❌"
            rows.append([{"text": f"{all_mark} Все категории", "callback_data": "cat_all"}])
        for cat in slice_:
            mark = "✅" if cat["id"] in user_cats else "❌"
            rows.append([{"text": f"{mark} {cat['name'][:28]}", "callback_data": f"cat_toggle:{cat['id']}"}])
        if not sorted_cats and query:
            rows.append([{"text": "Ничего не найдено", "callback_data": "cat_page:noop"}])
        nav = []
        if page > 0:
            nav.append({"text": "← Назад", "callback_data": f"cat_page:{page - 1}"})
        nav.append({"text": f"{page + 1}/{total_pages}", "callback_data": "cat_page:noop"})
        if page < total_pages - 1:
            nav.append({"text": "Вперёд →", "callback_data": f"cat_page:{page + 1}"})
        if nav:
            rows.append(nav)
        if query:
            rows.append([
                {"text": f'🔍 «{query[:20]}»', "callback_data": "cat_page:noop"},
                {"text": "❌ Сбросить", "callback_data": "cat_search_clear"},
            ])
        else:
            rows.append([{"text": "🔍 Поиск", "callback_data": "cat_search"}])
        rows.append([{"text": "← Главное меню", "callback_data": "menu_back"}])
        return {"inline_keyboard": rows}

    async def _handle_settings_cat_search_input(self, user_id: str, text: str) -> None:
        """Применяет поисковый запрос к фильтру категорий в настройках."""
        orig_chat_id, message_id = self._settings_search_mode.pop(user_id)
        self._user_cat_query[user_id] = text.strip()[:_MAX_SEARCH_LEN]
        self._user_cat_page[user_id] = 0
        await self.edit_message_text(
            orig_chat_id, message_id,
            "📂 <b>Выберите категории</b> (пусто = все):",
            reply_markup=self._build_categories_keyboard(user_id, 0),
        )

    async def _handle_report_search_input(self, user_id: str, text: str) -> None:
        """Применяет поисковый запрос к фильтру категорий отчёта."""
        orig_chat_id, message_id = self._report_search_mode.pop(user_id)
        state = self._get_report_state(user_id)
        state["cat_query"] = text.strip()[:_MAX_SEARCH_LEN]
        self._report_cat_page[user_id] = 0
        await self.edit_message_text(
            orig_chat_id, message_id,
            self._report_categories_text(state),
            reply_markup=self._build_report_cats_keyboard(user_id),
        )

    async def _handle_report_callback(
        self,
        callback_id: str,
        user_id: str,
        chat_id: str,
        message_id: Optional[int],
        data: str,
    ) -> None:
        """Обрабатывает шаги мастера отчёта."""
        state = self._get_report_state(user_id)

        if data == "report_open":
            self._report_state[user_id] = self._new_report_state()
            self._report_cat_page[user_id] = 0
            self._report_search_mode.pop(user_id, None)
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "📊 <b>Отчеты</b>\nВыберите тип отчета:",
                    reply_markup=self._build_report_type_keyboard(),
                )
            return

        if data.startswith("report_kind:"):
            kind = data[len("report_kind:"):]
            if kind not in ("discounts", "new_products", "sold_products"):
                await self._answer_callback(callback_id, "❌ Недопустимый отчет", alert=True)
                return
            self._report_state[user_id] = self._new_report_state(kind)
            self._report_cat_page[user_id] = 0
            self._report_search_mode.pop(user_id, None)
            state = self._report_state[user_id]
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_condition_text(state),
                    reply_markup=self._build_report_step1_keyboard(state),
                )
            return

        if data.startswith("report_toggle:"):
            kind = data[len("report_toggle:"):]
            if kind not in ("new", "bu"):
                await self._answer_callback(callback_id, "❌ Ошибка", alert=True)
                return
            if kind == "new":
                state["new"] = not state["new"]
            elif kind == "bu":
                state["bu"] = not state["bu"]
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_condition_text(state),
                    reply_markup=self._build_report_step1_keyboard(state),
                )
            return

        if data == "report_next:1":
            if not state["new"] and not state["bu"]:
                await self._answer_callback(callback_id, "⚠️ Выберите хотя бы одно состояние", alert=True)
                return
            if self._is_no_discount_report(state):
                if self._is_sold_products_report(state):
                    cats = await self._db_call(self.db.get_sold_known_categories) if self.db else []
                else:
                    cats = await self._db_call(self.db.get_all_known_categories) if self.db else []
                if not cats:
                    await self._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
                    return
                await self._answer_callback(callback_id, "")
                self._report_cat_page[user_id] = 0
                if message_id:
                    await self.edit_message_text(
                        chat_id, message_id,
                        self._report_categories_text(state),
                        reply_markup=self._build_report_cats_keyboard(user_id),
                )
                return
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    f"📊 <b>{self._report_title(state)} — Шаг 2 из 4</b>\nВыберите минимальную скидку:",
                    reply_markup=self._build_report_step2_keyboard(state),
                )
            return

        if data.startswith("report_pct:"):
            try:
                pct = int(data[len("report_pct:"):])
            except ValueError:
                await self._answer_callback(callback_id, "❌ Ошибка", alert=True)
                return
            if pct not in _VALID_REPORT_PCTS:
                await self._answer_callback(callback_id, "❌ Недопустимое значение", alert=True)
                return
            state["discount"] = pct
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    f"📊 <b>{self._report_title(state)} — Шаг 2 из 4</b>\nВыберите минимальную скидку:",
                    reply_markup=self._build_report_step2_keyboard(state),
                )
            return

        if data == "report_next:2":
            cats = await self._db_call(self.db.get_all_known_categories) if self.db else []
            if not cats:
                await self._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
                return
            await self._answer_callback(callback_id, "")
            self._report_cat_page[user_id] = 0
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_categories_text(state),
                    reply_markup=self._build_report_cats_keyboard(user_id),
                )
            return

        if data == "report_cat_all":
            state["cats"] = []
            state["cat_query"] = ""
            self._report_cat_page[user_id] = 0
            await self._answer_callback(callback_id, "✅ Все категории")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_categories_text(state),
                    reply_markup=self._build_report_cats_keyboard(user_id),
                )
            return

        if data.startswith("report_cat_toggle:"):
            cat_id = data[len("report_cat_toggle:"):]
            if self.db:
                known_categories = (
                    self.db.get_sold_known_categories()
                    if self._is_sold_products_report(state)
                    else self.db.get_all_known_categories()
                )
                known_ids = {c["id"] for c in known_categories}
                if cat_id not in known_ids:
                    await self._answer_callback(callback_id, "❌ Категория не найдена", alert=True)
                    return
            cats = state.get("cats", [])
            if cat_id in cats:
                cats.remove(cat_id)
                await self._answer_callback(callback_id, "❌ Убрано")
            else:
                cats.append(cat_id)
                await self._answer_callback(callback_id, "✅ Добавлено")
            state["cats"] = cats
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_categories_text(state),
                    reply_markup=self._build_report_cats_keyboard(user_id),
                )
            return

        if data.startswith("report_cat_page:"):
            raw = data[len("report_cat_page:"):]
            if raw != "noop":
                try:
                    self._report_cat_page[user_id] = max(0, int(raw))
                except ValueError:
                    await self._answer_callback(callback_id, "❌ Ошибка", alert=True)
                    return
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_categories_text(state),
                    reply_markup=self._build_report_cats_keyboard(user_id),
                )
            return

        if data == "report_cat_search":
            await self._answer_callback(callback_id, "")
            if message_id:
                self._report_search_mode[user_id] = (chat_id, message_id)
                await self.send_message(chat_id, "🔍 Введите название категории для поиска:")
            return

        if data == "report_cat_search_clear":
            state["cat_query"] = ""
            self._report_cat_page[user_id] = 0
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_categories_text(state),
                    reply_markup=self._build_report_cats_keyboard(user_id),
                )
            return

        if data == "report_next:cats":
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_period_text(state),
                    reply_markup=self._build_report_step3_keyboard(state),
                )
            return

        if data.startswith("report_period:"):
            period = data[len("report_period:"):]
            valid_periods = {v for v, _ in self._REPORT_PERIODS}
            if period not in valid_periods:
                await self._answer_callback(callback_id, "❌ Недопустимый период", alert=True)
                return
            state["period"] = period
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_period_text(state),
                    reply_markup=self._build_report_step3_keyboard(state),
                )
            return

        if data == "report_next:3":
            conds = (["Новые"] if state["new"] else []) + (["Б/У"] if state["bu"] else [])
            period_label = dict(self._REPORT_PERIODS).get(state.get("period", "1d"), "1 день")
            cats = state.get("cats", [])
            cats_label = "все" if not cats else f"{len(cats)} шт."
            discount_line = "" if self._is_no_discount_report(state) else f"Скидка: от {state['discount']}%\n"
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    f"📊 <b>{self._report_title(state)} — Готово</b>\n\n"
                    f"Состояние: {', '.join(conds)}\n"
                    f"{discount_line}"
                    f"Категории: {cats_label}\n"
                    f"Период: {period_label}\n\n"
                    f"Нажмите <b>Получить отчет</b>:",
                    reply_markup=self._build_report_step4_keyboard(),
                )
            return

        if data == "report_back:1":
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_condition_text(state),
                    reply_markup=self._build_report_step1_keyboard(state),
                )
            return

        if data == "report_back:2":
            await self._answer_callback(callback_id, "")
            if message_id:
                if self._is_no_discount_report(state):
                    await self.edit_message_text(
                        chat_id, message_id,
                        self._report_condition_text(state),
                        reply_markup=self._build_report_step1_keyboard(state),
                    )
                else:
                    await self.edit_message_text(
                        chat_id, message_id,
                        f"📊 <b>{self._report_title(state)} — Шаг 2 из 4</b>\nВыберите минимальную скидку:",
                        reply_markup=self._build_report_step2_keyboard(state),
                    )
            return

        if data == "report_back:cats":
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_categories_text(state),
                    reply_markup=self._build_report_cats_keyboard(user_id),
                )
            return

        if data == "report_back:3":
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    self._report_period_text(state),
                    reply_markup=self._build_report_step3_keyboard(state),
                )
            return

        if data == "report_get":
            await self._answer_callback(callback_id, "")
            await self._send_report(user_id, chat_id, state)
            return

        await self._answer_callback(callback_id, "❓ Неизвестная команда", alert=True)

    async def _send_report_batches(self, chat_id: str, item_blocks: list[str]) -> bool:
        current: list[str] = []
        current_len = 0
        ok = True

        for block in item_blocks:
            separator_len = 2 if current else 0
            if current and current_len + separator_len + len(block) > _TELEGRAM_SAFE_MESSAGE_LEN:
                result = await self.send_message(chat_id, "\n\n".join(current))
                ok = ok and result == "ok"
                current = []
                current_len = 0
                await asyncio.sleep(0.5)

            current.append(block)
            current_len += (2 if current_len else 0) + len(block)

        if current:
            result = await self.send_message(chat_id, "\n\n".join(current))
            ok = ok and result == "ok"
        return ok

    async def _send_report(self, user_id: str, chat_id: str, state: dict) -> None:
        """Формирует и отправляет отчёт пользователю."""
        if not self.db:
            await self.send_message(chat_id, "❌ БД не инициализирована")
            return

        statuses: list[str] = []
        if state.get("new"):
            statuses.append("Новый")
        if state.get("bu"):
            statuses.append("Б/У")
        if not statuses:
            await self.send_message(chat_id, "❌ Не выбрано ни одно состояние товара")
            return

        discount_pct = state.get("discount", 10)
        period = state.get("period", "1d")
        period_label = dict(self._REPORT_PERIODS).get(period, "1 день")
        category_ids = state.get("cats") or None
        user_settings = await self._db_call(self.db.get_user_settings, user_id)
        user_city = user_settings["city_slug"] if user_settings else None
        is_new_products_report = self._is_new_products_report(state)
        is_sold_products_report = self._is_sold_products_report(state)
        if is_new_products_report:
            products = await self._db_call(
                self.db.get_new_report_products,
                statuses, period=period, category_ids=category_ids, city_slug=user_city,
            )
        elif is_sold_products_report:
            products = await self._db_call(
                self.db.get_sold_report_products,
                statuses, period=period, category_ids=category_ids, city_slug=user_city,
            )
        else:
            products = await self._db_call(
                self.db.get_report_products,
                statuses, discount_pct, period=period,
                category_ids=category_ids, city_slug=user_city,
            )

        cond_text = ", ".join(
            (["Новые"] if state.get("new") else []) +
            (["Б/У"] if state.get("bu") else [])
        )
        report_title = self._report_title(state)
        filter_text = f"Состояние: {cond_text} | Период: {period_label}"
        if not self._is_no_discount_report(state):
            filter_text = f"Состояние: {cond_text} | Скидка: от {discount_pct}% | Период: {period_label}"

        if not products:
            await self.send_message(
                chat_id,
                f"📊 <b>{report_title}</b>\n\n"
                f"{filter_text}\n\n"
                f"Товаров не найдено.",
                reply_markup={"inline_keyboard": [[{"text": "🏠 Главная", "callback_data": "menu_back"}]]},
            )
            return

        await self.send_message(
            chat_id,
            f"📊 <b>{report_title}</b>\n"
            f"Найдено: {len(products)} тов. | {filter_text}",
        )

        base_url = config.api_base_url.rstrip("/")

        # Дедупликация: одинаковые позиции в отчёте показываем одной строкой с xN.
        seen: dict[tuple, dict] = {}
        for p in products:
            key = (
                p.get("title"),
                p.get("current_price"),
                p.get("previous_price"),
                p.get("created_at") or p.get("sold_at"),
            )
            if key in seen:
                seen[key]["_count"] += 1
            else:
                seen[key] = dict(p, _count=1)
        deduped = list(seen.values())

        item_blocks: list[str] = []
        for p in deduped:
            raw_url = p.get("url") or ""
            url = raw_url if raw_url.startswith("http") else base_url + raw_url
            safe_url = self._escape_html_attr(url)
            raw_title = self._truncate_report_title(str(p.get("title") or "Без названия"))
            safe_title = self._escape_html_text(raw_title)
            icon = "🆕" if p.get("status") == "Новый" else "♻️"
            cnt = f" (x{p['_count']})" if p['_count'] > 1 else ""
            cur = self._format_price(p.get("current_price"))
            if is_new_products_report:
                price_text = f"{cur} ₽"
                previous_price = p.get("previous_price")
                if previous_price and p.get("current_price") is not None and previous_price > p["current_price"]:
                    prev = self._format_price(previous_price)
                    price_text += f" <s>{prev} ₽</s>"
                item_blocks.append(
                    f'• <a href="{safe_url}">{safe_title}{cnt}</a>\n'
                    f"  💰 {price_text} {icon}"
                )
            elif is_sold_products_report:
                price_text = f"{cur} ₽"
                previous_price = p.get("previous_price")
                if previous_price and p.get("current_price") is not None and previous_price > p["current_price"]:
                    prev = self._format_price(previous_price)
                    price_text += f" <s>{prev} ₽</s>"
                sold_at = str(p.get("sold_at") or "")[:10]
                sold_text = f"\n  📅 {self._escape_html_text(sold_at)}" if sold_at else ""
                item_blocks.append(
                    f'🛒 <b><a href="{safe_url}">{safe_title}{cnt}</a></b>\n'
                    f"💰 {price_text} {icon}{sold_text}"
                )
            else:
                prev = self._format_price(p.get("previous_price"))
                try:
                    discount_text = f"{float(p.get('discount_pct') or 0):.0f}%"
                except (TypeError, ValueError):
                    discount_text = "0%"
                item_blocks.append(
                    f'{icon} <b><a href="{safe_url}">{safe_title}{cnt}</a></b>\n'
                    f"💰 {cur} ₽ <s>{prev} ₽</s> — -{discount_text}"
                )

        if not await self._send_report_batches(chat_id, item_blocks):
            logger.warning("[TG BOT] Не все части отчёта удалось отправить пользователю %s", user_id)

        final_result = await self.send_message(
            chat_id,
            "✅ Отчет сформирован.",
            reply_markup={"inline_keyboard": [[{"text": "🏠 Главная", "callback_data": "menu_back"}]]},
        )
        if final_result == "fail":
            logger.warning("[TG BOT] Не удалось отправить финальное сообщение отчёта пользователю %s", user_id)

    async def _handle_settings_command(self, user_id: str, chat_id: str) -> None:
        if not self.db:
            await self.send_message(chat_id, "❌ БД не инициализирована")
            return
        self.db.upsert_user_settings(user_id)
        s = self.db.get_user_settings(user_id)
        await self.send_message(
            chat_id,
            "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
            reply_markup=self._build_settings_keyboard(s),
        )

    async def _handle_city_command(self, user_id: str, chat_id: str) -> None:
        current_slug = ""
        if self.db:
            self.db.upsert_user_settings(user_id)
            s = self.db.get_user_settings(user_id)
            current_slug = s.get("city_slug", "")
        await self.send_message(
            chat_id,
            "🏙 <b>Выберите ваш город:</b>",
            reply_markup=self._build_city_keyboard(current_slug),
        )

    async def _handle_categories_command(self, user_id: str, chat_id: str) -> None:
        if not self.db:
            await self.send_message(chat_id, "❌ БД не инициализирована")
            return
        cats = self.db.get_all_known_categories()
        if not cats:
            await self.send_message(
                chat_id,
                "📭 Категории ещё не загружены. Дождитесь первого цикла парсера."
            )
            return
        page = self._user_cat_page.get(user_id, 0)
        await self.send_message(
            chat_id,
            "📂 <b>Выберите категории</b> (пусто = все):",
            reply_markup=self._build_categories_keyboard(user_id, page),
        )

    async def _handle_status_command(self, user_id: str, chat_id: str) -> None:
        if not self.db:
            await self.send_message(chat_id, "❌ БД не инициализирована")
            return
        self.db.upsert_user_settings(user_id)
        s = self.db.get_user_settings(user_id)
        from data.cities import SLUG_TO_CITY
        city_name = SLUG_TO_CITY.get(s["city_slug"], s["city_slug"])
        cats = self.db.get_user_categories(user_id)
        cat_text = "все" if not cats else f"{len(cats)} шт."
        notif_text = "включены ✅" if s["notifications_on"] else "выключены 🔕"
        new_text = "✅" if s["notify_new"] else "❌"
        drop_text = "✅" if s["notify_price_drop"] else "❌"
        pct_text = f">{s['min_price_drop_pct']}%" if s["min_price_drop_pct"] else "любое"

        await self.send_message(
            chat_id,
            f"📋 <b>Ваши настройки</b>\n\n"
            f"🏙 Город: {city_name}\n"
            f"📂 Категории: {cat_text}\n"
            f"🔔 Уведомления: {notif_text}\n"
            f"🆕 Новые товары: {new_text}\n"
            f"🏷 Снижение цен: {drop_text} (порог: {pct_text})\n\n"
            f"<i>Парсер работает для города из .env — ваш город сохранён для будущих функций.</i>",
            reply_markup={"inline_keyboard": [[{"text": "← Главное меню", "callback_data": "menu_back"}]]},
        )

    async def _handle_user_settings_callback(
        self,
        callback_id: str,
        user_id: str,
        chat_id: str,
        message_id: Optional[int],
        data: str,
    ) -> None:
        """Обрабатывает callback-кнопки настроек пользователя."""
        # Мастер отчёта не требует БД для большинства шагов
        if data.startswith("report_"):
            await self._handle_report_callback(callback_id, user_id, chat_id, message_id, data)
            return

        if not self.db:
            await self._answer_callback(callback_id, "❌ БД недоступна", alert=True)
            return

        self.db.upsert_user_settings(user_id)

        # ─── Главное меню ────────────────────────────────────────────────────
        if data == "menu_settings_open":
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "⚙️ <b>Настройки</b>\nВыберите раздел:",
                    reply_markup=self._build_settings_submenu_keyboard(),
                )
            else:
                await self.send_message(
                    chat_id,
                    "⚙️ <b>Настройки</b>\nВыберите раздел:",
                    reply_markup=self._build_settings_submenu_keyboard(),
                )
            return

        if data == "menu_back":
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "Выберите действие:",
                    reply_markup=self._build_main_menu_keyboard(user_id),
                )
            return

        if data == "menu_settings_cmd":
            await self._answer_callback(callback_id, "")
            s = self.db.get_user_settings(user_id)
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
                    reply_markup=self._build_settings_keyboard(s),
                )
            return

        if data == "menu_city_cmd":
            await self._answer_callback(callback_id, "")
            s = self.db.get_user_settings(user_id)
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "🏙 <b>Выберите ваш город:</b>",
                    reply_markup=self._build_city_keyboard(s.get("city_slug", "")),
                )
            return

        if data == "menu_categories_cmd":
            cats = await self._db_call(self.db.get_all_known_categories)
            if not cats:
                await self._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
                return
            await self._answer_callback(callback_id, "")
            self._user_cat_page[user_id] = 0
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "📂 <b>Выберите категории</b> (пусто = все):",
                    reply_markup=self._build_categories_keyboard(user_id, 0),
                )
            return

        if data == "menu_status_cmd":
            await self._answer_callback(callback_id, "")
            s = self.db.get_user_settings(user_id)
            from data.cities import SLUG_TO_CITY
            city_name = SLUG_TO_CITY.get(s["city_slug"], s["city_slug"])
            cats = self.db.get_user_categories(user_id)
            cat_text = "все" if not cats else f"{len(cats)} шт."
            notif_text = "включены ✅" if s["notifications_on"] else "выключены 🔕"
            new_text = "✅" if s["notify_new"] else "❌"
            drop_text = "✅" if s["notify_price_drop"] else "❌"
            pct_text = f">{s['min_price_drop_pct']}%" if s["min_price_drop_pct"] else "любое"
            status_text = (
                f"📋 <b>Ваши настройки</b>\n\n"
                f"🏙 Город: {city_name}\n"
                f"📂 Категории: {cat_text}\n"
                f"🔔 Уведомления: {notif_text}\n"
                f"🆕 Новые товары: {new_text}\n"
                f"🏷 Снижение цен: {drop_text} (порог: {pct_text})\n\n"
                f"<i>Парсер работает для города из .env — ваш город сохранён для будущих функций.</i>"
            )
            back_kb = {"inline_keyboard": [[{"text": "← Главное меню", "callback_data": "menu_back"}]]}
            if message_id:
                await self.edit_message_text(chat_id, message_id, status_text, reply_markup=back_kb)
            return

        if data == "menu_admin":
            await self._answer_callback(callback_id, "")
            await self._handle_admin_command(user_id, chat_id, message_id)
            return

        if data.startswith("city:"):
            slug = data[5:]
            from data.cities import SLUG_TO_CITY
            if slug not in SLUG_TO_CITY:
                await self._answer_callback(callback_id, "❌ Неизвестный город", alert=True)
                return
            city_name = SLUG_TO_CITY[slug]
            self.db.upsert_user_settings(user_id, city_slug=slug)
            await self._answer_callback(callback_id, f"✅ Город сохранён: {city_name}")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "🏙 <b>Выберите ваш город:</b>",
                    reply_markup=self._build_city_keyboard(slug),
                )
            return

        if data == "cat_search":
            await self._answer_callback(callback_id, "")
            if message_id:
                self._settings_search_mode[user_id] = (chat_id, message_id)
                await self.send_message(chat_id, "🔍 Введите название категории для поиска:")
            return

        if data == "cat_search_clear":
            self._user_cat_query[user_id] = ""
            self._user_cat_page[user_id] = 0
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "📂 <b>Выберите категории</b> (пусто = все):",
                    reply_markup=self._build_categories_keyboard(user_id, 0),
                )
            return

        if data == "cat_all":
            self.db.set_user_categories(user_id, [])
            self._user_cat_query[user_id] = ""
            self._user_cat_page[user_id] = 0
            await self._answer_callback(callback_id, "✅ Выбраны все категории")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "📂 <b>Выберите категории</b> (пусто = все):",
                    reply_markup=self._build_categories_keyboard(user_id, 0),
                )
            return

        if data.startswith("cat_toggle:"):
            cat_id = data[11:]
            known_ids = {c["id"] for c in self.db.get_all_known_categories()}
            if cat_id not in known_ids:
                await self._answer_callback(callback_id, "❌ Категория не найдена", alert=True)
                return
            added = self.db.toggle_user_category(user_id, cat_id)
            await self._answer_callback(callback_id, "✅ Добавлено" if added else "❌ Убрано")
            if message_id:
                page = self._user_cat_page.get(user_id, 0)
                await self.edit_message_text(
                    chat_id, message_id,
                    "📂 <b>Выберите категории</b> (пусто = все):",
                    reply_markup=self._build_categories_keyboard(user_id, page),
                )
            return

        if data.startswith("cat_page:"):
            raw = data[9:]
            if raw == "noop":
                await self._answer_callback(callback_id, "")
                return
            try:
                page = max(0, int(raw))
            except ValueError:
                await self._answer_callback(callback_id, "❌ Ошибка", alert=True)
                return
            self._user_cat_page[user_id] = page
            await self._answer_callback(callback_id, "")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "📂 <b>Выберите категории</b> (пусто = все):",
                    reply_markup=self._build_categories_keyboard(user_id, page),
                )
            return

        # set_* — настройки уведомлений
        setting_map = {
            "set_new:":   ("notify_new",          0, 1,  False),
            "set_drop:":  ("notify_price_drop",    0, 1,  False),
            "set_pct:":   ("min_price_drop_pct",   0, 100, False),
            "set_notif:": ("notifications_on",     0, 1,  False),
            "set_err:":   ("notify_errors",         0, 1,  True),
            "set_pf:":     ("notify_parse_finish",  0, 1,  True),
        }
        for prefix, (field, min_val, max_val, is_admin) in setting_map.items():
            if data.startswith(prefix):
                try:
                    value = int(data[len(prefix):])
                except ValueError:
                    await self._answer_callback(callback_id, "❌ Ошибка", alert=True)
                    return
                if not (min_val <= value <= max_val):
                    await self._answer_callback(callback_id, "❌ Недопустимое значение", alert=True)
                    return
                self.db.upsert_user_settings(user_id, **{field: value})
                await self._answer_callback(callback_id, "✅ Сохранено")
                if message_id:
                    s = self.db.get_user_settings(user_id)
                    if is_admin:
                        await self.edit_message_text(
                            chat_id, message_id,
                            "🔔 <b>Уведомления админа</b>\n\nВключите или выключите уведомления:",
                            reply_markup=self._build_admin_notify_keyboard(s),
                        )
                    else:
                        await self.edit_message_text(
                            chat_id, message_id,
                            "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
                            reply_markup=self._build_settings_keyboard(s),
                        )
                return

        await self._answer_callback(callback_id, "❓ Неизвестная команда", alert=True)

    async def _handle_admin_command(
        self,
        user_id: str,
        chat_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Обработка команды /admin с меню управления."""
        # Проверка прав администратора
        if user_id != self.admin_id:
            logger.warning("[TG BOT ADMIN] Попытка доступа к админ-панели от пользователя %s", user_id)
            await self.send_message(chat_id, "❌ У вас нет доступа к админ-панели")
            return

        if not self.parser_controller:
            await self.send_message(chat_id, "❌ Контроллер парсера не инициализирован")
            return

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
                    {"text": "📊 Статус", "callback_data": "admin_status"},
                    {"text": "🔔 Уведомления", "callback_data": "admin_notify"}
                ],
                [
                    {"text": "⬅️ Назад в главное меню", "callback_data": "menu_back"}
                ]
            ]
        }

        text = (
            "🎛️ <b>Админ-панель парсера DNS</b>\n\n"
            "Выберите действие:"
        )
        logger.info("[TG BOT ADMIN] Админ-панель открыта для %s", user_id)

        if message_id:
            await self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            await self.send_message(chat_id, text, reply_markup=markup)

    async def _handle_callback_query(self, callback_query: dict) -> None:
        """Обработка нажатий inline-кнопок."""
        try:
            callback_id = callback_query.get("id", "")
            user_id = str(callback_query.get("from", {}).get("id", ""))
            chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
            message_id = callback_query.get("message", {}).get("message_id")
            data = callback_query.get("data", "")

            logger.info(
                "[TG BOT] Callback: user=%s, data=%s",
                user_id, data,
            )

            # Пользовательские настройки — не требуют прав админа
            _user_prefixes = ("city:", "cat_", "set_new:", "set_drop:", "set_pct:", "set_notif:", "set_err:", "set_pf:", "menu_", "report_")
            if any(data.startswith(p) for p in _user_prefixes):
                if user_id not in self.subscribed_users:
                    await self._answer_callback(callback_id, "❌ Сначала подпишитесь через /start", alert=True)
                    return
                await self._handle_user_settings_callback(callback_id, user_id, chat_id, message_id, data)
                return

            # Далее — только admin callbacks
            if not self.admin_id:
                logger.warning("[TG BOT ADMIN] ❌ TELEGRAM_CHAT_ADMIN не установлен в .env")
                await self._answer_callback(callback_id, "❌ Админ-панель не сконфигурирована", alert=True)
                return

            if user_id != self.admin_id:
                logger.warning("[TG BOT ADMIN] Попытка доступа от %s (админ: %s)", user_id, self.admin_id)
                await self._answer_callback(callback_id, "❌ Нет доступа", alert=True)
                return

            # Команды, не требующие parser_controller
            if data == "admin_notify":
                logger.info("[TG BOT ADMIN] Запрос меню уведомлений админом %s", user_id)
                await self._answer_callback(callback_id, "")
                s = self.db.get_user_settings(user_id) if self.db else {}
                if message_id:
                    await self.edit_message_text(
                        chat_id, message_id,
                        "🔔 <b>Уведомления админа</b>\n\nВключите или выключите уведомления:",
                        reply_markup=self._build_admin_notify_keyboard(s),
                    )
                else:
                    await self.send_message(
                        chat_id,
                        "🔔 <b>Уведомления админа</b>\n\nВключите или выключите уведомления:",
                        reply_markup=self._build_admin_notify_keyboard(s),
                    )
                return

            elif data == "admin_back":
                logger.info("[TG BOT ADMIN] Возврат в админ-панель для %s", user_id)
                await self._answer_callback(callback_id, "")
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
                            {"text": "📊 Статус", "callback_data": "admin_status"},
                            {"text": "🔔 Уведомления", "callback_data": "admin_notify"}
                        ],
                        [
                            {"text": "⬅️ Назад в главное меню", "callback_data": "menu_back"}
                        ]
                    ]
                }
                if message_id:
                    await self.edit_message_text(
                        chat_id, message_id,
                        "🎛️ <b>Админ-панель парсера DNS</b>\n\nВыберите действие:",
                        reply_markup=markup,
                    )
                else:
                    await self.send_message(
                        chat_id,
                        "🎛️ <b>Админ-панель парсера DNS</b>\n\nВыберите действие:",
                        reply_markup=markup,
                    )
                return

            if not self.parser_controller:
                logger.error("[TG BOT ADMIN] ❌ parser_controller не инициализирован")
                await self._answer_callback(callback_id, "❌ Ошибка: контроллер не готов", alert=True)
                return

            # Обработка команд
            if data == "admin_start":
                result = await self.parser_controller.start()
                logger.info("[TG BOT ADMIN] admin_start result: %s", result)
                if result:
                    await self._answer_callback(callback_id, "✅ Парсер запущен")
                else:
                    await self._answer_callback(callback_id, "⚠️ Парсер уже работает", alert=True)
                logger.info("[TG BOT ADMIN] Парсер запущен админом %s", user_id)

            elif data == "admin_stop":
                result = await self.parser_controller.stop()
                logger.info("[TG BOT ADMIN] admin_stop result: %s", result)
                if result:
                    await self._answer_callback(callback_id, "✅ Парсер остановлен")
                else:
                    await self._answer_callback(callback_id, "⚠️ Парсер уже остановлен", alert=True)
                logger.info("[TG BOT ADMIN] Парсер остановлен админом %s", user_id)

            elif data == "admin_restart":
                result = await self.parser_controller.restart()
                logger.info("[TG BOT ADMIN] admin_restart result: %s", result)
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
                logger.info("[TG BOT ADMIN] Отправка логов админу %s", user_id)
                await self._answer_callback(callback_id, "")
                await self._send_logs(chat_id)

            elif data == "admin_status":
                logger.info("[TG BOT ADMIN] Запрос статуса админом %s", user_id)
                await self._answer_callback(callback_id, "")
                status = self.parser_controller.get_status()
                await self.send_message(
                    chat_id,
                    f"<b>📊 Статус парсера:</b>\n\n{status}"
                )
                logger.info("[TG BOT ADMIN] Статус отправлен админу %s", user_id)

            else:
                logger.error("[TG BOT ADMIN] ❌ Неизвестная команда callback: %s", data)
                await self._answer_callback(callback_id, "❌ Неизвестная команда", alert=True)

        except Exception as exc:
            logger.error("[TG BOT ADMIN] Ошибка при обработке callback: %s", exc, exc_info=True)

    async def _handle_interval_input(self, user_id: str, chat_id: str, text: str) -> None:
        """Обработка ввода нового интервала."""
        self._waiting_for_interval.discard(user_id)

        try:
            interval = int(text.strip())
            if interval < 60 or interval > 86400:
                await self.send_message(
                    chat_id,
                    "❌ Интервал должен быть от 60 до 86400 секунд (24 часа)"
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

                logs_text = _html.escape(logs_text)
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
            status, data = await self._telegram_request(
                "answerCallbackQuery",
                json=payload,
                timeout=10,
            )
            if status == 200 and data.get("ok", True):
                return True
            logger.debug("[TG BOT] answerCallbackQuery status=%s description=%s", status, data.get("description", ""))
            return False
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
                    logger.debug("[TG BOT POLLING] Отправляю getUpdates с offset=%d", offset)
                    async with self._get_session().get(
                        f"{self.api_url}/getUpdates",
                        params={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
                        timeout=aiohttp.ClientTimeout(total=35),
                    ) as resp:
                        logger.debug("[TG BOT POLLING] Получен ответ статус %d", resp.status)
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
                            logger.debug("[TG BOT] Raw update keys: %s", [list(u.keys()) for u in updates])

                            for update in updates:
                                update_type = "unknown"
                                if "message" in update:
                                    update_type = "message"
                                elif "callback_query" in update:
                                    update_type = "callback"
                                logger.info("[TG BOT] Обновление тип: %s", update_type)
                                try:
                                    await self.handle_update(update)
                                except Exception as exc:
                                    logger.error("[TG BOT] Ошибка при обработке обновления: %s", exc, exc_info=True)

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
