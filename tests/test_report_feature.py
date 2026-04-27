"""
Тесты для функции отчёта: db_manager.get_report_products и мастер отчёта в боте.
"""

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from parser.db_manager import DBManager
from parser.models import Product
from services.telegram_bot import TelegramBot


# ─── Фикстуры ────────────────────────────────────────────────────────────────

def _make_product(
    uid: str,
    title: str,
    price: int,
    price_old: int,
    status: str = "Новый",
    category_id: str = "cat-1",
    category_name: str = "Ноутбуки",
) -> Product:
    return Product(
        id=f"as-{uid}",
        uuid=f"{uid}-0000-0000-0000-000000000000",
        title=title,
        price=price,
        price_old=price_old,
        url=f"/catalog/{uid}/",
        category_id=category_id,
        category_name=category_name,
        status=status,
    )


def _make_bot(db=None) -> TelegramBot:
    bot = TelegramBot.__new__(TelegramBot)
    bot.token = "test"
    bot.api_url = "https://api.telegram.org/bottest"
    bot.db = db
    bot.enabled = True
    bot.admin_id = "999"
    bot.subscribed_users = {"user1"}
    bot._session = None
    bot._waiting_for_interval = set()
    bot._broadcast_lock = asyncio.Lock()
    bot._subscriber_lock = asyncio.Lock()
    bot._user_cat_page = {}
    bot._report_state = {}
    bot._report_cat_page = {}
    bot._report_search_mode = {}
    bot._settings_search_mode = {}
    bot._user_cat_query = {}
    bot.parser_controller = None
    return bot


# ─── DBManager: get_report_products ─────────────────────────────────────────

