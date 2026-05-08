"""
Keyboard builders для Telegram-бота.
Все функции — модульного уровня (без self), принимают зависимости явно.
"""
from data.cities import CITIES

from . import utils
from .state import ReportState

# ─── Constants ─────────────────────────────────────────────────────────────────

CATS_PER_PAGE = 8


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _build_category_page(
    items: list[dict],
    page: int,
    query: str,
    *,
    user_selected_ids: set[str],
    all_selected: bool,
    all_callback_data: str,
    toggle_callback_prefix: str,
    back_callback_data: str,
    next_callback_data: str,
    search_callback_data: str = "cat_search",
    search_clear_callback_data: str = "cat_search_clear",
    page_callback_prefix: str = "cat_page",
) -> list[dict]:
    """Общий пагинатор для пикера категорий (settings и reports).

    Переиспользуемая логика, вынесенная из обоих keyboard-методов.
    """
    rows: list[dict] = []
    total_pages = max(1, (len(items) + CATS_PER_PAGE - 1) // CATS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    slice_ = items[page * CATS_PER_PAGE:(page + 1) * CATS_PER_PAGE]

    if not query:
        mark = "✅" if all_selected else "❌"
        rows.append([{"text": f"{mark} Все категории", "callback_data": all_callback_data}])

    for item in slice_:
        mark = "✅" if item["id"] in user_selected_ids else "❌"
        rows.append([{
            "text": f"{mark} {item['name'][:28]}",
            "callback_data": f"{toggle_callback_prefix}{item['id']}",
        }])

    if not items and query:
        rows.append([{"text": "Ничего не найдено", "callback_data": f"{page_callback_prefix}:noop"}])

    nav: list[dict] = []
    if page > 0:
        nav.append({"text": "← Назад", "callback_data": f"{page_callback_prefix}:{page - 1}"})
    nav.append({"text": f"{page + 1}/{total_pages}", "callback_data": f"{page_callback_prefix}:noop"})
    if page < total_pages - 1:
        nav.append({"text": "Вперёд →", "callback_data": f"{page_callback_prefix}:{page + 1}"})
    if nav:
        rows.append(nav)

    if query:
        rows.append([
            {"text": f"🔍 «{query[:20]}»", "callback_data": f"{page_callback_prefix}:noop"},
            {"text": "❌ Сбросить", "callback_data": search_clear_callback_data},
        ])
    else:
        rows.append([{"text": "🔍 Поиск", "callback_data": search_callback_data}])

    rows.append([
        {"text": "← Назад", "callback_data": back_callback_data},
        {"text": "Далее →", "callback_data": next_callback_data},
    ])
    rows.append([{"text": "🏠 Главная", "callback_data": "menu_back"}])
    return rows


# ─── Settings keyboards ───────────────────────────────────────────────────────

def _build_main_menu_keyboard(user_id: str, admin_id: str | None) -> dict:
    """Главное inline-меню для подписчика."""
    rows = [
        [
            {"text": "⚙️ Настройки", "callback_data": "menu_settings_open"},
            {"text": "📊 Отчеты", "callback_data": "report_open"},
        ],
    ]
    if admin_id and user_id == admin_id:
        rows.append([{"text": "🎛️ Админ-панель", "callback_data": "menu_admin"}])
    return {"inline_keyboard": rows}


def _build_settings_submenu_keyboard() -> dict:
    """Подменю настроек."""
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


def _build_settings_keyboard(s: dict) -> dict:
    """Inline-клавиатура /settings на основе текущих настроек."""
    on_off = lambda v: "✅" if v else "❌"
    pct = s.get("min_price_drop_pct", 0)
    notif = s.get("notifications_on", True)
    return {
        "inline_keyboard": [
            [{"text": f"{on_off(s.get('notify_new'))} Новые товары",
              "callback_data": "set_new:0" if s.get("notify_new") else "set_new:1"}],
            [{"text": f"{on_off(s.get('notify_price_drop'))} Снижение цен",
              "callback_data": "set_drop:0" if s.get("notify_price_drop") else "set_drop:1"}],
            [
                {"text": f"{'✅' if pct == 0 else ''} Любое снижение", "callback_data": "set_pct:0"},
                {"text": f"{'✅' if pct == 5 else ''} >5%",  "callback_data": "set_pct:5"},
                {"text": f"{'✅' if pct == 10 else ''} >10%", "callback_data": "set_pct:10"},
                {"text": f"{'✅' if pct == 20 else ''} >20%", "callback_data": "set_pct:20"},
            ],
            [{"text": f"{on_off(notif)} Уведомления (мастер)",
              "callback_data": "set_notif:0" if notif else "set_notif:1"}],
            [{"text": "← Главное меню", "callback_data": "menu_back"}],
        ]
    }


def _build_city_keyboard(current_slug: str = "") -> dict:
    """Inline-клавиатура выбора города (3 кнопки в ряд)."""
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


def _build_admin_notify_keyboard(s: dict) -> dict:
    """Inline-клавиатура уведомлений админа."""
    err_on = s.get("notify_errors", True)
    pf_on = s.get("notify_parse_finish", True)
    on_off = lambda v: "✅" if v else "❌"
    return {
        "inline_keyboard": [
            [
                {"text": f"{on_off(err_on)} Ошибки: {'ВКЛ' if err_on else 'ВЫКЛ'}",
                  "callback_data": "set_err:0" if err_on else "set_err:1"},
                {"text": f"{on_off(pf_on)} Парсинг: {'ВКЛ' if pf_on else 'ВЫКЛ'}",
                  "callback_data": "set_pf:0" if pf_on else "set_pf:1"},
            ],
            [{"text": "← Назад в админ-панель", "callback_data": "admin_back"}],
        ]
    }


# ─── Category picker (settings) ─────────────────────────────────────────────

def _build_categories_keyboard(
    db,
    user_id: str,
    page: int,
    user_cat_query: str,
    user_cats_set: set[str],
    all_cats: list[dict],
) -> dict:
    """Inline-клавиатура выбора категорий с пагинацией и поиском (settings).

    Все параметры передаются явно — функция не читает db напрямую.
    """
    query = user_cat_query.strip().lower()
    sorted_cats = sorted(all_cats, key=lambda c: (0 if c["id"] in user_cats_set else 1, c["name"]))
    if query:
        sorted_cats = [c for c in sorted_cats if query in c["name"].lower()]

    rows = _build_category_page(
        sorted_cats, page, query,
        user_selected_ids=user_cats_set,
        all_selected=(len(user_cats_set) == 0),
        all_callback_data="cat_all",
        toggle_callback_prefix="cat_toggle:",
        back_callback_data="menu_back",
        next_callback_data="menu_back",
    )
    return {"inline_keyboard": rows}


# ─── Report keyboards ───────────────────────────────────────────────────────────

def _build_report_type_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🏷 Скидки",         "callback_data": "report_kind:discounts"}],
            [{"text": "🆕 Новые товары",    "callback_data": "report_kind:new_products"}],
            [{"text": "🛒 Проданные товары","callback_data": "report_kind:sold_products"}],
            [{"text": "🏠 Главная",         "callback_data": "menu_back"}],
        ]
    }


