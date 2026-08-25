"""Tests for U-2: a very long FIR number/name must not break expander layout.

The audit's repro was a 200-char FIR number (`"FIR/" * 30`) overflowing the
expander header. app.py's `_short()` helper truncates the header text with
an ellipsis; `_full_if_truncated()` (added while verifying this finding)
additionally surfaces the untruncated value inside the expanded body, so a
malformed/adversarial value can't hide information as a side effect of the
truncation that fixed the layout bug.
"""
from __future__ import annotations

from tests.frontend.conftest import RoutedResponse, navigate_to

_LONG_FIR = "FIR/" * 60  # 240 chars


def test_long_fir_number_is_truncated_in_the_cases_expander_header(logged_in_app, mock_api):
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(
            200,
            {
                "cases": [{"case_id": "case-0001", "fir_no": _LONG_FIR, "status": "open", "stage": "investigation"}],
                "total": 1,
                "has_more": False,
                "page": 1,
            },
        ),
    )

    at = navigate_to(logged_in_app, "Cases")

    assert not at.exception
    assert len(at.expander) == 1
    header = at.expander[0].label
    assert len(header) < len(_LONG_FIR), "the header must be shorter than the raw 240-char FIR number"
    assert "…" in header


def test_long_fir_number_is_still_visible_in_full_inside_the_expander_body(logged_in_app, mock_api):
    """Truncating the header must not make the full value unrecoverable."""
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(
            200,
            {
                "cases": [{"case_id": "case-0001", "fir_no": _LONG_FIR, "status": "open", "stage": "investigation"}],
                "total": 1,
                "has_more": False,
                "page": 1,
            },
        ),
    )

    at = navigate_to(logged_in_app, "Cases")

    assert any(_LONG_FIR in c.value for c in at.caption), (
        "the full, untruncated FIR number should be shown somewhere in the expanded body"
    )


def test_short_fir_number_gets_no_full_value_caption(logged_in_app, mock_api):
    """A normal-length FIR number shouldn't get a redundant 'Full FIR No' caption."""
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(
            200,
            {
                "cases": [{"case_id": "case-0001", "fir_no": "FIR/12/2026", "status": "open", "stage": "investigation"}],
                "total": 1,
                "has_more": False,
                "page": 1,
            },
        ),
    )

    at = navigate_to(logged_in_app, "Cases")

    assert not any("Full FIR No" in c.value for c in at.caption)


def test_long_fir_number_is_truncated_on_the_cmc_morning_hearings_list(logged_in_app, mock_api):
    view = {
        "date": "2026-08-25", "district": "chennai", "n_hearings": 1, "n_actions_pending": 0,
        "n_actions_overdue": 0, "n_actions_answered_yesterday": 0, "n_escalations_open": 0,
        "n_cases_unreviewed": 0,
        "hearings": [
            {
                "hearing_id": "hearing-0001", "case_id": "case-0001", "fir_no": _LONG_FIR,
                "stage": "trial", "sp_reviewed": "pending", "date": "2026-08-25",
                "pp_present": True, "accused_present": True,
            }
        ],
        "overdue_actions": [], "open_escalations": [], "top_priority": [], "sp_signoff_status": {},
    }
    mock_api.set("/api/v1/cmc/daily-view", RoutedResponse(200, view))

    at = navigate_to(logged_in_app, "CMC Morning")

    assert not at.exception
    hearing_expanders = [e for e in at.expander if "trial" in e.label]
    assert len(hearing_expanders) == 1
    assert len(hearing_expanders[0].label) < len(_LONG_FIR)
    assert any(_LONG_FIR in c.value for c in at.caption)
