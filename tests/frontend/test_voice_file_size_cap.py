"""Tests for U-6: the Voice tab's audio upload must show a size indicator and enforce a cap.

`st.file_uploader` has no live-widget support in `streamlit.testing.v1.AppTest`
(confirmed: `AppTest` exposes no `file_uploader` accessor, and there is no
way to inject a fake `UploadedFile` into a running script), so
`render_voice_tab()`'s size-check logic was factored out into the pure
`_audio_size_status(filename, size_mb, max_mb)` helper specifically so it
stays testable without a real upload widget. These tests exercise that
helper directly -- the same function `render_voice_tab()` calls once a
file is actually selected.
"""
from __future__ import annotations

from aranmanai.frontend.voice_tab import _audio_size_status


def test_caption_reports_the_file_name_and_both_sizes():
    caption, over_limit = _audio_size_status("statement.wav", 3.5, 50)

    assert caption == "File: statement.wav — 3.50MB / 50MB"
    assert over_limit is False


def test_file_within_the_cap_is_not_flagged():
    _, over_limit = _audio_size_status("short_clip.mp3", 49.9, 50)

    assert over_limit is False


def test_file_exactly_at_the_cap_is_not_flagged():
    _, over_limit = _audio_size_status("exact.mp3", 50.0, 50)

    assert over_limit is False


def test_file_over_the_cap_is_flagged():
    caption, over_limit = _audio_size_status("huge_recording.wav", 512.0, 50)

    assert over_limit is True
    assert "512.00MB" in caption
    assert "50MB" in caption


def test_uses_the_configured_cap_not_a_hardcoded_one():
    """A deployment with a different max_audio_size_mb must be respected, not a hardcoded 50."""
    _, over_limit_small_cap = _audio_size_status("clip.wav", 10.0, 5)
    _, over_limit_large_cap = _audio_size_status("clip.wav", 10.0, 100)

    assert over_limit_small_cap is True
    assert over_limit_large_cap is False
