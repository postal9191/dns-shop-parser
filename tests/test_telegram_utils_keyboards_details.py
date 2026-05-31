from services.telegram_bot import keyboards as kb
from services.telegram_bot import utils


def _button_texts(markup: dict) -> list[str]:
    return [button["text"] for row in markup["inline_keyboard"] for button in row]


class TestTelegramUtilsDetails:
    def test_escape_html_text_escapes_markup_but_not_quotes(self):
        assert utils._escape_html_text('A&B <tag> "quote"') == 'A&amp;B &lt;tag&gt; "quote"'

    def test_escape_html_attr_escapes_quotes_for_href_values(self):
        assert utils._escape_html_attr('https://x.test/?q="a"&b=1') == (
            "https://x.test/?q=&quot;a&quot;&amp;b=1"
        )

    def test_format_price_handles_none_numbers_and_invalid_values(self):
        assert utils._format_price(None) != "?"
        assert utils._format_price("1234567") == "1 234 567"
        assert utils._format_price("not-a-price") == "?"

    def test_format_user_status_text_uses_slug_fallback_and_pct_threshold(self):
        text = utils.format_user_status_text(
            {
                "city_slug": "unknown-city",
                "notifications_on": True,
                "notify_new": False,
                "notify_price_drop": True,
                "min_price_drop_pct": 15,
            },
            ["cat-1", "cat-2"],
            {},
        )

        assert "unknown-city" in text
        assert "2" in text
        assert ">15%" in text


class TestCategoryKeyboardDetails:
    def test_settings_categories_keyboard_filters_query_and_keeps_selected_first(self):
        markup = kb._build_categories_keyboard(
            db=None,
            user_id="user1",
            page=0,
            user_cat_query="phone",
            user_cats_set={"cat-phone"},
            all_cats=[
                {"id": "cat-tv", "name": "Television"},
                {"id": "cat-phone", "name": "Phone"},
                {"id": "cat-case", "name": "Phone Case"},
            ],
        )

        texts = _button_texts(markup)
        assert any("Phone" in text for text in texts)
        assert not any("Television" in text for text in texts)
        assert markup["inline_keyboard"][0][0]["callback_data"] == "cat_toggle:cat-phone"

    def test_settings_categories_keyboard_reports_empty_search_result(self):
        markup = kb._build_categories_keyboard(
            db=None,
            user_id="user1",
            page=99,
            user_cat_query="missing",
            user_cats_set=set(),
            all_cats=[{"id": "cat-tv", "name": "Television"}],
        )

        callbacks = [
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
        ]
        assert "cat_page:noop" in callbacks
        assert "cat_search_clear" in callbacks

    def test_report_categories_keyboard_uses_report_callbacks(self):
        markup = kb._build_report_cats_keyboard(
            db=None,
            user_id="user1",
            page=0,
            state={"cats": ["cat-2"], "cat_query": ""},
            all_cats=[
                {"id": "cat-1", "name": "Alpha"},
                {"id": "cat-2", "name": "Beta"},
            ],
        )

        callbacks = [
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
        ]
        assert "report_cat_all" in callbacks
        assert "report_cat_toggle:cat-2" in callbacks
        assert "report_next:cats" in callbacks


class TestAdminRightsKeyboardDetails:
    def test_admin_rights_users_keyboard_marks_unsaved_plan_and_normalizes_username(self):
        markup = kb._build_admin_rights_users_keyboard(
            users=[{"user_id": "42", "username": "alice", "plan_type": "free"}],
            page=0,
            draft={"42": "pro"},
        )

        first = markup["inline_keyboard"][0][0]
        assert first["callback_data"] == "admin_rights_pick:42"
        assert first["text"].startswith("*@alice | 42 | pro")

    def test_admin_rights_users_keyboard_handles_empty_user_list(self):
        markup = kb._build_admin_rights_users_keyboard(users=[], page=5)

        callbacks = [
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
        ]
        assert "admin_rights_noop" in callbacks
        assert "admin_rights_save" in callbacks

    def test_admin_rights_plan_keyboard_shows_cancel_only_when_dirty(self):
        dirty = kb._build_admin_rights_plan_keyboard(
            {"user_id": "42"},
            selected_plan="pro",
            has_changes=True,
        )
        clean = kb._build_admin_rights_plan_keyboard(
            {"user_id": "42"},
            selected_plan="free",
            has_changes=False,
        )

        dirty_callbacks = [
            button["callback_data"]
            for row in dirty["inline_keyboard"]
            for button in row
        ]
        clean_callbacks = [
            button["callback_data"]
            for row in clean["inline_keyboard"]
            for button in row
        ]
        assert "admin_rights_set:42:pro" in dirty_callbacks
        assert "admin_rights_cancel" in dirty_callbacks
        assert "admin_rights_cancel" not in clean_callbacks