def _build_report_step1_keyboard(state: dict) -> dict:
    new_mark = "✅" if state.get("new") else "❌"
    bu_mark  = "✅" if state.get("bu")  else "❌"
    return {
        "inline_keyboard": [
            [
                {"text": f"{new_mark} Новые", "callback_data": "report_toggle:new"},
                {"text": f"{bu_mark} Б/У",     "callback_data": "report_toggle:bu"},
            ],
            [{"text": "Далее →", "callback_data": "report_next:1"}],
            [{"text": "🏠 Главная", "callback_data": "menu_back"}],
        ]
    }


def _build_report_step2_keyboard(state: dict) -> dict:
    selected = state.get("discount", 10)
    pct_rows: list[list[dict]] = []
    row: list[dict] = []
    for p in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
        row.append({"text": f"{'✅ ' if p == selected else ''}{p}%", "callback_data": f"report_pct:{p}"})
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


def _build_report_cats_keyboard(
    db,
    user_id: str,
    page: int,
    state: ReportState,
    all_cats: list[dict],
) -> dict:
    """Клавиатура выбора категорий для отчёта (пагинация + поиск).

    all_cats передаётся явно — вызывающий решает, какие категории показывать
    (get_all_known_categories или get_sold_known_categories).
    """
    user_cats = set(state.get("cats", []))
    query = state.get("cat_query", "").strip().lower()
    sorted_cats = sorted(all_cats, key=lambda c: (0 if c["id"] in user_cats else 1, c["name"]))
    if query:
        sorted_cats = [c for c in sorted_cats if query in c["name"].lower()]

    rows = _build_category_page(
        sorted_cats, page, query,
        user_selected_ids=user_cats,
        all_selected=(len(user_cats) == 0),
        all_callback_data="report_cat_all",
        toggle_callback_prefix="report_cat_toggle:",
        back_callback_data="report_back:2",
        next_callback_data="report_next:cats",
        search_callback_data="report_cat_search",
        search_clear_callback_data="report_cat_search_clear",
        page_callback_prefix="report_cat_page",
    )
    return {"inline_keyboard": rows}


