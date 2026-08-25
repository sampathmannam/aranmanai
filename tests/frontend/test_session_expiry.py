"""Tests for S-8 (JWT expiry auto-logout) and S-6 (401 -> logout redirect).

Neither of these had regression coverage even though both are implemented
in app.py: `_jwt_exp`/`_check_token_validity` (S-8) decode the JWT's `exp`
claim and clear the session before the page ever renders with a dead
token; `_api_call`'s 401 branch (S-6) does the same the moment any API
call comes back unauthorized mid-session.
"""
from __future__ import annotations

import base64
import json
import time

from streamlit.testing.v1 import AppTest

from tests.frontend.conftest import FAKE_USER, RoutedResponse, navigate_to


def _make_jwt(exp: int) -> str:
    """A minimal, real-shaped JWT with only the `exp` claim populated.

    `_jwt_exp` in app.py only ever reads the middle (payload) segment, so
    the header and signature segments just need to exist as dot-separated
    parts -- their content is never inspected.
    """
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.sig"


def test_expired_token_bounces_straight_to_the_login_page(app_path, mock_api):
    """S-8: a token whose `exp` has already passed never gets a chance to render a page."""
    expired = _make_jwt(int(time.time()) - 3600)
    at = AppTest.from_file(app_path)
    at.session_state["token"] = expired
    at.session_state["user"] = dict(FAKE_USER)

    at.run()

    assert not at.exception
    assert "token" not in at.session_state
    assert "user" not in at.session_state
    assert any("Aranmanai" in t.value for t in at.title), "expected to land back on the login page"


def test_not_yet_expired_token_is_left_alone(app_path, mock_api):
    """S-8 must not be a hair-trigger: a token still valid for another hour must not be logged out."""
    valid = _make_jwt(int(time.time()) + 3600)
    at = AppTest.from_file(app_path)
    at.session_state["token"] = valid
    at.session_state["user"] = dict(FAKE_USER)

    at.run()

    assert not at.exception
    assert at.session_state["token"] == valid
    assert len(at.sidebar.radio) == 1, "expected to be on the main app, not bounced to login"


def test_unparseable_token_does_not_crash_the_app(app_path, mock_api):
    """A malformed token (e.g. the test fixtures' 'fake.header.payload') must fail safe.

    `_jwt_exp` catches decode errors and returns None; `_check_token_validity`
    treats that as "can't tell, so don't force a logout" rather than crashing.
    """
    at = AppTest.from_file(app_path)
    at.session_state["token"] = "not-a-real-jwt"
    at.session_state["user"] = dict(FAKE_USER)

    at.run()

    assert not at.exception
    assert "token" in at.session_state
    assert at.session_state["token"] == "not-a-real-jwt"


def test_a_401_mid_session_clears_the_session_and_shows_the_expiry_message(logged_in_app, mock_api):
    """S-6: an API call returning 401 after login must trigger the centralized logout path."""
    mock_api.set(
        "/api/v1/witnesses",
        RoutedResponse(401, {"detail": "Missing or malformed Authorization header"}),
    )

    at = navigate_to(logged_in_app, "Witnesses")

    assert not at.exception
    assert "token" not in at.session_state
    assert "user" not in at.session_state
    assert any("session has expired" in e.value.lower() for e in at.error)


def test_after_a_401_logout_the_login_page_is_reachable_again(logged_in_app, mock_api):
    """The 401 path must actually land the user somewhere usable, not a blank/broken page."""
    mock_api.set(
        "/api/v1/witnesses",
        RoutedResponse(401, {"detail": "Missing or malformed Authorization header"}),
    )

    at = navigate_to(logged_in_app, "Witnesses")

    # Verified empirically: AppTest's element-reconciliation across an
    # internal st.rerun() restart can retain a stray sidebar title element
    # from the interrupted pre-401 pass alongside the fresh login page's
    # own title, so this asserts the durable outcome (the login title is
    # present, a text_input for credentials exists) rather than an exact
    # element count -- mirroring the same documented characteristic in
    # test_cmc_state_refresh.py's test_open_meeting_triggers_rerun_with_no_errors.
    assert any("Aranmanai" in t.value for t in at.title)
    assert len(at.text_input) >= 2, "expected the login form's username/password inputs"