class TestGetReportProducts:
    def _seed(self, db: DBManager) -> None:
        products = [
            _make_product("aaa", "Новый 30%",  700, 1000, "Новый", "cat-1", "Ноутбуки"),
            _make_product("bbb", "Новый 15%",  850, 1000, "Новый", "cat-1", "Ноутбуки"),
            _make_product("ccc", "Б/У 50%",    500, 1000, "Б/У",   "cat-2", "Мониторы"),
            _make_product("ddd", "Б/У 5%",     950, 1000, "Б/У",   "cat-2", "Мониторы"),
            _make_product("eee", "Без скидки", 1000, 1000, "Новый", "cat-1", "Ноутбуки"),
            _make_product("fff", "Без цены",   800, 0,    "Новый", "cat-1", "Ноутбуки"),
        ]
        db.upsert_products(products)

    def test_filter_by_min_discount(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый", "Б/У"], 20, period="all")
        titles = [r["title"] for r in result]
        assert "Новый 30%" in titles
        assert "Б/У 50%" in titles
        assert "Новый 15%" not in titles
        assert "Б/У 5%" not in titles

    def test_filter_new_only(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый"], 10, period="all")
        assert all(r["status"] == "Новый" for r in result)

    def test_filter_bu_only(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Б/У"], 10, period="all")
        assert all(r["status"] == "Б/У" for r in result)

    def test_empty_statuses_returns_empty(self, db_memory):
        self._seed(db_memory)
        assert db_memory.get_report_products([], 10) == []

    def test_no_discount_excluded(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый", "Б/У"], 1, period="all")
        titles = [r["title"] for r in result]
        assert "Без скидки" not in titles
        assert "Без цены" not in titles

    def test_sorted_by_discount_desc(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый", "Б/У"], 1, period="all")
        discounts = [r["discount_pct"] for r in result]
        assert discounts == sorted(discounts, reverse=True)

    def test_result_fields(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый"], 20, period="all")
        assert result
        for field in ("title", "url", "current_price", "previous_price", "status", "category_name", "discount_pct"):
            assert field in result[0]

    def test_limit_respected(self, db_memory):
        products = [_make_product(f"p{i}", f"Товар {i}", 500, 1000) for i in range(10)]
        db_memory.upsert_products(products)
        result = db_memory.get_report_products(["Новый"], 10, period="all", limit=3)
        assert len(result) <= 3

    def test_period_1d_includes_fresh(self, db_memory):
        self._seed(db_memory)
        result_1d = db_memory.get_report_products(["Новый", "Б/У"], 10, period="1d")
        result_all = db_memory.get_report_products(["Новый", "Б/У"], 10, period="all")
        assert len(result_1d) == len(result_all)  # upsert пишет updated_at=now

    def test_period_default_is_1d(self, db_memory):
        self._seed(db_memory)
        assert (
            len(db_memory.get_report_products(["Новый"], 10)) ==
            len(db_memory.get_report_products(["Новый"], 10, period="1d"))
        )

    def test_category_filter_none_returns_all(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый", "Б/У"], 1, period="all", category_ids=None)
        cats = {r["category_name"] for r in result}
        assert len(cats) > 1

    def test_category_filter_single(self, db_memory):
        self._seed(db_memory)
        result = db_memory.get_report_products(["Новый", "Б/У"], 1, period="all", category_ids=["cat-2"])
        assert all(r["category_name"] == "Б/У" or r["status"] == "Б/У" for r in result)
        titles = [r["title"] for r in result]
        assert "Новый 30%" not in titles

    def test_category_filter_empty_list_returns_all(self, db_memory):
        self._seed(db_memory)
        result_empty = db_memory.get_report_products(["Новый", "Б/У"], 1, period="all", category_ids=[])
        result_none = db_memory.get_report_products(["Новый", "Б/У"], 1, period="all", category_ids=None)
        assert len(result_empty) == len(result_none)


# ─── TelegramBot: клавиатуры ─────────────────────────────────────────────────

class TestReportKeyboards:
    def test_step1_both_enabled(self):
        bot = _make_bot()
        kb = bot._build_report_step1_keyboard({"new": True, "bu": True})
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("✅" in t and "Новые" in t for t in texts)
        assert any("✅" in t and "Б/У" in t for t in texts)

    def test_step1_has_next_home(self):
        bot = _make_bot()
        kb = bot._build_report_step1_keyboard({"new": True, "bu": True})
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_next:1" in callbacks
        assert "menu_back" in callbacks

    def test_step2_selected_marked(self):
        bot = _make_bot()
        kb = bot._build_report_step2_keyboard({"discount": 30})
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("✅" in t and "30%" in t for t in texts)
        assert sum(1 for t in texts if "✅" in t and "%" in t) == 1

    def test_step2_all_pcts(self):
        bot = _make_bot()
        kb = bot._build_report_step2_keyboard({"discount": 10})
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        for pct in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
            assert f"report_pct:{pct}" in callbacks

    def test_step2_nav(self):
        bot = _make_bot()
        kb = bot._build_report_step2_keyboard({"discount": 10})
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_back:1" in callbacks
        assert "report_next:2" in callbacks
        assert "menu_back" in callbacks

    def test_cats_keyboard_no_db(self):
        bot = _make_bot(db=None)
        kb = bot._build_report_cats_keyboard("user1")
        assert kb == {"inline_keyboard": []}

    def test_cats_keyboard_all_selected_by_default(self):
        bot = _make_bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [
            {"id": "cat-1", "name": "Ноутбуки"},
            {"id": "cat-2", "name": "Мониторы"},
        ]
        bot.db = mock_db
        bot._get_report_state("user1")  # default cats=[]
        kb = bot._build_report_cats_keyboard("user1")
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("✅" in t and "Все категории" in t for t in texts)

    def test_cats_keyboard_nav(self):
        bot = _make_bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [{"id": "cat-1", "name": "Ноутбуки"}]
        bot.db = mock_db
        bot._get_report_state("user1")
        kb = bot._build_report_cats_keyboard("user1")
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_back:2" in callbacks
        assert "report_next:cats" in callbacks
        assert "menu_back" in callbacks

    def test_period_keyboard_all_options(self):
        bot = _make_bot()
        kb = bot._build_report_step3_keyboard({"period": "1d"})
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        for val in ["1d", "3d", "7d", "30d", "all"]:
            assert f"report_period:{val}" in callbacks

    def test_period_keyboard_back_to_cats(self):
        bot = _make_bot()
        kb = bot._build_report_step3_keyboard({"period": "1d"})
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_back:cats" in callbacks
        assert "report_next:3" in callbacks

    def test_step4_keyboard(self):
        bot = _make_bot()
        kb = bot._build_report_step4_keyboard()
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_get" in callbacks
        assert "report_back:3" in callbacks
        assert "menu_back" in callbacks


# ─── TelegramBot: состояние ───────────────────────────────────────────────────

class TestReportState:
    def test_default_state(self):
        bot = _make_bot()
        state = bot._get_report_state("user1")
        assert state == {"new": True, "bu": True, "discount": 10, "cats": [], "period": "1d", "cat_query": ""}

    def test_state_isolated_per_user(self):
        bot = _make_bot()
        bot._get_report_state("user1")["discount"] = 50
        assert bot._get_report_state("user2")["discount"] == 10


# ─── TelegramBot: обработчики ─────────────────────────────────────────────────

class TestReportCallbacks:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _bot(self):
        bot = _make_bot()
        bot._answer_callback = AsyncMock(return_value=True)
        bot.edit_message_text = AsyncMock(return_value=True)
        bot.send_message = AsyncMock(return_value="ok")
        return bot

    def test_report_open_resets_state(self):
        bot = self._bot()
        bot._report_state["user1"] = {"new": False, "bu": False, "discount": 80, "cats": ["cat-x"], "period": "30d"}
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_open"))
        s = bot._report_state["user1"]
        assert s == {"new": True, "bu": True, "discount": 10, "cats": [], "period": "1d", "cat_query": ""}
        assert bot._report_cat_page.get("user1", 0) == 0

    def test_report_open_text_step1_of_4(self):
        bot = self._bot()
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_open"))
        args = bot.edit_message_text.call_args[0]
        assert "1 из 4" in args[2]

    def test_toggle_new(self):
        bot = self._bot()
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_toggle:new"))
        assert bot._report_state["user1"]["new"] is False

    def test_next1_blocks_if_nothing(self):
        bot = self._bot()
        bot._report_state["user1"] = {"new": False, "bu": False, "discount": 10, "cats": [], "period": "1d"}
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_next:1"))
        _, kwargs = bot._answer_callback.call_args
        assert kwargs.get("alert") is True

    def test_next2_goes_to_cats(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [{"id": "cat-1", "name": "Ноутбуки"}]
        bot.db = mock_db
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_next:2"))
        args = bot.edit_message_text.call_args[0]
        assert "3 из 4" in args[2]

    def test_cat_toggle_adds_category(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [{"id": "cat-1", "name": "Ноутбуки"}]
        bot.db = mock_db
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_toggle:cat-1"))
        assert "cat-1" in bot._report_state["user1"]["cats"]

    def test_cat_toggle_removes_category(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [{"id": "cat-1", "name": "Ноутбуки"}]
        bot.db = mock_db
        bot._report_state["user1"] = {"new": True, "bu": True, "discount": 10, "cats": ["cat-1"], "period": "1d"}
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_toggle:cat-1"))
        assert "cat-1" not in bot._report_state["user1"]["cats"]

    def test_cat_all_clears_selection(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [{"id": "cat-1", "name": "Ноутбуки"}]
        bot.db = mock_db
        bot._report_state["user1"] = {"new": True, "bu": True, "discount": 10, "cats": ["cat-1"], "period": "1d"}
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_all"))
        assert bot._report_state["user1"]["cats"] == []

    def test_next_cats_goes_to_period(self):
        bot = self._bot()
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_next:cats"))
        args = bot.edit_message_text.call_args[0]
        assert "4 из 4" in args[2]

    def test_back_cats_goes_to_cats(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_all_known_categories.return_value = [{"id": "cat-1", "name": "Ноутбуки"}]
        bot.db = mock_db
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_back:cats"))
        args = bot.edit_message_text.call_args[0]
        assert "3 из 4" in args[2]

    def test_period_sets_period(self):
        bot = self._bot()
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_period:7d"))
        assert bot._report_state["user1"]["period"] == "7d"

    def test_next3_confirm_shows_cats_label(self):
        bot = self._bot()
        bot._report_state["user1"] = {"new": True, "bu": True, "discount": 10, "cats": ["cat-1", "cat-2"], "period": "1d"}
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_next:3"))
        args = bot.edit_message_text.call_args[0]
        assert "2 шт." in args[2]

    def test_send_report_passes_category_ids(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_report_products.return_value = []
        bot.db = mock_db
        state = {"new": True, "bu": False, "discount": 10, "cats": ["cat-1"], "period": "1d"}
        self._run(bot._send_report("user1", "chat1", state))
        mock_db.get_report_products.assert_called_once_with(["Новый"], 10, period="1d", category_ids=["cat-1"], city_slug=ANY)

    def test_send_report_empty_cats_passes_none(self):
        bot = self._bot()
        mock_db = MagicMock()
        mock_db.get_report_products.return_value = []
        bot.db = mock_db
        state = {"new": True, "bu": True, "discount": 10, "cats": [], "period": "all"}
        self._run(bot._send_report("user1", "chat1", state))
        mock_db.get_report_products.assert_called_once_with(["Новый", "Б/У"], 10, period="all", category_ids=None, city_slug=ANY)

    def test_main_menu_has_report_button(self):
        bot = _make_bot()
        callbacks = [btn["callback_data"] for row in bot._build_main_menu_keyboard("user1")["inline_keyboard"] for btn in row]
        assert "report_open" in callbacks
        assert "menu_settings_open" in callbacks


# ─── Поиск категорий в отчёте ────────────────────────────────────────────────

def _make_db_with_cats(cats: list[dict]) -> MagicMock:
    mock_db = MagicMock()
    mock_db.get_all_known_categories.return_value = cats
    return mock_db


class TestReportCatSearch:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _bot(self, cats=None):
        bot = _make_bot(db=_make_db_with_cats(cats or [
            {"id": "cat-1", "name": "Ноутбуки"},
            {"id": "cat-2", "name": "Холодильники"},
            {"id": "cat-3", "name": "Ходунки"},
        ]))
        bot._answer_callback = AsyncMock(return_value=True)
        bot.edit_message_text = AsyncMock(return_value=True)
        bot.send_message = AsyncMock(return_value="ok")
        return bot

    def test_keyboard_has_search_button_by_default(self):
        bot = self._bot()
        bot._get_report_state("user1")
        kb = bot._build_report_cats_keyboard("user1")
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_cat_search" in callbacks

    def test_keyboard_filters_by_query(self):
        bot = self._bot()
        state = bot._get_report_state("user1")
        state["cat_query"] = "хо"
        kb = bot._build_report_cats_keyboard("user1")
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        # Холодильники и Ходунки должны быть, Ноутбуки — нет
        assert any("Холодильники" in t for t in texts)
        assert any("Ходунки" in t for t in texts)
        assert not any("Ноутбуки" in t for t in texts)

    def test_keyboard_hides_all_categories_button_when_query(self):
        bot = self._bot()
        state = bot._get_report_state("user1")
        state["cat_query"] = "хо"
        kb = bot._build_report_cats_keyboard("user1")
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_cat_all" not in callbacks

    def test_keyboard_shows_clear_button_when_query(self):
        bot = self._bot()
        state = bot._get_report_state("user1")
        state["cat_query"] = "хо"
        kb = bot._build_report_cats_keyboard("user1")
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "report_cat_search_clear" in callbacks
        assert "report_cat_search" not in callbacks

    def test_keyboard_no_results_message(self):
        bot = self._bot()
        state = bot._get_report_state("user1")
        state["cat_query"] = "zzz_no_match"
        kb = bot._build_report_cats_keyboard("user1")
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("Ничего не найдено" in t for t in texts)

    def test_search_callback_sends_prompt(self):
        bot = self._bot()
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_search"))
        bot.send_message.assert_called_once()
        assert "user1" in bot._report_search_mode

    def test_search_callback_stores_message_id(self):
        bot = self._bot()
        bot._get_report_state("user1")
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_search"))
        assert bot._report_search_mode["user1"] == ("chat1", 42)

    def test_search_input_applies_query(self):
        bot = self._bot()
        bot._get_report_state("user1")
        bot._report_search_mode["user1"] = ("chat1", 42)
        self._run(bot._handle_report_search_input("user1", "хо"))
        assert bot._report_state["user1"]["cat_query"] == "хо"
        assert "user1" not in bot._report_search_mode
        bot.edit_message_text.assert_called_once()

    def test_search_input_resets_page(self):
        bot = self._bot()
        bot._get_report_state("user1")
        bot._report_cat_page["user1"] = 5
        bot._report_search_mode["user1"] = ("chat1", 42)
        self._run(bot._handle_report_search_input("user1", "хо"))
        assert bot._report_cat_page["user1"] == 0

    def test_clear_callback_resets_query(self):
        bot = self._bot()
        state = bot._get_report_state("user1")
        state["cat_query"] = "хо"
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_search_clear"))
        assert bot._report_state["user1"]["cat_query"] == ""

    def test_cat_all_clears_query(self):
        bot = self._bot()
        state = bot._get_report_state("user1")
        state["cat_query"] = "хо"
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_cat_all"))
        assert bot._report_state["user1"]["cat_query"] == ""

    def test_report_open_clears_search_mode(self):
        bot = self._bot()
        bot._report_search_mode["user1"] = ("chat1", 99)
        self._run(bot._handle_report_callback("cb", "user1", "chat1", 42, "report_open"))
        assert "user1" not in bot._report_search_mode


# ─── Поиск категорий в настройках ────────────────────────────────────────────

class TestSettingsCatSearch:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _bot(self, cats=None):
        bot = _make_bot(db=_make_db_with_cats(cats or [
            {"id": "cat-1", "name": "Ноутбуки"},
            {"id": "cat-2", "name": "Холодильники"},
            {"id": "cat-3", "name": "Ходунки"},
        ]))
        bot.db.get_user_categories = MagicMock(return_value=[])
        bot._answer_callback = AsyncMock(return_value=True)
        bot.edit_message_text = AsyncMock(return_value=True)
        bot.send_message = AsyncMock(return_value="ok")
        return bot

    def _run_settings_cb(self, bot, data):
        from services.telegram_bot import TelegramBot
        return self._run(bot._handle_user_settings_callback("cb", "user1", "chat1", 42, data))

    def test_keyboard_has_search_button(self):
        bot = self._bot()
        kb = bot._build_categories_keyboard("user1", 0)
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "cat_search" in callbacks

    def test_keyboard_filters_by_query(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "хо"
        kb = bot._build_categories_keyboard("user1", 0)
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("Холодильники" in t for t in texts)
        assert any("Ходунки" in t for t in texts)
        assert not any("Ноутбуки" in t for t in texts)

    def test_keyboard_hides_all_categories_button_when_query(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "хо"
        kb = bot._build_categories_keyboard("user1", 0)
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "cat_all" not in callbacks

    def test_keyboard_shows_clear_button_when_query(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "хо"
        kb = bot._build_categories_keyboard("user1", 0)
        callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        assert "cat_search_clear" in callbacks
        assert "cat_search" not in callbacks

    def test_keyboard_no_results_message(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "zzz_no_match"
        kb = bot._build_categories_keyboard("user1", 0)
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("Ничего не найдено" in t for t in texts)

    def test_search_callback_sends_prompt(self):
        bot = self._bot()
        self._run_settings_cb(bot, "cat_search")
        bot.send_message.assert_called_once()
        assert "user1" in bot._settings_search_mode

    def test_search_callback_stores_message_id(self):
        bot = self._bot()
        self._run_settings_cb(bot, "cat_search")
        assert bot._settings_search_mode["user1"] == ("chat1", 42)

    def test_search_input_applies_query(self):
        bot = self._bot()
        bot._settings_search_mode["user1"] = ("chat1", 42)
        self._run(bot._handle_settings_cat_search_input("user1", "хо"))
        assert bot._user_cat_query["user1"] == "хо"
        assert "user1" not in bot._settings_search_mode
        bot.edit_message_text.assert_called_once()

    def test_search_input_resets_page(self):
        bot = self._bot()
        bot._user_cat_page["user1"] = 5
        bot._settings_search_mode["user1"] = ("chat1", 42)
        self._run(bot._handle_settings_cat_search_input("user1", "хо"))
        assert bot._user_cat_page["user1"] == 0

    def test_clear_callback_resets_query(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "хо"
        self._run_settings_cb(bot, "cat_search_clear")
        assert bot._user_cat_query.get("user1", "") == ""

    def test_cat_all_clears_query(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "хо"
        self._run_settings_cb(bot, "cat_all")
        assert bot._user_cat_query.get("user1", "") == ""

    def test_query_is_case_insensitive(self):
        bot = self._bot()
        bot._user_cat_query["user1"] = "ХОЛОД"
        kb = bot._build_categories_keyboard("user1", 0)
        texts = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
        assert any("Холодильники" in t for t in texts)