def _build_report_step3_keyboard(state: dict) -> dict:
    from .state import _REPORT_PERIODS
    selected = state.get("period", "1d")
    rows = []
    for val, label in _REPORT_PERIODS:
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


def _build_report_step4_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "📥 Получить отчет", "callback_data": "report_get"}],
            [
                {"text": "← Назад", "callback_data": "report_back:3"},
                {"text": "🏠 Главная", "callback_data": "menu_back"},
            ],
        ]
    }


# ─── Admin keyboard ────────────────────────────────────────────────────────────

PLAN_TYPES = ("super", "pro", "free")
ADMIN_RIGHTS_PAGE_SIZE = 10


def _build_admin_rights_users_keyboard(
    users: list[dict],
    page: int,
    draft: dict[str, str] | None = None,
) -> dict:
    """Admin keyboard with active users and pending plan changes."""
    draft = draft or {}
    total_pages = max(1, (len(users) + ADMIN_RIGHTS_PAGE_SIZE - 1) // ADMIN_RIGHTS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * ADMIN_RIGHTS_PAGE_SIZE
    rows: list[list[dict]] = []

    for user in users[start:start + ADMIN_RIGHTS_PAGE_SIZE]:
        uid = str(user.get("user_id"))
        current = user.get("plan_type", "free")
        effective = draft.get(uid, current)
        dirty = "*" if effective != current else ""
        username = user.get("username") or "-"
        if username != "-" and not username.startswith("@"):
            username = f"@{username}"
        rows.append([{
            "text": f"{dirty}{username} | {uid} | {effective}",
            "callback_data": f"admin_rights_pick:{uid}",
        }])

    if not users:
        rows.append([{"text": "Пользователей нет", "callback_data": "admin_rights_noop"}])

    nav: list[dict] = []
    if page > 0:
        nav.append({"text": "←", "callback_data": f"admin_rights_page:{page - 1}"})
    nav.append({"text": f"{page + 1}/{total_pages}", "callback_data": "admin_rights_noop"})
    if page < total_pages - 1:
        nav.append({"text": "→", "callback_data": f"admin_rights_page:{page + 1}"})
    rows.append(nav)

    rows.append([
        {"text": "Сохранить", "callback_data": "admin_rights_save"},
        {"text": "Отмена", "callback_data": "admin_rights_cancel"},
    ])
    rows.append([{"text": "← Назад в админ-панель", "callback_data": "admin_back"}])
    return {"inline_keyboard": rows}


def _build_admin_rights_plan_keyboard(
    user: dict,
    selected_plan: str,
    has_changes: bool,
) -> dict:
    """Admin keyboard for one user's plan draft."""
    rows = []
    for plan in PLAN_TYPES:
        mark = "✅ " if selected_plan == plan else ""
        rows.append([{
            "text": f"{mark}{plan}",
            "callback_data": f"admin_rights_set:{user.get('user_id')}:{plan}",
        }])
    rows.append([
        {"text": "Сохранить", "callback_data": "admin_rights_save"},
        {"text": "К списку", "callback_data": "admin_rights"},
    ])
    if has_changes:
        rows.append([{"text": "Отмена изменений", "callback_data": "admin_rights_cancel"}])
    rows.append([{"text": "← Назад в админ-панель", "callback_data": "admin_back"}])
    return {"inline_keyboard": rows}


def _build_admin_menu_keyboard() -> dict:
    """Главное меню админ-панели (используется и в /admin, и в admin_back)."""
    return {
        "inline_keyboard": [
            [
                {"text": "▶️ Запустить",  "callback_data": "admin_start"},
                {"text": "⏹ Остановить", "callback_data": "admin_stop"},
            ],
            [
                {"text": "🔄 Перезапустить", "callback_data": "admin_restart"},
                {"text": "⏱ Интервал",      "callback_data": "admin_interval"},
            ],
            [
                {"text": "📄 Логи",         "callback_data": "admin_logs"},
            ],
            [
                {"text": "📊 Статус",       "callback_data": "admin_status"},
                {"text": "🔔 Уведомления",   "callback_data": "admin_notify"},
            ],
            [
                {"text": "Права пользователей", "callback_data": "admin_rights"},
            ],
            [
                {"text": "⬅️ Назад в главное меню", "callback_data": "menu_back"},
            ],
        ]
    }
