"""Tests for W-1/W-2: the AI Assist service tabs must be real forms, not
"form coming" / "Full form handling TBD" dead placeholders.

The audit's original code sample for W-1 (FIR Draft) had 9 unwired
`st.text_input`/`st.text_area` calls and a submit handler that only showed
`st.info("Fill the form and click Draft FIR. Full form handling TBD.")`.
W-2 covered the same "form coming" placeholder for Chargesheet Draft,
Investigation Recommendations, and Cross-Exam Prep. These tests assert the
actual widgets a real, wired form needs are present for every one of the
4 previously-dead tabs, and that no residual placeholder text survives.
"""
from __future__ import annotations

from tests.frontend.conftest import RoutedResponse, navigate_to

PLACEHOLDER_PHRASES = ("form coming", "tbd", "handling tbd")


def _select_ai_assist_tab(at, tab_name: str):
    at = navigate_to(at, "AI Assist")
    at.selectbox[0].set_value(tab_name).run()
    return at


def _all_text_values(at) -> list[str]:
    """Every user-visible text-bearing element's value, lowercased."""
    values = []
    for group in (at.info, at.warning, at.markdown, at.caption, at.text):
        values.extend(v.value.lower() for v in group)
    return values


def test_fir_draft_renders_all_nine_fields_and_a_submit_button(logged_in_app, mock_api):
    """W-1: FIR Draft must expose real, submittable form fields."""
    at = _select_ai_assist_tab(logged_in_app, "FIR Draft")

    assert not at.exception
    labels = {ti.label for ti in at.text_input} | {ta.label for ta in at.text_area}
    expected = {
        "FIR No.", "Police Station", "District", "Complainant name",
        "Complainant contact", "Incident date/time", "Location", "Facts",
        "IO name", "BNS sections (comma-separated)",
    }
    assert expected <= labels, f"missing fields: {expected - labels}"
    assert any(b.label == "Draft FIR" for b in at.button)
    assert not any(phrase in v for v in _all_text_values(at) for phrase in PLACEHOLDER_PHRASES)


def test_chargesheet_draft_renders_real_fields_not_a_placeholder(logged_in_app, mock_api):
    """W-2: Chargesheet Draft is a real form, not an st.info() dead end."""
    at = _select_ai_assist_tab(logged_in_app, "Chargesheet Draft")

    assert not at.exception
    labels = {ti.label for ti in at.text_input} | {ta.label for ta in at.text_area}
    assert "Case ID" in labels
    assert any("charges" in lbl.lower() for lbl in labels)
    assert any("evidence" in lbl.lower() for lbl in labels)
    assert any("witnesses" in lbl.lower() for lbl in labels)
    assert any(b.label == "Draft chargesheet" for b in at.button)
    assert not any(phrase in v for v in _all_text_values(at) for phrase in PLACEHOLDER_PHRASES)


def test_investigation_recommendations_renders_real_fields_not_a_placeholder(
    logged_in_app, mock_api
):
    """W-2: Investigation Recommendations is a real form, not an st.info() dead end."""
    at = _select_ai_assist_tab(logged_in_app, "Investigation Recommendations")

    assert not at.exception
    labels = {ti.label for ti in at.text_input} | {ta.label for ta in at.text_area}
    assert "Case ID" in labels
    assert any("case facts" in lbl.lower() for lbl in labels)
    assert any(sb.label == "Focus area" for sb in at.selectbox)
    assert any(b.label == "Get recommendations" for b in at.button)
    assert not any(phrase in v for v in _all_text_values(at) for phrase in PLACEHOLDER_PHRASES)


def test_cross_exam_prep_renders_real_fields_not_a_placeholder(logged_in_app, mock_api):
    """W-2: Cross-Exam Prep is a real form, not an st.info() dead end."""
    at = _select_ai_assist_tab(logged_in_app, "Cross-Exam Prep")

    assert not at.exception
    labels = {ti.label for ti in at.text_input} | {ta.label for ta in at.text_area}
    assert "Witness ID" in labels
    assert any("case facts" in lbl.lower() for lbl in labels)
    assert any("witness statement" in lbl.lower() for lbl in labels)
    assert any(b.label == "Generate cross-exam questions" for b in at.button)
    assert not any(phrase in v for v in _all_text_values(at) for phrase in PLACEHOLDER_PHRASES)


def test_chargesheet_draft_submits_the_typed_fields_to_the_api(logged_in_app, mock_api):
    """The Chargesheet Draft form must actually be wired end-to-end, not just present."""
    at = _select_ai_assist_tab(logged_in_app, "Chargesheet Draft")
    mock_api.set(
        "/api/v1/ai/chargesheet-draft",
        RoutedResponse(200, {"drafted_chargesheet": "Chargesheet text.", "charges_applied": ["BNS 302"]}),
    )

    next(ti for ti in at.text_input if ti.label == "Case ID").input("case-0001").run()
    next(
        ta for ta in at.text_area if ta.label.startswith("Charges")
    ).input("BNS 302 murder").run()
    at.button(key="FormSubmitter:chargesheet-Draft chargesheet").click().run()

    assert not at.exception
    calls = [
        c for c in mock_api.mock.call_args_list if "/api/v1/ai/chargesheet-draft" in c.args[1]
    ]
    assert len(calls) == 1
    sent = calls[0].kwargs.get("json", {})
    assert sent["case_id"] == "case-0001"
    assert sent["charges"] == ["BNS 302 murder"]
    assert any(ta.label == "Drafted chargesheet" and "Chargesheet text." in ta.value for ta in at.text_area)
