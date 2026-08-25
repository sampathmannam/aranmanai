"""Tests for the login flow in app.py (F-12 whitespace validation, success, failure)."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tests.frontend.conftest import FAKE_LOGIN_RESPONSE, RoutedResponse

LOGIN_BUTTON_KEY = "FormSubmitter:login-Sign in"


def _submit_login(at: AppTest, username: str, password: str) -> AppTest:
    at.text_input[0].input(username).run()
    at.text_input[1].input(password).run()
    at.button(key=LOGIN_BUTTON_KEY).click().run()
    return at


def test_whitespace_only_username_is_rejected(app_path, mock_api):
    """F-12: a whitespace-only username must be rejected client-side, before any API call."""
    at = AppTest.from_file(app_path)
    at.run()

    _submit_login(at, "   ", "irrelevant-password")

    assert not mock_api.mock.called, "the API must not be called for a whitespace-only username"
    assert "token" not in at.session_state
    assert any(
        "cannot be empty or whitespace" in e.value.lower() for e in at.error
    ), f"expected a whitespace error, got: {[e.value for e in at.error]}"


def test_empty_username_is_rejected(app_path, mock_api):
    """F-12: an outright empty username is rejected the same way as whitespace."""
    at = AppTest.from_file(app_path)
    at.run()

    _submit_login(at, "", "irrelevant-password")

    assert not mock_api.mock.called
    assert "token" not in at.session_state
    assert any("cannot be empty or whitespace" in e.value.lower() for e in at.error)


def test_valid_credentials_log_the_user_in_and_reach_main_page(app_path, mock_api):
    """A successful (mocked) login stores the token/user and renders past the login form."""
    at = AppTest.from_file(app_path)
    at.run()
    assert len(at.title) == 1, "expected to start on the login page"

    _submit_login(at, "sp_user", "correct-password")

    assert at.session_state["token"] == FAKE_LOGIN_RESPONSE["access_token"]
    assert at.session_state["user"]["username"] == FAKE_LOGIN_RESPONSE["username"]
    assert at.session_state["user"]["role"] == FAKE_LOGIN_RESPONSE["role"]
    # main_page() renders past the login form: the sidebar nav + a page header
    # replace the bare login title/subheader.
    assert len(at.sidebar.radio) == 1
    assert not at.exception


def test_username_is_trimmed_before_submission(app_path, mock_api):
    """F-12: surrounding whitespace on an otherwise valid username is stripped, not rejected."""
    at = AppTest.from_file(app_path)
    at.run()

    _submit_login(at, "  sp_user  ", "correct-password")

    assert at.session_state["token"] == FAKE_LOGIN_RESPONSE["access_token"]
    # main_page() renders "Today" after login too, so find the login POST
    # specifically among all recorded calls rather than assuming it's last.
    login_calls = [
        call for call in mock_api.mock.call_args_list if "/api/v1/auth/login" in call.args[1]
    ]
    assert len(login_calls) == 1
    sent_body = login_calls[0].kwargs.get("json", {})
    assert sent_body["username"] == "sp_user"


def test_invalid_credentials_shows_error_and_does_not_log_in(app_path, mock_api):
    """A 401 from the login endpoint must surface an error and leave the user logged out.

    Empirically verified: app.py's login() calls the shared `_api_call`
    helper, whose generic 401 branch (session-expired message + rerun)
    fires before login-specific error text would -- so the real, observed
    behavior is a "session expired" style error, not a bespoke "invalid
    credentials" string. This test asserts on that actual behavior.
    """
    mock_api.set("/api/v1/auth/login", RoutedResponse(401, {"detail": "Invalid credentials"}))

    at = AppTest.from_file(app_path)
    at.run()

    _submit_login(at, "sp_user", "wrong-password")

    assert "token" not in at.session_state
    assert len(at.error) >= 1, "expected an error message on failed login"
    assert not at.exception


def test_connection_error_shows_api_unreachable_message(app_path, mock_api, mocker):
    """If the API can't be reached at all, a clear connection error is shown (not a stack trace)."""
    import requests as real_requests

    mock_api.mock.side_effect = real_requests.exceptions.ConnectionError("refused")

    at = AppTest.from_file(app_path)
    at.run()

    _submit_login(at, "sp_user", "correct-password")

    assert "token" not in at.session_state
    assert any("cannot reach the api" in e.value.lower() for e in at.error)
    assert not at.exception
