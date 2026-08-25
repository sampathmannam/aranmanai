"""Tests for the U-8 sidebar recovery: the "Show Menu" button flip-flop."""
from __future__ import annotations


def test_sidebar_state_defaults_to_unset(logged_in_app):
    """Before any click, `_sidebar_state` has never been written to session_state."""
    assert "_sidebar_state" not in logged_in_app.session_state


def test_show_menu_click_sets_sidebar_state_to_expanded(logged_in_app, mock_api):
    """First click: unset -> "expanded" (the `current == "expanded"` branch is False)."""
    logged_in_app.button(key="_show_menu_btn").click().run()

    assert logged_in_app.session_state["_sidebar_state"] == "expanded"


def test_second_show_menu_click_flips_to_auto(logged_in_app, mock_api):
    """Second click: "expanded" -> "auto".

    This is the crux of the U-8 fix: Streamlit only recomputes the
    sidebar's collapsed/expanded state when `initial_sidebar_state`'s
    *value* changes between reruns, so sending "expanded" twice in a row
    would be a no-op the second time. Flip-flopping to "auto" guarantees
    a real value change on every click.
    """
    at = logged_in_app
    at.button(key="_show_menu_btn").click().run()
    assert at.session_state["_sidebar_state"] == "expanded"

    at.button(key="_show_menu_btn").click().run()

    assert at.session_state["_sidebar_state"] == "auto"


def test_third_show_menu_click_flips_back_to_expanded(logged_in_app, mock_api):
    """The flip-flop keeps alternating on every subsequent click, not just once."""
    at = logged_in_app
    at.button(key="_show_menu_btn").click().run()
    at.button(key="_show_menu_btn").click().run()
    assert at.session_state["_sidebar_state"] == "auto"

    at.button(key="_show_menu_btn").click().run()

    assert at.session_state["_sidebar_state"] == "expanded"


def test_show_menu_button_is_present_on_every_authenticated_page(logged_in_app, mock_api):
    """The recovery button must be reachable regardless of which page is selected."""
    from tests.frontend.conftest import navigate_to

    navigate_to(logged_in_app, "CMC Morning")

    assert logged_in_app.button(key="_show_menu_btn") is not None
