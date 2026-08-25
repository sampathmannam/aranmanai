"""Shared fixtures for Streamlit frontend tests (streamlit.testing.v1.AppTest).

These tests run the real app.py / voice_tab.py scripts headlessly via
AppTest. They never hit a live API server: app.py's `_api_call` routes
every HTTP call through `requests.request(method, url, ...)`, so we patch
`aranmanai.frontend.app.requests.request` with a URL-keyed fake. voice_tab.py
calls `requests.get`/`requests.post` directly (a separate import in that
module), so it is patched separately.

Response payloads below mirror the real Pydantic response models in
src/aranmanai/api/v1/*.py (TokenResponse, CmcDailyViewResponse,
ComplaintIntakeResponse, etc.) rather than invented shapes.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "src" / "aranmanai" / "frontend"
APP_PATH = str(FRONTEND_DIR / "app.py")

# ──────────────────────────────────────────────────────────────
# Canonical fake API responses, matching the real response models.
# ──────────────────────────────────────────────────────────────

FAKE_LOGIN_RESPONSE = {
    # aranmanai.api.v1.auth.TokenResponse
    "access_token": "fake.header.payload",
    "token_type": "bearer",
    "role": "sp",
    "user_id": "user-0001",
    "district": "chennai",
    "username": "sp_user",
}

FAKE_USER = {
    "username": FAKE_LOGIN_RESPONSE["username"],
    "role": FAKE_LOGIN_RESPONSE["role"],
    "district": FAKE_LOGIN_RESPONSE["district"],
    "user_id": FAKE_LOGIN_RESPONSE["user_id"],
    "access_token": FAKE_LOGIN_RESPONSE["access_token"],
    "token_type": FAKE_LOGIN_RESPONSE["token_type"],
}

FAKE_TODAY_HEARINGS: list[dict] = []  # empty -> render_today() shows "No hearings today."

FAKE_CMC_DAILY_VIEW = {
    # aranmanai.api.v1.cmc.CmcDailyViewResponse
    "date": "2026-08-25",
    "district": "chennai",
    "n_hearings": 1,
    "n_actions_pending": 0,
    "n_actions_overdue": 0,
    "n_actions_answered_yesterday": 0,
    "n_escalations_open": 0,
    "n_cases_unreviewed": 0,
    "hearings": [
        {
            "hearing_id": "hearing-0001",
            "case_id": "case-0001",
            "fir_no": "FIR/12/2026",
            "stage": "trial",
            "sp_reviewed": "pending",
            "date": "2026-08-25",
            "pp_present": True,
            "accused_present": True,
        }
    ],
    "overdue_actions": [],
    "open_escalations": [],
    "top_priority": [],
    "sp_signoff_status": {},
}

FAKE_CMC_MEETING_RESPONSE = {
    # aranmanai.api.v1.cmc.CmcMeetingResponse
    "meeting_id": "meeting-0001",
    "district": "chennai",
    "meeting_date": "2026-08-25T10:00:00",
    "held_by": "user-0001",
    "attendees": [],
    "n_actions": 0,
}

FAKE_SP_REVIEW_RESPONSE = {
    # POST /cmc/sp-review handler return shape (dict, not a pydantic model)
    "review_id": "review-0001",
    "case_id": "case-0001",
    "review_date": "2026-08-25",
    "status": "reviewed",
    "action_count": 0,
    "overdue_action_count": 0,
}

FAKE_VOICE_CAPABILITIES = {
    "stt_model": "small",
    "stt_device": "cpu",
    "tts_available": True,
    "max_audio_size_mb": 25,
}

FAKE_COMPLAINT_INTAKE_RESPONSE = {
    # aranmanai.ai.services.complaint_intake.ComplaintIntakeResponse
    "draft_id": "draft-0001",
    "structured": "Structured complaint text.",
    "likely_sections_bns": ["BNS 351"],
    "registerable": True,
    "created_at": "2026-08-25T10:00:00",
}


class RoutedResponse:
    """A minimal stand-in for requests.Response, routed by URL substring."""

    def __init__(self, status_code: int, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or (str(payload) if payload is not None else "")
        self.content = b"{}" if payload is not None else b""

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"raise_for_status called on {self.status_code} response")


def build_api_router(
    mocker, overrides: dict[str, RoutedResponse | Callable[..., RoutedResponse]] | None = None
) -> Callable[..., RoutedResponse]:
    """Build a `requests.request(method, url, ...)`-shaped fake, routed by URL substring.

    `overrides` maps a URL substring to either a RoutedResponse or a
    zero/one-arg callable returning one (called with the kwargs passed to
    the request), letting a test override just the endpoints it cares
    about while sensible defaults (login, today, cmc daily-view) keep the
    rest of the app from crashing when it renders underneath.
    """
    default_routes: dict[str, RoutedResponse] = {
        "/api/v1/auth/login": RoutedResponse(200, FAKE_LOGIN_RESPONSE),
        "/api/v1/cms/calendar/today": RoutedResponse(200, FAKE_TODAY_HEARINGS),
        "/api/v1/cmc/daily-view": RoutedResponse(200, FAKE_CMC_DAILY_VIEW),
        "/api/v1/cmc/meeting": RoutedResponse(201, FAKE_CMC_MEETING_RESPONSE),
        "/api/v1/cmc/sp-review": RoutedResponse(201, FAKE_SP_REVIEW_RESPONSE),
    }
    routes = {**default_routes, **(overrides or {})}

    def _route(method: str, url: str, **kwargs) -> RoutedResponse:
        for substr, response in routes.items():
            if substr in url:
                return response(**kwargs) if callable(response) else response
        raise AssertionError(f"No mocked route for {method.upper()} {url}")

    return _route


@pytest.fixture
def app_path() -> str:
    """Absolute path to the real app.py under test."""
    return APP_PATH


@pytest.fixture
def mock_api(mocker):
    """Patch aranmanai.frontend.app.requests.request with a URL-routed fake.

    Returns a helper object exposing `.set(url_substring, response)` so
    individual tests can override/add routes, and `.mock` (the underlying
    MagicMock) to assert on call args.
    """

    class Router:
        def __init__(self) -> None:
            self.overrides: dict[str, Any] = {}
            self.mock = mocker.patch(
                "aranmanai.frontend.app.requests.request",
                side_effect=lambda method, url, **kw: build_api_router(mocker, self.overrides)(
                    method, url, **kw
                ),
            )

        def set(self, url_substring: str, response: RoutedResponse | Callable[..., RoutedResponse]) -> None:
            self.overrides[url_substring] = response

    return Router()


@pytest.fixture
def mock_voice_api(mocker):
    """Patch aranmanai.frontend.voice_tab's `requests.get`/`requests.post`.

    voice_tab.py imports `requests` at module scope and calls
    `requests.get(...)` / `requests.post(...)` directly (not through
    app.py's `_api_call`), so it needs its own patch target.
    """
    get_mock = mocker.patch(
        "aranmanai.frontend.voice_tab.requests.get",
        return_value=RoutedResponse(200, FAKE_VOICE_CAPABILITIES),
    )
    post_mock = mocker.patch(
        "aranmanai.frontend.voice_tab.requests.post",
        return_value=RoutedResponse(200, FAKE_COMPLAINT_INTAKE_RESPONSE),
    )
    return get_mock, post_mock


@pytest.fixture
def logged_in_app(app_path, mock_api, mock_voice_api) -> Iterator[AppTest]:
    """An AppTest instance pre-seeded as already logged in, run once.

    Session state values read on the very first script execution (token,
    user) must be set before the first `.run()` call -- AppTest has no
    live widget interaction until then, so this is the documented way to
    start a test already "inside" the app rather than at the login form.
    """
    at = AppTest.from_file(app_path)
    at.session_state["token"] = FAKE_LOGIN_RESPONSE["access_token"]
    at.session_state["user"] = dict(FAKE_USER)
    at.run()
    yield at


def navigate_to(at: AppTest, page_name: str) -> AppTest:
    """Select a sidebar page and rerun, mirroring a user clicking a nav radio option."""
    at.sidebar.radio[0].set_value(page_name).run()
    return at
