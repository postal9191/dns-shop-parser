"""
Состояние пользовательских сессий и машина состояний мастера отчётов.
"""
import asyncio
from typing import Set, TypedDict

from . import utils

# ─── TypedDict для состояния мастера отчёта ─────────────────────────────────

class ReportState(TypedDict):
    kind: str          # "discounts" | "new_products" | "sold_products"
    new: bool          # включать новые товары
    bu: bool           # включать Б/У
    discount: int      # мин. скидка % (10–90)
    cats: list[str]    # выбранные category_id (пусто = все)
    period: str        # "1d" | "3d" | "7d" | "30d" | "all"
    cat_query: str     # поисковый фильтр в пикере категорий


# ─── Периоды отчёта ───────────────────────────────────────────────────────────

_REPORT_PERIODS = [
    ("1d",  "1 день"),
    ("3d",  "3 дня"),
    ("7d",  "Неделя"),
    ("30d", "Месяц"),
    ("all", "Весь срок"),
]


# ─── UserState — все контейнеры состояния в одном месте ───────────────────────

class UserState:
    """Хранит все пользовательские состояния и блокировки.

    Все 9 контейнеров теперь в одном объекте вместо разбросанных
    по атрибутам TelegramBot — это упрощает очистку, тестирование
    и передачу состояния обработчикам.
    """

    def __init__(self) -> None:
        self.waiting_for_interval: Set[str] = set()
        self.user_cat_page: dict[str, int] = {}
        self.report_state: dict[str, ReportState] = {}
        self.report_cat_page: dict[str, int] = {}
        self.report_search_mode: dict[str, tuple[str, int]] = {}
        self.settings_search_mode: dict[str, tuple[str, int]] = {}
        self.user_cat_query: dict[str, str] = {}
        self.admin_rights_users: dict[str, list[dict]] = {}
        self.admin_rights_draft: dict[str, dict[str, str]] = {}
        self.admin_rights_page: dict[str, int] = {}
        self.broadcast_lock = asyncio.Lock()
        self.subscriber_lock = asyncio.Lock()

    def cleanup(self, user_id: str) -> None:
        """Очищает все состояния пользователя при отписке."""
        self.waiting_for_interval.discard(user_id)
        self.user_cat_page.pop(user_id, None)
        self.report_state.pop(user_id, None)
        self.report_cat_page.pop(user_id, None)
        self.report_search_mode.pop(user_id, None)
        self.settings_search_mode.pop(user_id, None)
        self.user_cat_query.pop(user_id, None)
        self.admin_rights_users.pop(user_id, None)
        self.admin_rights_draft.pop(user_id, None)
        self.admin_rights_page.pop(user_id, None)


# ─── ReportMachine — логика управления состоянием отчёта ──────────────────────

class ReportMachine:
    """Управляет состоянием мастера отчёта для каждого пользователя."""

    def __init__(self, user_state: UserState) -> None:
        self._us = user_state

    # ── Factories ────────────────────────────────────────────────────────────────

    def new_state(self, kind: str = "discounts") -> ReportState:
        return ReportState(
            kind=kind,
            new=True,
            bu=True,
            discount=10,
            cats=[],
            period="1d",
            cat_query="",
        )

    def get_state(self, user_id: str) -> ReportState:
        if user_id not in self._us.report_state:
            self._us.report_state[user_id] = self.new_state()
        else:
            self._us.report_state[user_id].setdefault("kind", "discounts")
            self._us.report_state[user_id].setdefault("cat_query", "")
        return self._us.report_state[user_id]

    # ── Predicates ───────────────────────────────────────────────────────────────

    def is_new_products_report(self, state: dict) -> bool:
        return state.get("kind") == "new_products"

    def is_sold_products_report(self, state: dict) -> bool:
        return state.get("kind") == "sold_products"

    def is_no_discount_report(self, state: dict) -> bool:
        return self.is_new_products_report(state) or self.is_sold_products_report(state)

    # ── Formatters ───────────────────────────────────────────────────────────────

    def report_title(self, state: dict) -> str:
        if self.is_new_products_report(state):
            return "Новые товары"
        if self.is_sold_products_report(state):
            return "Проданные товары"
        return "Скидки"

    def steps_total(self, state: dict) -> int:
        return 3 if self.is_no_discount_report(state) else 4

    def condition_text(self, state: dict) -> str:
        return (
            f"📊 <b>{self.report_title(state)} — Шаг 1 из {self.steps_total(state)}</b>\n"
            "Выберите состояние товара:"
        )

    def categories_text(self, state: dict) -> str:
        step = 2 if self.is_no_discount_report(state) else 3
        return (
            f"📊 <b>{self.report_title(state)} — Шаг {step} из {self.steps_total(state)}</b>\n"
            "Выберите категории (пусто = все):"
        )

    def period_text(self, state: dict) -> str:
        step = 3 if self.is_no_discount_report(state) else 4
        if self.is_new_products_report(state):
            hint = "по дате добавления товара"
        elif self.is_sold_products_report(state):
            hint = "по дате продажи/исчезновения товара"
        else:
            hint = "по дате последнего обновления цены"
        return (
            f"📊 <b>{self.report_title(state)} — Шаг {step} из {self.steps_total(state)}</b>\n"
            f"Выберите период ({hint}):"
        )
