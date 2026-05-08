"""
Обработчик мастера отчётов — извлечён из telegram_bot.py.
Управляет 4-шаговым wizard: тип → состояние → скидка → категории → период → генерация.
"""
import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from data.cities import SLUG_TO_CITY

from .. import keyboards as kb
from .. import utils
from ..state import ReportMachine, ReportState, _REPORT_PERIODS, UserState

if TYPE_CHECKING:
    from ..core import TelegramBot


class ReportWizard:
    """Мастер формирования отчётов — ReportWizard."""

    def __init__(self, bot: "TelegramBot") -> None:
        self._bot = bot
        self._rm: ReportMachine = ReportMachine(bot._user_state)
        # shortcuts to bot state for convenience
        self._us: UserState = bot._user_state

    async def _get_user_city_slug(self, user_id: str) -> str:
        if not self._bot.db:
            return ""
        settings = await self._bot._db_call(self._bot.db.get_user_settings, user_id)
        return (settings or {}).get("city_slug", "")

    async def _load_report_categories(self, user_id: str, state: dict) -> list[dict]:
        if not self._bot.db:
            return []
        city_slug = await self._get_user_city_slug(user_id)
        if self._rm.is_sold_products_report(state):
            return await self._bot._db_call(self._bot.db.get_sold_known_categories, city_slug=city_slug)
        return await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=city_slug)

    # ── Public router ─────────────────────────────────────────────────────────

    async def handle(
        self,
        callback_id: str,
        user_id: str,
        chat_id: str,
        message_id: Optional[int],
        data: str,
    ) -> None:
        """Единственная точка входа — диспетчер всех report_* callbacks."""
        # NOTE: порядок важен — более длинные/точные префиксы должны идти раньше
        # коротких (report_cat_search_clear до report_cat_search)
        handlers = [
            ("report_open",             self._on_report_open),
            ("report_kind:",            self._on_report_kind),
            ("report_toggle:",          self._on_report_toggle),
            ("report_next:1",           self._on_report_next_1),
            ("report_pct:",             self._on_report_pct),
            ("report_next:2",           self._on_report_next_2),
            ("report_cat_all",          self._on_report_cat_all),
            ("report_cat_toggle:",      self._on_report_cat_toggle),
            ("report_cat_page:",        self._on_report_cat_page),
            ("report_cat_search_clear", self._on_report_cat_search_clear),
            ("report_cat_search",       self._on_report_cat_search),
            ("report_next:cats",        self._on_report_next_cats),
            ("report_period:",          self._on_report_period),
            ("report_next:3",           self._on_report_next_3),
            ("report_back:1",           self._on_report_back_1),
            ("report_back:2",           self._on_report_back_2),
            ("report_back:cats",        self._on_report_back_cats),
            ("report_back:3",           self._on_report_back_3),
            ("report_get",              self._on_report_get),
        ]

        for prefix, handler in handlers:
            if data == prefix or data.startswith(prefix):
                await handler(callback_id, user_id, chat_id, message_id, data)
                return

        await self._bot._answer_callback(callback_id, "❓ Неизвестная команда", alert=True)

    # ── Step 0: type selection ─────────────────────────────────────────────────

    async def _on_report_open(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        self._us.report_state[user_id] = self._rm.new_state()
        self._us.report_cat_page[user_id] = 0
        self._us.report_search_mode.pop(user_id, None)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "📊 <b>Отчеты</b>\nВыберите тип отчета:",
                reply_markup=kb._build_report_type_keyboard(),
            )

    # ── Step 1: kind → condition ───────────────────────────────────────────────

    async def _on_report_kind(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        kind = data[len("report_kind:"):]
        if kind not in ("discounts", "new_products", "sold_products"):
            await self._bot._answer_callback(callback_id, "❌ Недопустимый отчет", alert=True)
            return
        self._us.report_state[user_id] = self._rm.new_state(kind)
        self._us.report_cat_page[user_id] = 0
        self._us.report_search_mode.pop(user_id, None)
        state = self._us.report_state[user_id]
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.condition_text(state),
                reply_markup=kb._build_report_step1_keyboard(state),
            )

    async def _on_report_toggle(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        kind = data[len("report_toggle:"):]
        if kind not in ("new", "bu"):
            await self._bot._answer_callback(callback_id, "❌ Ошибка", alert=True)
            return
        state = self._rm.get_state(user_id)
        if kind == "new":
            state["new"] = not state["new"]
        elif kind == "bu":
            state["bu"] = not state["bu"]
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.condition_text(state),
                reply_markup=kb._build_report_step1_keyboard(state),
            )

    # ── Advance from step 1 (validate) ────────────────────────────────────────

    async def _on_report_next_1(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        if not state["new"] and not state["bu"]:
            await self._bot._answer_callback(callback_id, "⚠️ Выберите хотя бы одно состояние", alert=True)
            return
        if self._rm.is_no_discount_report(state):
            # Skip discount step for new/sold reports
            cats = await self._load_report_categories(user_id, state)
            if not cats:
                await self._bot._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
                return
            await self._bot._answer_callback(callback_id, "")
            self._us.report_cat_page[user_id] = 0
            if message_id:
                await self._bot.edit_message_text(
                    chat_id, message_id,
                    self._rm.categories_text(state),
                    reply_markup=kb._build_report_cats_keyboard(
                        self._bot.db, user_id,
                        self._us.report_cat_page.get(user_id, 0),
                        state,
                        cats,
                    ),
                )
        else:
            # Discounts: go to step 2
            await self._bot._answer_callback(callback_id, "")
            if message_id:
                await self._bot.edit_message_text(
                    chat_id, message_id,
                    f"📊 <b>{self._rm.report_title(state)} — Шаг 2 из 4</b>\nВыберите минимальную скидку:",
                    reply_markup=kb._build_report_step2_keyboard(state),
                )

    # ── Step 2: discount % ────────────────────────────────────────────────────

    async def _on_report_pct(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        try:
            pct = int(data[len("report_pct:"):])
        except ValueError:
            await self._bot._answer_callback(callback_id, "❌ Ошибка", alert=True)
            return
        if pct not in utils._VALID_REPORT_PCTS:
            await self._bot._answer_callback(callback_id, "❌ Недопустимое значение", alert=True)
            return
        state = self._rm.get_state(user_id)
        state["discount"] = pct
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                f"📊 <b>{self._rm.report_title(state)} — Шаг 2 из 4</b>\nВыберите минимальную скидку:",
                reply_markup=kb._build_report_step2_keyboard(state),
            )

    async def _on_report_next_2(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        cats = await self._load_report_categories(user_id, self._rm.get_state(user_id))
        if not cats:
            await self._bot._answer_callback(callback_id, "📭 Категории ещё не загружены", alert=True)
            return
        await self._bot._answer_callback(callback_id, "")
        self._us.report_cat_page[user_id] = 0
        state = self._rm.get_state(user_id)
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.categories_text(state),
                reply_markup=kb._build_report_cats_keyboard(
                    self._bot.db, user_id,
                    self._us.report_cat_page.get(user_id, 0),
                    state,
                    cats,
                ),
            )

    # ── Categories: all / toggle / page / search ──────────────────────────────

    async def _on_report_cat_all(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        state["cats"] = []
        state["cat_query"] = ""
        self._us.report_cat_page[user_id] = 0
        await self._bot._answer_callback(callback_id, "✅ Все категории")
        cats = await self._load_report_categories(user_id, state)
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.categories_text(state),
                reply_markup=kb._build_report_cats_keyboard(
                    self._bot.db, user_id,
                    self._us.report_cat_page.get(user_id, 0),
                    state,
                    cats,
                ),
            )

    async def _on_report_cat_toggle(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        cat_id = data[len("report_cat_toggle:"):]
        state = self._rm.get_state(user_id)
        cats_list: list = state["cats"]
        if cat_id in cats_list:
            cats_list.remove(cat_id)
        else:
            cats_list.append(cat_id)
        state["cats"] = cats_list
        cats = await self._load_report_categories(user_id, state)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.categories_text(state),
                reply_markup=kb._build_report_cats_keyboard(
                    self._bot.db, user_id,
                    self._us.report_cat_page.get(user_id, 0),
                    state,
                    cats,
                ),
            )

    async def _on_report_cat_page(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        raw = data[len("report_cat_page:"):]
        if raw == "noop":
            await self._bot._answer_callback(callback_id, "")
            return
        try:
            page = max(0, int(raw))
        except ValueError:
            await self._bot._answer_callback(callback_id, "❌ Ошибка", alert=True)
            return
        self._us.report_cat_page[user_id] = page
        state = self._rm.get_state(user_id)
        cats = await self._load_report_categories(user_id, state)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.categories_text(state),
                reply_markup=kb._build_report_cats_keyboard(
                    self._bot.db, user_id, page, state, cats,
                ),
            )

    async def _on_report_cat_search(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            self._us.report_search_mode[user_id] = (chat_id, message_id)
            await self._bot.send_message(chat_id, "🔍 Введите название категории для поиска:")

    async def _on_report_cat_search_clear(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        state["cat_query"] = ""
        self._us.report_cat_page[user_id] = 0
        self._us.report_search_mode.pop(user_id, None)
        cats = await self._load_report_categories(user_id, state)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.categories_text(state),
                reply_markup=kb._build_report_cats_keyboard(
                    self._bot.db, user_id,
                    self._us.report_cat_page.get(user_id, 0),
                    state,
                    cats,
                ),
            )

    async def _on_report_next_cats(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        state = self._rm.get_state(user_id)
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.period_text(state),
                reply_markup=kb._build_report_step3_keyboard(state),
            )

    # ── Step 3: period ────────────────────────────────────────────────────────

    async def _on_report_period(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        period = data[len("report_period:"):]
        state = self._rm.get_state(user_id)
        state["period"] = period
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.period_text(state),
                reply_markup=kb._build_report_step3_keyboard(state),
            )

    async def _on_report_next_3(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        cat_count = len(state.get("cats", []))
        cat_label = "все категории" if cat_count == 0 else f"{cat_count} шт."
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                f"📊 <b>Отчет готов к формированию</b>\n\n"
                f"Категории: {cat_label}\n\n"
                "Нажмите «Получить отчёт» для генерации.",
                reply_markup=kb._build_report_step4_keyboard(),
            )

    # ── Back navigation ──────────────────────────────────────────────────────

    async def _on_report_back_1(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.condition_text(state),
                reply_markup=kb._build_report_step1_keyboard(state),
            )

    async def _on_report_back_2(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                f"📊 <b>{self._rm.report_title(state)} — Шаг 2 из 4</b>\nВыберите минимальную скидку:",
                reply_markup=kb._build_report_step2_keyboard(state),
            )

    async def _on_report_back_cats(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        await self._bot._answer_callback(callback_id, "")
        cats = await self._load_report_categories(user_id, state)
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.categories_text(state),
                reply_markup=kb._build_report_cats_keyboard(
                    self._bot.db, user_id,
                    self._us.report_cat_page.get(user_id, 0),
                    state,
                    cats,
                ),
            )

    async def _on_report_back_3(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                self._rm.period_text(state),
                reply_markup=kb._build_report_step3_keyboard(state),
            )

    # ── Generate report ───────────────────────────────────────────────────────

    async def _on_report_get(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        state = self._rm.get_state(user_id)
        await self._bot._answer_callback(callback_id, "")
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id,
                "⏳ Формирую отчёт…",
            )
        await self._send_report(user_id, chat_id, state)

    # ── Search input handler (called from core.handle_update) ─────────────────

    async def handle_search_input(self, user_id: str, text: str) -> None:
        """Обрабатывает свободный ввод в режиме поиска категорий в отчёте."""
        orig_chat_id, orig_message_id = self._us.report_search_mode.pop(user_id)
        state = self._rm.get_state(user_id)
        state["cat_query"] = text.strip()[:utils._MAX_SEARCH_LEN]
        self._us.report_cat_page[user_id] = 0
        cats = await self._load_report_categories(user_id, state)
        await self._bot.edit_message_text(
            orig_chat_id, orig_message_id,
            self._rm.categories_text(state),
            reply_markup=kb._build_report_cats_keyboard(
                self._bot.db, user_id,
                self._us.report_cat_page.get(user_id, 0),
                state,
                cats,
            ),
        )

    # ── Report generation ─────────────────────────────────────────────────────

    async def _send_report_batches(self, chat_id: str, item_blocks: list[str]) -> bool:
        current: list[str] = []
        current_len = 0
        ok = True
        for block in item_blocks:
            sep_len = 2 if current else 0
            if current and current_len + sep_len + len(block) > utils._TELEGRAM_SAFE_MESSAGE_LEN:
                result = await self._bot.send_message(chat_id, "\n\n".join(current))
                ok = ok and result == "ok"
                current = []
                current_len = 0
                await asyncio.sleep(0.5)
            current.append(block)
            current_len += (2 if current_len else 0) + len(block)
        if current:
            result = await self._bot.send_message(chat_id, "\n\n".join(current))
            ok = ok and result == "ok"
        return ok

    async def _send_report(self, user_id: str, chat_id: str, state: ReportState) -> None:
        if not self._bot.db:
            await self._bot.send_message(chat_id, "\u274c \u0411\u0414 \u043d\u0435 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d\u0430")
            return

        statuses: list[str] = []
        if state.get("new"):
            statuses.append("\u041d\u043e\u0432\u044b\u0439")
        if state.get("bu"):
            statuses.append("\u0411/\u0423")
        if not statuses:
            await self._bot.send_message(chat_id, "\u274c \u041d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d\u043e \u043d\u0438 \u043e\u0434\u043d\u043e \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430")
            return

        discount_pct = state.get("discount", 10)
        period = state.get("period", "1d")
        period_label = dict(_REPORT_PERIODS).get(period, "1 \u0434\u0435\u043d\u044c")
        category_ids = state.get("cats") or None
        user_settings = await self._bot._db_call(self._bot.db.get_user_settings, user_id)
        user_city = user_settings["city_slug"] if user_settings else None
        plan_type = user_settings.get("plan_type", "free") if user_settings else "free"
        report_type = state.get("kind", "discounts")
        is_new_report = self._rm.is_new_products_report(state)
        is_sold_report = self._rm.is_sold_products_report(state)
        limited_categories: list[str] | None = None
        exhausted_categories: list[str] = []

        if user_settings is not None and plan_type == "free":
            if category_ids:
                limited_categories = list(category_ids)
            else:
                cats = (
                    await self._bot._db_call(self._bot.db.get_sold_known_categories, city_slug=user_city)
                    if is_sold_report
                    else await self._bot._db_call(self._bot.db.get_all_known_categories, city_slug=user_city)
                )
                limited_categories = [cat["id"] for cat in cats]
            today_msk = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
            exhausted_categories = [
                cat_id for cat_id in limited_categories
                if await self._bot._db_call(
                    self._bot.db.get_report_limit_usage,
                    user_id,
                    cat_id,
                    report_type,
                    today_msk,
                )
            ]
            limited_categories = [cat_id for cat_id in limited_categories if cat_id not in exhausted_categories]
            if not limited_categories:
                await self._bot.send_message(
                    chat_id,
                    "\u041b\u0438\u043c\u0438\u0442 free: 1 \u043e\u0442\u0447\u0435\u0442 \u043d\u0430 \u043a\u0430\u0436\u0434\u0443\u044e \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u0432 \u0441\u0443\u0442\u043a\u0438. \u041f\u043e \u0432\u0441\u0435\u043c \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u044b\u043c \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f\u043c \u043b\u0438\u043c\u0438\u0442 \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0443\u0436\u0435 \u0438\u0441\u0447\u0435\u0440\u043f\u0430\u043d.",
                    reply_markup={"inline_keyboard": [[{"text": "\u0413\u043b\u0430\u0432\u043d\u0430\u044f", "callback_data": "menu_back"}]]},
                )
                return
            if category_ids is None or exhausted_categories:
                category_ids = limited_categories

        if is_new_report:
            products = await self._bot._db_call(
                self._bot.db.get_new_report_products,
                statuses, period=period, category_ids=category_ids, city_slug=user_city,
            )
        elif is_sold_report:
            products = await self._bot._db_call(
                self._bot.db.get_sold_report_products,
                statuses, period=period, category_ids=category_ids, city_slug=user_city,
            )
        else:
            products = await self._bot._db_call(
                self._bot.db.get_report_products,
                statuses, discount_pct, period=period,
                category_ids=category_ids, city_slug=user_city,
            )

        cond_text = ", ".join(
            (["\u041d\u043e\u0432\u044b\u0435"] if state.get("new") else []) +
            (["\u0411/\u0423"] if state.get("bu") else [])
        )
        report_title = self._rm.report_title(state)
        filter_text = f"\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435: {cond_text} | \u041f\u0435\u0440\u0438\u043e\u0434: {period_label}"
        if not self._rm.is_no_discount_report(state):
            filter_text = f"\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435: {cond_text} | \u0421\u043a\u0438\u0434\u043a\u0430: \u043e\u0442 {discount_pct}% | \u041f\u0435\u0440\u0438\u043e\u0434: {period_label}"

        if not products:
            skipped_note = f"\n\n\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0439 \u043f\u043e \u043b\u0438\u043c\u0438\u0442\u0443: {len(exhausted_categories)}." if exhausted_categories else ""
            await self._bot.send_message(
                chat_id,
                f"\U0001f4ca <b>{report_title}</b>\n\n{filter_text}\n\n\u0422\u043e\u0432\u0430\u0440\u043e\u0432 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.{skipped_note}",
                reply_markup={"inline_keyboard": [[{"text": "\U0001f3e0 \u0413\u043b\u0430\u0432\u043d\u0430\u044f", "callback_data": "menu_back"}]]},
            )
            return

        if user_settings is not None and plan_type == "free" and limited_categories:
            today_msk = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
            for cat_id in limited_categories:
                ok = await self._bot._db_call(
                    self._bot.db.consume_free_report_limit,
                    user_id,
                    cat_id,
                    report_type,
                    today_msk,
                )
                if not ok:
                    await self._bot.send_message(chat_id, "\u041b\u0438\u043c\u0438\u0442 free \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0443\u0436\u0435 \u0438\u0441\u0447\u0435\u0440\u043f\u0430\u043d.")
                    return

        skipped_categories_note = f"\n\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0439 \u043f\u043e \u043b\u0438\u043c\u0438\u0442\u0443: {len(exhausted_categories)}." if exhausted_categories else ""
        await self._bot.send_message(
            chat_id,
            f"\U0001f4ca <b>{report_title}</b>\n"
            f"\u041d\u0430\u0439\u0434\u0435\u043d\u043e: {len(products)} \u0442\u043e\u0432. | {filter_text}{skipped_categories_note}",
        )

        from config import config
        base_url = config.api_base_url.rstrip("/")

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
            safe_url = utils._escape_html_attr(url)
            raw_title = utils._truncate_report_title(str(p.get("title") or "\u0411\u0435\u0437 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f"))
            safe_title = utils._escape_html_text(raw_title)
            icon = "\U0001f195" if p.get("status") == "\u041d\u043e\u0432\u044b\u0439" else "\u267b\ufe0f"
            cnt = f" (x{p['_count']})" if p["_count"] > 1 else ""
            cur = utils._format_price(p.get("current_price"))

            if is_new_report:
                price_text = f"{cur} \u20bd"
                prev_price = p.get("previous_price")
                if prev_price and p.get("current_price") is not None and prev_price > p["current_price"]:
                    prev_f = utils._format_price(prev_price)
                    price_text += f" <s>{prev_f} \u20bd</s>"
                item_blocks.append(
                    f'\u2022 <a href="{safe_url}">{safe_title}{cnt}</a>\n'
                    f"  \U0001f4b0 {price_text} {icon}"
                )
            elif is_sold_report:
                price_text = f"{cur} \u20bd"
                prev_price = p.get("previous_price")
                if prev_price and p.get("current_price") is not None and prev_price > p["current_price"]:
                    prev_f = utils._format_price(prev_price)
                    price_text += f" <s>{prev_f} \u20bd</s>"
                sold_at = str(p.get("sold_at") or "")[:10]
                sold_text = f"\n  \U0001f4c5 {utils._escape_html_text(sold_at)}" if sold_at else ""
                item_blocks.append(
                    f'\U0001f6d2 <b><a href="{safe_url}">{safe_title}{cnt}</a></b>\n'
                    f"\U0001f4b0 {price_text} {icon}{sold_text}"
                )
            else:
                prev_f = utils._format_price(p.get("previous_price"))
                try:
                    disc_txt = f"{float(p.get('discount_pct') or 0):.0f}%"
                except (TypeError, ValueError):
                    disc_txt = "0%"
                item_blocks.append(
                    f'{icon} <b><a href="{safe_url}">{safe_title}{cnt}</a></b>\n'
                    f"\U0001f4b0 {cur} \u20bd <s>{prev_f} \u20bd</s> \u2014 -{disc_txt}"
                )

        if not await self._send_report_batches(chat_id, item_blocks):
            pass

        final_result = await self._bot.send_message(
            chat_id,
            "\u2705 \u041e\u0442\u0447\u0435\u0442 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d.",
            reply_markup={"inline_keyboard": [[{"text": "\U0001f3e0 \u0413\u043b\u0430\u0432\u043d\u0430\u044f", "callback_data": "menu_back"}]]},
        )
        if final_result == "fail":
            pass
