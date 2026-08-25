"""Tests for U-5: the Tamil embedding debug vector chart must be hidden by default.

The audit found `st.bar_chart({"value": vec[:50]})` rendered unconditionally
with only a caption for context -- meaningless to a non-ML audience. The fix
gates it behind an unchecked-by-default checkbox. These tests confirm both
halves: hidden by default, and it genuinely appears once opted into (a
positive control -- otherwise a "hidden by default" test alone can't tell
a real gate from a chart that's simply broken/removed).
"""
from __future__ import annotations

from tests.frontend.conftest import RoutedResponse, navigate_to

_FAKE_EMBED_RESPONSE = {"vector_dim": 384, "model": "bge-m3", "vector": [0.1] * 384}


def _open_embed_tool(at):
    at = navigate_to(at, "Tamil")
    at.selectbox[0].set_value("Embed (semantic search)").run()
    return at


def _chart_node_types(at) -> list[str]:
    """Flatten the element tree and collect every node's `type` name."""
    types: list[str] = []

    def walk(node) -> None:
        t = getattr(node, "type", None)
        if t is not None:
            types.append(t)
        children = getattr(node, "children", None)
        if children:
            for child in children.values() if isinstance(children, dict) else children:
                walk(child)

    walk(at.main)
    return types


def test_debug_chart_checkbox_defaults_to_unchecked(logged_in_app, mock_api, mock_tamil_api):
    at = _open_embed_tool(logged_in_app)

    checkboxes = [c for c in at.checkbox if c.label.startswith("Show debug vector plot")]
    assert len(checkboxes) == 1
    assert checkboxes[0].value is False


def test_chart_does_not_render_when_checkbox_is_unchecked(logged_in_app, mock_api, mock_tamil_api):
    mock_tamil_api.return_value = RoutedResponse(200, _FAKE_EMBED_RESPONSE)
    at = _open_embed_tool(logged_in_app)
    next(ta for ta in at.text_area if ta.label == "Text to embed").input("hello world").run()

    next(b for b in at.button if b.label == "Embed").click().run(timeout=15)

    assert not at.exception
    assert "arrow_vega_lite_chart" not in _chart_node_types(at)
    assert not any("Showing first 50 of" in c.value for c in at.caption)


def test_chart_renders_once_the_checkbox_is_checked(logged_in_app, mock_api, mock_tamil_api):
    """Positive control: the checkbox actually gates real content, not a permanently-dead feature."""
    mock_tamil_api.return_value = RoutedResponse(200, _FAKE_EMBED_RESPONSE)
    at = _open_embed_tool(logged_in_app)
    next(c for c in at.checkbox if c.label.startswith("Show debug vector plot")).check().run(timeout=15)
    next(ta for ta in at.text_area if ta.label == "Text to embed").input("hello world").run()

    next(b for b in at.button if b.label == "Embed").click().run(timeout=15)

    assert not at.exception
    assert "arrow_vega_lite_chart" in _chart_node_types(at)
    assert any("Showing first 50 of 384 dimensions" in c.value for c in at.caption)
