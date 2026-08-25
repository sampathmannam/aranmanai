"""Test for U-7: focus-ring CSS must be injected into every page.

Caveat (see final report): AppTest runs the script headlessly with no real
DOM/browser, so it cannot verify that a focus ring is actually *visible* to
a keyboard user -- that would need a real browser + visual/accessibility
test. What AppTest *can* verify is that the `st.markdown(..., unsafe_allow_
html=True)` call injecting the CSS actually executes on every render and
still contains the selectors/declaration the audit's remediation specified
(`:focus` + `outline`) -- catching, for example, someone deleting the call
or breaking the selector in a future refactor. This is a narrower guarantee
than "focus rings are visible," and is documented as such rather than
presented as full U-7 coverage.
"""
from __future__ import annotations


def test_focus_ring_css_is_injected_on_every_authenticated_page(logged_in_app, mock_api):
    from tests.frontend.conftest import navigate_to

    css_blocks = [m.value for m in logged_in_app.markdown if "<style>" in m.value]
    assert any(":focus" in block and "outline" in block for block in css_blocks), (
        "expected a <style> block targeting :focus with an outline declaration"
    )

    # Re-assert after navigating -- the CSS is injected at module import
    # time (runs once per script execution), not conditionally per page.
    at = navigate_to(logged_in_app, "CMC Morning")
    css_blocks_after_nav = [m.value for m in at.markdown if "<style>" in m.value]
    assert any(":focus" in block and "outline" in block for block in css_blocks_after_nav)


def test_focus_ring_css_targets_buttons_specifically(logged_in_app, mock_api):
    """The audit's remediation targeted `button:focus` -- pin that selector, not just any :focus rule."""
    css_blocks = [m.value for m in logged_in_app.markdown if "<style>" in m.value]
    assert any("button:focus" in block for block in css_blocks)
