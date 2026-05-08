"""
Обработчик настроек пользователя — извлечён из telegram_bot.py.
Управляет командами /settings, /city, /categories, /status и callback-кнопками настроек.
"""
import html as _html
from typing import TYPE_CHECKING, Optional

from data.cities import SLUG_TO_CITY

from .. import keyboards as kb
from .. import utils
from ..state import UserState

if TYPE_CHECKING:
    from ..core import TelegramBot
    from .reports import ReportWizard


class SettingsHandler:
    """Обработчик команд настроек и пользовательских callback-кнопок."""

    def __init__(self, bot: "TelegramBot", report_wizard: "ReportWizard") -> None:
        self._bot = bot
        self._rw = report_wizard
        self._us: UserState = bot._user_state

    def _get_user_city_slug(self, user_id: str) -> str:
        if not self._bot.db:
            return ""
        s = self._bot.db.get_user_settings(user_id) or {}
        return s.get("city_slug", "")

    # ── Public router ─────────────────────────────────────────────────────────

    async def handle_command(self, user_id: str, chat_id: str, command: str) -> None:
        handlers = {
            "/settings":    self._handle_settings_command,
            "/city":        self._handle_city_command,
            "/categories":  self._handle_categories_command,
            "/status":      self._handle_status_command,
        }
        handler = handlers.get(command)
        if handler:
            await handler(user_id, chat_id)

    async def handle_callback(
        self,
        callback_id: str,
        user_id: str,
        chat_id: str,
        message_id: Optional[int],
        data: str,
    ) -> None:
        """Диспетчер callback-кнопок настроек (не требующих прав админа)."""
        # report_* — отдаём мастеру отчётов
        if data.startswith("report_"):
            await self._rw.handle(callback_id, user_id, chat_id, message_id, data)
            return

        # branch handlers
        # порядок важен — более длинные/точные префиксы раньше коротких
        branches = [
            ("menu_settings_open",   self._on_menu_settings_open),
            ("menu_back",            self._on_menu_back),
            ("menu_settings_cmd",    self._on_menu_settings_cmd),
            ("menu_city_cmd",        self._on_menu_city_cmd),
            ("menu_categories_cmd",  self._on_menu_categories_cmd),
            ("menu_status_cmd",      self._on_menu_status_cmd),
            ("menu_admin",          self._on_menu_admin),
            ("cat_search_clear",     self._on_cat_search_clear),
            ("cat_search",          self._on_cat_search),
            ("cat_all",             self._on_cat_all),
            ("cat_toggle:",         self._on_cat_toggle),
            ("cat_page:",           self._on_cat_page),
        ]
        for key, handler in branches:
            if data == key or data.startswith(key):
                await handler(callback_id, user_id, chat_id, message_id, data)
                return

        # set_* — setting map
        if await self._handle_set(callback_id, user_id, chat_id, message_id, data):
            return

        # city: prefix
        if data.startswith("city:"):
            await self._on_city(callback_id, user_id, chat_id, message_id, data)
            return

        await self._bot._answer_callback(callback_id, "❓ Неизвестная команда", alert=True)

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _handle_settings_command(self, user_id: str, chat_id: str) -> None:
        if not self._bot.db:
            await self._bot.send_message(chat_id, "❌ БД не инициализирована")
            return
        self._bot.db.upsert_user_settings(user_id)
        s = self._bot.db.get_user_settings(user_id)
        await self._bot.send_message(
            chat_id,
            "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
            reply_markup=kb._build_settings_keyboard(s),
        )

    async def _handle_city_command(self, user_id: str, chat_id: str) -> None:
        current_slug = ""
        if self._bot.db:
            self._bot.db.upsert_user_settings(user_id)
            s = self._bot.db.get_user_settings(user_id)
            current_slug = s.get("city_slug", "")
        await self._bot.send_message(
            chat_id,
            "🏙 <b>Выберите ваш город:</b>",
            reply_markup=kb._build_city_keyboard(current_slug),
        )

    async def _handle_categories_command(self, user_id: str, chat_id: str) -> None:
        if not self._bot.db:
            await self._bot.send_message(chat_id, "❌ БД не инициализирована")
            return
        city_slug = self._get_user_city_slug(user_id)
        cats = self._bot.db.get_all_known_categories(city_slug=city_slug)
        if not cats:
            await self._bot.send_message(
                chat_id,
                "📭 Категории ещё не загружены. Дождитесь первого цикла парсера."
            )
            return
        page = self._us.user_cat_page.get(user_id, 0)
        user_cats = set(self._bot.db.get_user_categories(user_id, city_slug))
        await self._bot.send_message(
            chat_id,
            "📂 <b>Выберите категории</b> (пусто = все):",
            reply_markup=kb._build_categories_keyboard(
                self._bot.db, user_id, page,
                self._us.user_cat_query.get(user_id, ""),
                user_cats,
                cats,
            ),
        )

    async def _handle_status_command(self, user_id: str, chat_id: str) -> None:
        if not self._bot.db:
            await self._bot.send_message(chat_id, "❌ БД не инициализирована")
            return
        self._bot.db.upsert_user_settings(user_id)
        s = self._bot.db.get_user_settings(user_id)
        city_slug = s.get("city_slug", "")
        cats = self._bot.db.get_user_categories(user_id, city_slug)
        text = utils.format_user_status_text(s, cats, SLUG_TO_CITY)
        await self._bot.send_message(
            chat_id,
            text,
            reply_markup={"inline_keyboard": [[{"text": "← Главное меню", "callback_data": "menu_back"}]]},
        )

    # ── Menu callback branches ─────────────────────────────────────────────────

    async def _on_menu_settings_open(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "⚙️ <b>Настройки</b>\nВыберите раздел:",
                reply_markup=kb._build_settings_submenu_keyboard(),
            )
        else:
            await self._bot.send_message(
                chat_id,
                "⚙️ <b>Настройки</b>\nВыберите раздел:",
                reply_markup=kb._build_settings_submenu_keyboard(),
            )

    async def _on_menu_back(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "Выберите действие:",
                reply_markup=kb._build_main_menu_keyboard(user_id, self._bot.admin_id),
            )

    async def _on_menu_settings_cmd(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        s = self._bot.db.get_user_settings(user_id) if self._bot.db else {}
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
                reply_markup=kb._build_settings_keyboard(s),
            )

    async def _on_menu_city_cmd(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        s = self._bot.db.get_user_settings(user_id) if self._bot.db else {}
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "🏙 <b>Выберите ваш город:</b>",
                reply_markup=kb._build_city_keyboard(s.get("city_slug", "")),
            )

    async def _on_menu_categories_cmd(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        city_slug = self._get_user_city_slug(user_id)
        cats = await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug) if self._bot.db else []
        if not cats:
            await self._bot._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
            return
        await self._bot._answer_callback(callback_id, "")
        self._us.user_cat_page[user_id] = 0
        if message_id:
            user_cats = set(self._bot.db.get_user_categories(user_id, city_slug)) if self._bot.db else set()
            await self._bot.edit_message_text(
                chat_id, message_id,
                "📂 <b>Выберите категории</b> (пусто = все):",
                reply_markup=kb._build_categories_keyboard(
                    self._bot.db, user_id, 0,
                    self._us.user_cat_query.get(user_id, ""),
                    user_cats,
                    cats,
                ),
            )

    async def _on_menu_status_cmd(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        s = self._bot.db.get_user_settings(user_id) if self._bot.db else {}
        city_slug = s.get("city_slug", "")
        cats = self._bot.db.get_user_categories(user_id, city_slug) if self._bot.db else []
        text = utils.format_user_status_text(s, cats, SLUG_TO_CITY)
        back_kb = {"inline_keyboard": [[{"text": "← Главное меню", "callback_data": "menu_back"}]]}
        if message_id:
            await self._bot.edit_message_text(chat_id, message_id, text, reply_markup=back_kb)

    async def _on_menu_admin(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        await self._bot._handle_admin_command(user_id, chat_id, message_id)

    # ── City ─────────────────────────────────────────────────────────────────

    async def _on_city(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        slug = data[5:]
        if slug not in SLUG_TO_CITY:
            await self._bot._answer_callback(callback_id, "❌ Неизвестный город", alert=True)
            return
        city_name = SLUG_TO_CITY[slug]
        self._bot.db.upsert_user_settings(user_id, city_slug=slug) if self._bot.db else None
        await self._bot._answer_callback(callback_id, f"✅ Город сохранён: {city_name}")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "🏙 <b>Выберите ваш город:</b>",
                reply_markup=kb._build_city_keyboard(slug),
            )

    # ── Category picker ──────────────────────────────────────────────────────

    async def _on_cat_search(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            self._us.settings_search_mode[user_id] = (chat_id, message_id)
            await self._bot.send_message(chat_id, "🔍 Введите название категории для поиска:")

    async def _on_cat_search_clear(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        self._us.user_cat_query[user_id] = ""
        self._us.user_cat_page[user_id] = 0
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            city_slug = self._get_user_city_slug(user_id)
            cats = await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug) if self._bot.db else []
            user_cats = set(self._bot.db.get_user_categories(user_id, city_slug)) if self._bot.db else set()
            await self._bot.edit_message_text(
                chat_id, message_id,
                "📂 <b>Выберите категории</b> (пусто = все):",
                reply_markup=kb._build_categories_keyboard(
                    self._bot.db, user_id, 0,
                    "",
                    user_cats,
                    cats,
                ),
            )

    async def _on_cat_all(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        city_slug = self._get_user_city_slug(user_id)
        self._bot.db.set_user_categories(user_id, [], city_slug) if self._bot.db else None
        self._us.user_cat_query[user_id] = ""
        self._us.user_cat_page[user_id] = 0
        await self._bot._answer_callback(callback_id, "✅ Выбраны все категории")
        if message_id:
            cats = await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug) if self._bot.db else []
            await self._bot.edit_message_text(
                chat_id, message_id,
                "📂 <b>Выберите категории</b> (пусто = все):",
                reply_markup=kb._build_categories_keyboard(
                    self._bot.db, user_id, 0,
                    "",
                    set(),  # all selected → empty set
                    cats,
                ),
            )

    async def _on_cat_toggle(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        cat_id = data[11:]
        if self._bot.db:
            city_slug = self._get_user_city_slug(user_id)
            known_ids = {c["id"] for c in self._bot.db.get_all_known_categories(city_slug=city_slug)}
            if cat_id not in known_ids:
                await self._bot._answer_callback(callback_id, "❌ Категория не найдена", alert=True)
                return
            added = self._bot.db.toggle_user_category(user_id, cat_id, city_slug)
        else:
            added = False
        await self._bot._answer_callback(callback_id, "✅ Добавлено" if added else "❌ Убрано")
        if message_id:
            page = self._us.user_cat_page.get(user_id, 0)
            city_slug = self._get_user_city_slug(user_id)
            cats = await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug) if self._bot.db else []
            user_cats = set(self._bot.db.get_user_categories(user_id, city_slug)) if self._bot.db else set()
            await self._bot.edit_message_text(
                chat_id, message_id,
                "📂 <b>Выберите категории</b> (пусто = все):",
                reply_markup=kb._build_categories_keyboard(
                    self._bot.db, user_id, page,
                    self._us.user_cat_query.get(user_id, ""),
                    user_cats,
                    cats,
                ),
            )

    async def _on_cat_page(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        raw = data[9:]
        if raw == "noop":
            await self._bot._answer_callback(callback_id, "")
            return
        try:
            page = max(0, int(raw))
        except ValueError:
            await self._bot._answer_callback(callback_id, "❌ Ошибка", alert=True)
            return
        self._us.user_cat_page[user_id] = page
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            city_slug = self._get_user_city_slug(user_id)
            cats = await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug) if self._bot.db else []
            user_cats = set(self._bot.db.get_user_categories(user_id, city_slug)) if self._bot.db else set()
            await self._bot.edit_message_text(
                chat_id, message_id,
                "📂 <b>Выберите категории</b> (пусто = все):",
                reply_markup=kb._build_categories_keyboard(
                    self._bot.db, user_id, page,
                    self._us.user_cat_query.get(user_id, ""),
                    user_cats,
                    cats,
                ),
            )

    # ── set_* settings map ───────────────────────────────────────────────────

    async def _handle_set(
        self,
        callback_id: str,
        user_id: str,
        chat_id: str,
        message_id: Optional[int],
        data: str,
    ) -> bool:
        """Обрабатывает set_*-callbacks. Возвращает True если обработал."""
        setting_map = {
            "set_new:":   ("notify_new",          0, 1,  False),
            "set_drop:":  ("notify_price_drop",    0, 1,  False),
            "set_pct:":   ("min_price_drop_pct",   0, 100, False),
            "set_notif:": ("notifications_on",     0, 1,  False),
            "set_err:":   ("notify_errors",         0, 1,  True),
            "set_pf:":    ("notify_parse_finish",  0, 1,  True),
        }
        for prefix, (field, min_val, max_val, is_admin) in setting_map.items():
            if data.startswith(prefix):
                try:
                    value = int(data[len(prefix):])
                except ValueError:
                    await self._bot._answer_callback(callback_id, "❌ Ошибка", alert=True)
                    return True
                if not (min_val <= value <= max_val):
                    await self._bot._answer_callback(callback_id, "❌ Недопустимое значение", alert=True)
                    return True
                if self._bot.db:
                    self._bot.db.upsert_user_settings(user_id, **{field: value})
                await self._bot._answer_callback(callback_id, "✅ Сохранено")
                if message_id and self._bot.db:
                    s = self._bot.db.get_user_settings(user_id)
                    if is_admin:
                        await self._bot.edit_message_text(
                            chat_id, message_id,
                            "🔔 <b>Уведомления админа</b>\n\nВключите или выключите уведомления:",
                            reply_markup=kb._build_admin_notify_keyboard(s),
                        )
                    else:
                        await self._bot.edit_message_text(
                            chat_id, message_id,
                            "⚙️ <b>Настройки уведомлений</b>\nВыберите что хотите изменить:",
                            reply_markup=kb._build_settings_keyboard(s),
                        )
                return True
        return False

    # ── Search input handler (called from core.handle_update) ─────────────────

    async def handle_search_input(self, user_id: str, text: str) -> None:
        """Обрабатывает свободный ввод в режиме поиска категорий в настройках."""
        orig_chat_id, orig_message_id = self._us.settings_search_mode.pop(user_id)
        self._us.user_cat_query[user_id] = text.strip()[:utils._MAX_SEARCH_LEN]
        self._us.user_cat_page[user_id] = 0
        city_slug = self._get_user_city_slug(user_id)
        cats = await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug) if self._bot.db else []
        user_cats = set(self._bot.db.get_user_categories(user_id, city_slug)) if self._bot.db else set()
        await self._bot.edit_message_text(
            orig_chat_id, orig_message_id,
            "📂 <b>Выберите категории</b> (пусто = все):",
            reply_markup=kb._build_categories_keyboard(
                self._bot.db, user_id, 0,
                self._us.user_cat_query.get(user_id, ""),
                user_cats,
                cats,
            ),
        )
