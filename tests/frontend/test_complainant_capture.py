"""Tests for the F-10 Complainant Details capture step in voice_tab.py.

These tests bypass the actual audio-upload/transcribe flow (st.file_uploader
cannot be driven through AppTest) by pre-seeding
`_pending_complaint_transcript` / `_pending_complaint_language` directly in
session_state, exactly as they would be after a real transcription
succeeded (see voice_tab.py's `render_voice_tab`, which stashes these same
two keys once `generate_clicked and transcript_text` is true).
"""
from __future__ import annotations

from tests.frontend.conftest import navigate_to

SUBMIT_BUTTON_KEY = "submit_complaint_btn"
ACK_CHECKBOX_KEY = "complainant_empty_ack"


def _seed_transcript(at, text: str, language: str = "en") -> None:
    at.session_state["_pending_complaint_transcript"] = text
    at.session_state["_pending_complaint_language"] = language


def test_complainant_details_section_renders_with_expected_labels(logged_in_app, mock_api):
    """Once a transcript is pending, the Complainant Details section appears."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "Sir I want to file a complaint about a theft")
    at.run()

    assert any("Complainant Details" in s.value for s in at.subheader)
    labels = [ti.label for ti in at.text_input]
    assert "Complainant name" in labels
    assert "Contact number" in labels


def test_phone_number_is_prefilled_from_transcript(logged_in_app, mock_api):
    """F-10: the regex heuristic pre-fills a detected 10-digit mobile number."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "Sir my number is 98765 43210, please note it down")
    at.run()

    contact_input = next(ti for ti in at.text_input if ti.label == "Contact number")
    assert contact_input.value == "9876543210"


def test_phone_number_with_plus91_prefix_is_prefilled(logged_in_app, mock_api):
    """The heuristic also handles a +91 country-code prefix."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "you can reach me at +91-98765-43210 any time")
    at.run()

    contact_input = next(ti for ti in at.text_input if ti.label == "Contact number")
    assert contact_input.value == "9876543210"


def test_no_phone_number_in_transcript_leaves_contact_blank(logged_in_app, mock_api):
    """When the heuristic finds nothing, the contact field is left for manual entry."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "no phone or name mentioned here at all")
    at.run()

    contact_input = next(ti for ti in at.text_input if ti.label == "Contact number")
    assert contact_input.value == ""


def test_name_field_is_never_auto_prefilled(logged_in_app, mock_api):
    """No NER exists in this codebase for names -- the name field always starts blank."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "my name is Ramesh Kumar and my number is 98765 43210")
    at.run()

    name_input = next(ti for ti in at.text_input if ti.label == "Complainant name")
    assert name_input.value == ""


def test_submit_disabled_when_both_fields_empty_without_acknowledgment(logged_in_app, mock_api):
    """F-10: with no complainant details and no ack, submission is blocked."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "no phone or name mentioned here at all")
    at.run()

    assert at.button(key=SUBMIT_BUTTON_KEY).disabled is True
    assert any("Abhaya" in w.value for w in at.warning)
    ack_checkboxes = [c for c in at.checkbox if c.key == ACK_CHECKBOX_KEY]
    assert len(ack_checkboxes) == 1


def test_submit_enabled_once_acknowledgment_checked(logged_in_app, mock_api):
    """Checking the deliberate-submission acknowledgment unblocks the submit button."""
    at = navigate_to(logged_in_app, "Voice")
    _seed_transcript(at, "no phone or name mentioned here at all")
    at.run()
    assert at.button(key=SUBMIT_BUTTON_KEY).disabled is True

    at.checkbox(key=ACK_CHECKBOX_KEY).check().run()

    assert at.button(key=SUBMIT_BUTTON_KEY).disabled is False


def test_submit_enabled_when_contact_detected_even_without_ack_checkbox(logged_in_app, mock_api):
    """When at least one field is populated (e.g. a detected phone), no ack is required."""
    at = navigate_to(logged_in_app, "Voice")

    _seed_transcript(at, "call me at 98765 43210 please")
    at.run()

    assert not any(c.key == ACK_CHECKBOX_KEY for c in at.checkbox), (
        "the acknowledgment checkbox should only appear when both fields are empty"
    )
    assert at.button(key=SUBMIT_BUTTON_KEY).disabled is False


def test_submit_enabled_when_only_name_is_manually_entered(logged_in_app, mock_api):
    """Manually filling just the name field (no detected phone) also unblocks submit."""
    at = navigate_to(logged_in_app, "Voice")
    _seed_transcript(at, "no phone or name mentioned here at all")
    at.run()
    assert at.button(key=SUBMIT_BUTTON_KEY).disabled is True

    name_input = next(ti for ti in at.text_input if ti.label == "Complainant name")
    name_input.input("Ramesh Kumar").run()

    assert at.button(key=SUBMIT_BUTTON_KEY).disabled is False


def test_successful_submit_calls_complaint_intake_with_entered_details(
    logged_in_app, mock_api, mock_voice_api
):
    """Submitting posts the transcript + entered complainant details to complaint-intake."""
    _, post_mock = mock_voice_api
    at = navigate_to(logged_in_app, "Voice")
    _seed_transcript(at, "call me at 98765 43210 please", language="ta")
    at.run()

    at.button(key=SUBMIT_BUTTON_KEY).click().run()

    assert post_mock.called
    call = post_mock.call_args
    assert "/api/v1/ai/complaint-intake" in call.args[0]
    sent = call.kwargs["json"]
    assert sent["raw_complaint"] == "call me at 98765 43210 please"
    assert sent["complainant_contact"] == "9876543210"
    assert sent["language"] == "ta"


def test_successful_submit_clears_the_pending_transcript(logged_in_app, mock_api, mock_voice_api):
    """After a successful submit, the pending-complaint state is cleared so the form doesn't linger."""
    at = navigate_to(logged_in_app, "Voice")
    _seed_transcript(at, "call me at 98765 43210 please")
    at.run()

    at.button(key=SUBMIT_BUTTON_KEY).click().run()

    assert "_pending_complaint_transcript" not in at.session_state
    assert "_pending_complaint_language" not in at.session_state
