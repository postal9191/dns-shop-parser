"""
Telegram бот для управления подписками на уведомления и админ-панель.
"""

import asyncio
import aiohttp
from typing import Optional, Set

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
        self._broadcast_lock = asyncio.Lock()
        self._subscriber_lock = asyncio.Lock()
        self._user_cat_page: dict[str, int] = {}  # user_id → текущая страница /categories

        if self.db and self.enabled:
            self.subscribed_users = self._load_subscribers()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
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
                async with self._get_session().post(
                    f"{self.api_url}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {}

                    if resp.status == 200 and data.get("ok"):
                        return "ok"
                    if resp.status == 429:
                        retry_after = data.get("parameters", {}).get("retry_after", 5)
                        logger.warning("[TG BOT] Rate limit, жду %d сек (попытка %d/3)", retry_after, attempt + 1)
                        await asyncio.sleep(retry_after + 1)
                        continue
                    if resp.status == 403:
                        logger.info("[TG BOT] Пользователь %s заблокировал бота (403): %s",
                                    chat_id, data.get("description"))
                        return "blocked"
                    desc = data.get("description", "")
                    if resp.status == 400 and ("chat not found" in desc.lower() or "user is deactivated" in desc.lower()):
                        logger.info("[TG BOT] Чат %s недоступен (%s): %s", chat_id, resp.status, desc)
                        return "blocked"
                    logger.warning("[TG BOT] Ответ %d при отправке в %s (попытка %d/3): %s",
                                   resp.status, chat_id, attempt + 1, desc)
                    if resp.status >= 500:
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
            [{"text": "⚙️ Настройки", "callback_data": "menu_settings_open"}],
        ]
        if user_id == self.admin_id:
            rows.append([{"text": "🎛️ Админ-панель", "callback_data": "menu_admin"}])
        return {"inline_keyboard": rows}

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
            async with self._get_session().post(
                f"{self.api_url}/editMessageText",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
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

    def _build_categories_keyboard(self, user_id: str, page: int) -> dict:
        """Строит inline-клавиатуру выбора категорий с пагинацией."""
        if not self.db:
            return {"inline_keyboard": []}
        all_cats = self.db.get_all_known_categories()
        user_cats = set(self.db.get_user_categories(user_id))
        # Выбранные категории поднимаем наверх
        sorted_cats = sorted(all_cats, key=lambda c: (0 if c["id"] in user_cats else 1, c["name"]))
        total_pages = max(1, (len(sorted_cats) + self._CATS_PER_PAGE - 1) // self._CATS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        slice_ = sorted_cats[page * self._CATS_PER_PAGE:(page + 1) * self._CATS_PER_PAGE]

        rows = []
        # «Все категории» — сброс фильтра
        all_mark = "✅" if not user_cats else "❌"
        rows.append([{"text": f"{all_mark} Все категории", "callback_data": "cat_all"}])
        for cat in slice_:
            mark = "✅" if cat["id"] in user_cats else "❌"
            name = cat["name"][:28]
            rows.append([{"text": f"{mark} {name}", "callback_data": f"cat_toggle:{cat['id']}"}])
        # Навигация
        nav = []
        if page > 0:
            nav.append({"text": "← Назад", "callback_data": f"cat_page:{page - 1}"})
        nav.append({"text": f"{page + 1}/{total_pages}", "callback_data": "cat_page:noop"})
        if page < total_pages - 1:
            nav.append({"text": "Вперёд →", "callback_data": f"cat_page:{page + 1}"})
        if nav:
            rows.append(nav)
        rows.append([{"text": "← Главное меню", "callback_data": "menu_back"}])
        return {"inline_keyboard": rows}

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
            await self._answer_callback(callback_id, "")
            cats = self.db.get_all_known_categories()
            if not cats:
                await self._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
                return
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
            await self._handle_admin_command(user_id, chat_id)
            return

        if data.startswith("city:"):
            slug = data[5:]
            from data.cities import SLUG_TO_CITY
            city_name = SLUG_TO_CITY.get(slug, slug)
            self.db.upsert_user_settings(user_id, city_slug=slug)
            await self._answer_callback(callback_id, f"✅ Город сохранён: {city_name}")
            if message_id:
                await self.edit_message_text(
                    chat_id, message_id,
                    "🏙 <b>Выберите ваш город:</b>",
                    reply_markup=self._build_city_keyboard(slug),
                )
            return

        if data == "cat_all":
            self.db.set_user_categories(user_id, [])
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
            page = int(raw)
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
            "set_new:": "notify_new",
            "set_drop:": "notify_price_drop",
            "set_pct:": "min_price_drop_pct",
            "set_notif:": "notifications_on",
        }
        for prefix, field in setting_map.items():
            if data.startswith(prefix):
                value = int(data[len(prefix):])
                self.db.upsert_user_settings(user_id, **{field: value})
                await self._answer_callback(callback_id, "✅ Сохранено")
                if message_id:
                    s = self.db.get_user_settings(user_id)
                    await self.edit_message_text(
                        chat_id, message_id,
                        "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
                        reply_markup=self._build_settings_keyboard(s),
                    )
                return

        await self._answer_callback(callback_id, "❓ Неизвестная команда", alert=True)

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
            message_id = callback_query.get("message", {}).get("message_id")
            data = callback_query.get("data", "")

            logger.info(
                "[TG BOT] Callback: user=%s, data=%s",
                user_id, data,
            )

            # Пользовательские настройки — не требуют прав админа
            _user_prefixes = ("city:", "cat_", "set_new:", "set_drop:", "set_pct:", "set_notif:", "menu_")
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
