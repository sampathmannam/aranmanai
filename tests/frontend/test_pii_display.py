"""Tests for U-4: no raw API/case object is ever dumped via st.json().

The audit's original finding was `st.json(c)` in the Cases tab, since fixed
into structured metric/field rendering. While verifying that fix, a SECOND,
undocumented instance of the same anti-pattern was found live in app.py:
`render_ai_assist()`'s "last result" persistence (F-5) called `st.json(last)`
to redisplay a cached AI Assist response -- and those responses routinely
embed complainant names/contact numbers/case facts inside free-text fields
(drafted_fir, structured, narrative, questions). That call has been
replaced with the same structured, per-tab rendering used for a fresh
result (see `_render_ai_result` in app.py). These tests cover both the
originally-fixed Cases tab AND this newly-discovered-and-fixed AI Assist
leak, plus a blanket "no st.json anywhere in the whole app" guard.
"""
from __future__ import annotations

from tests.frontend.conftest import RoutedResponse, navigate_to

_FAKE_CASE = {
    "case_id": "case-0001",
    "fir_no": "FIR/12/2026",
    "status": "open",
    "stage": "investigation",
    "facts_text": "ENCRYPTED_SECRET_FACTS_ABOUT_THE_VICTIM",
    "next_hearing": "2026-09-01",
    "judgment_date": "2026-12-01",
    "court": "District Court",
    "judge": "Hon. X",
    "io_username": "io1",
    "pp_username": "pp1",
    "district": "chennai",
    "risk_score": 0.4,
}


def test_cases_tab_never_calls_st_json(logged_in_app, mock_api):
    """U-4 (original finding): opening a case must not dump the raw dict."""
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(200, {"cases": [_FAKE_CASE], "total": 1, "has_more": False, "page": 1}),
    )

    at = navigate_to(logged_in_app, "Cases")

    assert not at.exception
    assert len(at.json) == 0, "no st.json element should render anywhere on the Cases tab"


def test_cases_tab_does_not_leak_encrypted_facts_text_anywhere_on_the_page(logged_in_app, mock_api):
    """The specific PII the audit called out (facts_text) must not appear in any rendered text."""
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(200, {"cases": [_FAKE_CASE], "total": 1, "has_more": False, "page": 1}),
    )

    at = navigate_to(logged_in_app, "Cases")

    all_text = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.value for t in at.text]
    assert not any("ENCRYPTED_SECRET_FACTS" in v for v in all_text)


def test_cases_tab_shows_structured_fields_instead(logged_in_app, mock_api):
    """The remediation was a structured view (metrics + labeled fields), not just "hide everything"."""
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(200, {"cases": [_FAKE_CASE], "total": 1, "has_more": False, "page": 1}),
    )

    at = navigate_to(logged_in_app, "Cases")

    assert any(m.label == "Status" for m in at.metric)
    assert any("Court:" in md.value for md in at.markdown)
    assert any("Judge:" in md.value for md in at.markdown)


def test_ai_assist_last_result_does_not_call_st_json(logged_in_app, mock_api):
    """Newly-discovered leak (fixed): F-5's cached 'last result' replay must not be raw JSON."""
    mock_api.set(
        "/api/v1/ai/chargesheet-draft",
        RoutedResponse(
            200,
            {
                "drafted_chargesheet": "Charges against Ramesh, contact 9876543210.",
                "charges_applied": ["BNS 302"],
            },
        ),
    )
    at = navigate_to(logged_in_app, "AI Assist")
    at.selectbox[0].set_value("Chargesheet Draft").run()
    next(ti for ti in at.text_input if ti.label == "Case ID").input("case-0001").run()
    next(ta for ta in at.text_area if ta.label.startswith("Charges")).input("BNS 302 murder").run()
    at.button(key="FormSubmitter:chargesheet-Draft chargesheet").click().run()
    assert len(at.json) == 0, "the freshly-submitted result must not render via st.json either"

    # Switch away and back -- this is the F-5 "last result" replay path.
    at.selectbox[0].set_value("Risk Score").run()
    at.selectbox[0].set_value("Chargesheet Draft").run()

    assert not at.exception
    assert any("last result" in i.value.lower() for i in at.info)
    assert len(at.json) == 0, "the replayed last-result must not be a raw st.json() dump"
    assert any(
        ta.label == "Drafted chargesheet" and "Ramesh" in ta.value for ta in at.text_area
    ), "the cached result should still render its structured field"


def test_no_st_json_element_ever_renders_across_the_whole_app(logged_in_app, mock_api):
    """Blanket guard: this app should never use st.json() for user-facing display, anywhere."""
    mock_api.set(
        "/api/v1/kishore/cases",
        RoutedResponse(200, {"cases": [_FAKE_CASE], "total": 1, "has_more": False, "page": 1}),
    )
    pages = ["Today", "CMC Morning", "Cases", "Witnesses", "SP Dashboard", "AI Assist"]
    at = logged_in_app
    for page in pages:
        at = navigate_to(at, page)
        assert len(at.json) == 0, f"st.json() rendered on the {page!r} page"
