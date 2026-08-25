"""Tests for F-8: rapid sidebar tab-switching must not re-fire redundant API calls.

The audit's repro was "5 clicks in 2 seconds -> 5 API calls, no debouncing."
app.py's `api_get_cached()` reuses the last response for a GET path if it
was fetched within `_GET_DEBOUNCE_SEC` (2s) -- flicking back to a tab you
just left re-renders instantly from cache instead of re-hitting the API.
`_api_call` clears that cache on every mutating request specifically so
this debounce can never mask the deliberate refresh-after-mutation
behavior already covered by W-5/S-1/S-2 in test_cmc_state_refresh.py.
"""
from __future__ import annotations

from tests.frontend.conftest import navigate_to


def _calls_to(mock_api, path_substring: str) -> list:
    return [c for c in mock_api.mock.call_args_list if path_substring in c.args[1]]


def test_revisiting_a_tab_within_the_debounce_window_reuses_the_cached_response(
    logged_in_app, mock_api
):
    """Today -> CMC Morning -> Today in rapid succession must fetch Today only once."""
    at = navigate_to(logged_in_app, "CMC Morning")
    at = navigate_to(at, "Today")

    assert not at.exception
    today_calls = _calls_to(mock_api, "/api/v1/cms/calendar/today")
    # logged_in_app's initial .run() already lands on "Today" once; the
    # explicit revisit above must not add a second call.
    assert len(today_calls) == 1, f"expected exactly 1 debounced fetch, got {len(today_calls)}"


def test_revisiting_cmc_morning_within_the_window_also_reuses_the_cache(logged_in_app, mock_api):
    at = navigate_to(logged_in_app, "CMC Morning")
    at = navigate_to(at, "Witnesses")
    at = navigate_to(at, "CMC Morning")

    assert not at.exception
    daily_view_calls = _calls_to(mock_api, "/api/v1/cmc/daily-view")
    assert len(daily_view_calls) == 1


def test_a_mutation_invalidates_the_cache_so_the_post_action_refresh_is_never_stale(
    logged_in_app, mock_api
):
    """The debounce must never defeat W-5/S-1/S-2's rerun-after-mutation refresh."""
    at = navigate_to(logged_in_app, "CMC Morning")
    daily_view_calls_before = _calls_to(mock_api, "/api/v1/cmc/daily-view")
    assert len(daily_view_calls_before) == 1

    at.button(key="sp_rev_hearing-0001").click().run()

    assert not at.exception
    daily_view_calls_after = _calls_to(mock_api, "/api/v1/cmc/daily-view")
    assert len(daily_view_calls_after) == 2, (
        "the rerun after 'Mark reviewed' must issue a real fetch, not reuse the pre-mutation cache"
    )


def test_different_case_pages_are_not_conflated_by_the_cache(logged_in_app, mock_api):
    """The cache key includes the query string, so distinct pages never share stale data."""
    from tests.frontend.conftest import RoutedResponse

    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(
            200,
            {
                "cases": [{"case_id": "c1", "fir_no": "F1", "status": "open", "stage": "investigation"}],
                "total": 20,
                "has_more": True,
                "page": 1,
            },
        ),
    )
    at = navigate_to(logged_in_app, "Cases")

    at.button(key="cases_next").click().run()

    assert not at.exception
    cases_calls = _calls_to(mock_api, "/api/v1/kishore/cases")
    urls = [c.args[1] for c in cases_calls]
    assert any("page=1" in u for u in urls)
    assert any("page=2" in u for u in urls), "switching page must not be served from the page-1 cache entry"
