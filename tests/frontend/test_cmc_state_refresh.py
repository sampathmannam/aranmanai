"""Tests for the CMC Morning view: W-5/S-1/S-2 rerun-after-success and F-1 double-click guard."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tests.frontend.conftest import RoutedResponse, navigate_to


def _open_cmc_morning(at: AppTest) -> AppTest:
    return navigate_to(at, "CMC Morning")


def test_mark_reviewed_triggers_rerun_with_no_errors(logged_in_app, mock_api):
    """W-5/S-1: a successful "Mark reviewed" click reruns the script cleanly.

    AppTest has no direct "was st.rerun() called" flag, but st.rerun()
    raises RerunException, which the script runner catches internally and
    simply ends that run -- so the only externally observable signal is
    that `.run()` (called by `.click().run()`) completes without an
    unhandled exception and the page re-renders using fresh data, exactly
    as it would after a live rerun. An exception here would mean the
    rerun path crashed instead of completing.
    """
    at = _open_cmc_morning(logged_in_app)
    assert at.button(key="sp_rev_hearing-0001") is not None

    at.button(key="sp_rev_hearing-0001").click().run()

    assert not at.exception
    assert any("marked reviewed" in s.value.lower() for s in at.success)


def test_mark_reviewed_calls_the_sp_review_endpoint_with_case_id(logged_in_app, mock_api):
    """The rerun-triggering click must have actually posted the SP review before rerunning."""
    at = _open_cmc_morning(logged_in_app)

    at.button(key="sp_rev_hearing-0001").click().run()

    review_calls = [
        call for call in mock_api.mock.call_args_list if "/api/v1/cmc/sp-review" in call.args[1]
    ]
    assert len(review_calls) == 1
    sent_body = review_calls[0].kwargs.get("json", {})
    assert sent_body["case_id"] == "case-0001"
    assert sent_body["status"] == "reviewed"


def test_open_meeting_triggers_rerun_with_no_errors(logged_in_app, mock_api):
    """W-5/S-2: opening the CMC meeting also reruns cleanly on success.

    Note: unlike the "Mark reviewed" success message (rendered inside a
    nested st.expander block), the top-level `st.success(f"Meeting
    opened: ...")` here does not survive into AppTest's final element
    tree -- verified with a spy on `st.success` showing it genuinely
    fires before `st.rerun()` triggers a real internal re-execution of
    the script, whose fresh top-level render simply doesn't include it
    (a live browser user would see it flash briefly). This is an AppTest
    element-reconciliation characteristic of top-level elements
    immediately preceding a rerun, not a bug in app.py, so this test
    asserts on the durable, verifiable outcome (clean rerun + correct
    API payload + guard reset) rather than the transient message.
    """
    at = _open_cmc_morning(logged_in_app)

    at.button(key="open_meeting_btn").click().run()

    assert not at.exception
    assert at.session_state["opening_meeting"] is False


def test_open_meeting_calls_the_meeting_endpoint(logged_in_app, mock_api):
    """The open-meeting click must have actually posted to /cmc/meeting."""
    at = _open_cmc_morning(logged_in_app)

    at.button(key="open_meeting_btn").click().run()

    meeting_calls = [
        call for call in mock_api.mock.call_args_list if "/api/v1/cmc/meeting" in call.args[1]
    ]
    assert len(meeting_calls) == 1
    assert meeting_calls[0].kwargs.get("json", {}) == {"minutes": "Daily CMC — 10am"}


def test_double_click_guard_hides_button_and_shows_in_flight_message(logged_in_app, mock_api):
    """F-1: while `reviewing_{hearing_id}` is set, the button is replaced by an info message.

    This reproduces the in-flight state a real double-click would produce:
    the first click sets the guard flag before the (slow) API call
    resolves. We simulate "API call still in flight" by setting the flag
    directly and rerunning, since AppTest cannot pause mid-callback.
    """
    at = _open_cmc_morning(logged_in_app)
    assert at.button(key="sp_rev_hearing-0001") is not None, "button should be present before any click"

    at.session_state["reviewing_hearing-0001"] = True
    at.run()

    assert not any(b.key == "sp_rev_hearing-0001" for b in at.button), (
        "the Mark reviewed button must not render while its guard flag is set"
    )
    assert any("marking reviewed" in i.value.lower() for i in at.info)


def test_guard_flag_is_cleared_after_the_call_completes(logged_in_app, mock_api):
    """F-1/F-2: the guard flag is reset (via `finally`) once the API call finishes.

    After a full click+run round-trip completes, the button must be
    clickable again -- proving the guard does not permanently lock out
    review actions after the first successful click.
    """
    at = _open_cmc_morning(logged_in_app)

    at.button(key="sp_rev_hearing-0001").click().run()

    assert at.session_state["reviewing_hearing-0001"] is False
    assert at.button(key="sp_rev_hearing-0001") is not None, (
        "the button should reappear once the guard flag is reset"
    )


def test_guard_prevents_a_second_api_call_while_first_is_in_flight(logged_in_app, mock_api):
    """F-1: with the guard flag already set, clicking again must not fire a second API call.

    The rendered branch is `elif st.button(...)` behind
    `if st.session_state.get(f"reviewing_{id}")`, so once the guard is
    set the button itself is not drawn at all -- there is nothing to
    click, which is the strongest form of "prevented".
    """
    at = _open_cmc_morning(logged_in_app)
    at.session_state["reviewing_hearing-0001"] = True
    at.run()

    review_calls_before = [
        call for call in mock_api.mock.call_args_list if "/api/v1/cmc/sp-review" in call.args[1]
    ]
    assert review_calls_before == []
    assert not any(b.key == "sp_rev_hearing-0001" for b in at.button)


def test_failed_review_shows_the_api_error(logged_in_app, mock_api):
    """A failing API call surfaces `_api_call`'s own error message, not a "Failed: ..." wrapper.

    Empirically verified: `_api_call` calls `st.error(...)` and then
    `st.stop()` for any >=400 response, and `st.stop()` raises
    StreamlitStopException directly out of the script run rather than
    through normal Python exception propagation -- so
    `render_cmc_morning`'s local `except Exception as e: st.error(f"Failed:
    {e}")` around the `api_post` call never actually fires for this path;
    the message seen is the one `_api_call` itself rendered.
    """
    mock_api.set("/api/v1/cmc/sp-review", RoutedResponse(500, {"detail": "boom"}, text="boom"))
    at = _open_cmc_morning(logged_in_app)

    at.button(key="sp_rev_hearing-0001").click().run()

    assert not at.exception
    assert any("api error 500" in e.value.lower() for e in at.error)


def test_failed_review_leaves_the_guard_flag_set(logged_in_app, mock_api):
    """Documents observed behavior: st.stop() skips the `finally` guard-reset.

    This was verified with a minimal AppTest reproduction: a `finally`
    block that sets a session_state flag does NOT execute when `st.stop()`
    is raised inside the corresponding `try`. Concretely, this means
    `render_cmc_morning`'s `finally: st.session_state[f"reviewing_{id}"] =
    False` does not run when the sp-review call fails, so the guard flag
    is left `True`. This test pins that real, surprising behavior down so
    a future fix (e.g. resetting the flag before the error path, or
    avoiding st.stop() here) is a deliberate, visible change rather than
    a silent regression either way.
    """
    mock_api.set("/api/v1/cmc/sp-review", RoutedResponse(500, {"detail": "boom"}, text="boom"))
    at = _open_cmc_morning(logged_in_app)

    at.button(key="sp_rev_hearing-0001").click().run()

    assert at.session_state["reviewing_hearing-0001"] is True


def test_failed_review_hides_the_button_behind_in_flight_message_on_next_render(
    logged_in_app, mock_api
):
    """The consequence of the guard flag staying set: settles into "stuck" state.

    The click-handling run itself still shows the button (it was drawn
    before `st.stop()` cut execution short mid-handler) -- the guard's
    real effect is only visible on the *next* render, once the script
    re-evaluates the `if flag: info else: elif button` check from a
    clean top-of-script state with the (still-True) flag already in
    session_state.
    """
    mock_api.set("/api/v1/cmc/sp-review", RoutedResponse(500, {"detail": "boom"}, text="boom"))
    at = _open_cmc_morning(logged_in_app)

    at.button(key="sp_rev_hearing-0001").click().run()
    assert at.session_state["reviewing_hearing-0001"] is True

    at.run()  # settle: re-render with the (still-set) guard flag

    assert not any(b.key == "sp_rev_hearing-0001" for b in at.button)
    assert any("marking reviewed" in i.value.lower() for i in at.info)
