"""Voice tab for the Aranmanai Streamlit app.

Push-to-talk interface for IOs and SPs to file complaints, dictate case
diary entries, search cases, and dictate witness prep notes.

Uses the /api/v1/voice/* endpoints (transcribe, pipeline, speak).

Frontend QA fixes applied (2026-08-25).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import requests
import streamlit as st

from aranmanai.config import get_settings

API_BASE = f"http://{get_settings().host}:{get_settings().port}"


# ──────────────────────────────────────────────────────────────
# F-7 / S-7: Guard
# ──────────────────────────────────────────────────────────────
def _auth_headers() -> dict:
    token = st.session_state.get("token")
    if not token:
        st.warning("Please log in to use voice features.")
        st.stop()
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────────────────────
# F-3: Whitespace non-empty
# ──────────────────────────────────────────────────────────────
def _nonempty(label: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        st.error(f"{label} cannot be empty.")
        st.stop()
    return v


# ──────────────────────────────────────────────────────────────
# U-2: truncate
# ──────────────────────────────────────────────────────────────
def _short(s: str | None, n: int = 50) -> str:
    s = s or "—"
    return s if len(s) <= n else s[: n - 1] + "…"


def render_voice_tab() -> None:
    """Render the Voice tab inside the Streamlit app."""
    st.header("Voice")
    st.caption("Push-to-talk for IOs and SPs. Tamil + English + Hindi.")

    # 1. Voice capabilities
    try:
        with st.spinner("Loading voice capabilities..."):
            r = requests.get(
                f"{API_BASE}/api/v1/voice/capabilities",
                headers=_auth_headers(),
                timeout=10,
            )
        if r.status_code == 200:
            cap = r.json()
            cols = st.columns(4)
            cols[0].metric("STT model", cap.get("stt_model", "?"))
            cols[1].metric("STT device", cap.get("stt_device", "?"))
            cols[2].metric("TTS", "yes" if cap.get("tts_available") else "no (silent)")
            cols[3].metric("Max audio (MB)", cap.get("max_audio_size_mb", "?"))
        else:
            st.warning(f"Could not load voice capabilities (HTTP {r.status_code})")
    except Exception as e:
        st.warning(f"Voice capabilities unavailable: {e}")

    st.divider()

    # 2. Audio uploader + transcribe
    st.subheader("Transcribe audio file")
    settings = get_settings()
    audio_file = st.file_uploader(
        f"Upload an audio file (WAV/MP3/M4A/OGG) — max {settings.max_audio_size_mb}MB",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
        help="Audio is processed locally. Not uploaded to any cloud.",
    )
    # U-6: file size indicator
    if audio_file is not None:
        size_mb = audio_file.size / 1024 / 1024
        st.caption(f"File: {audio_file.name} — {size_mb:.2f}MB / {settings.max_audio_size_mb}MB")
        if size_mb > settings.max_audio_size_mb:
            st.error(
                f"File too large: {size_mb:.1f}MB > limit {settings.max_audio_size_mb}MB. "
                "Transcribe a shorter clip."
            )
            st.stop()
    col_lang = st.columns(2)
    language = col_lang[0].selectbox(
        "Language (auto-detect if blank)",
        ["", "en", "ta", "hi", "te", "kn", "ml", "mr", "bn"],
        index=0,
    )
    use_pipeline = col_lang[1].checkbox(
        "Use VAD pipeline (recommended for long files)",
        value=True,
    )

    # W-4: bind session state via value=, key=
    st.session_state.setdefault("voice_transcript", "")
    st.session_state.setdefault("voice_transcript_result", None)

    col_btn = st.columns([1, 1, 3])
    transcribe_key = "voice_transcribe_btn"
    generate_key = "voice_generate_btn"

    # F-2: disable buttons during in-flight
    in_flight = st.session_state.get("_voice_in_flight", False)
    transcribe_clicked = col_btn[0].button(
        "Transcribe", type="primary", key=transcribe_key, disabled=in_flight
    )
    generate_clicked = col_btn[1].button(
        "Transcribe + Generate complaint", disabled=in_flight
    )

    if audio_file and (transcribe_clicked or generate_clicked):
        if in_flight:
            st.info("Already transcribing…")
        else:
            st.session_state["_voice_in_flight"] = True
            tmp_path = None
            try:
                # S-4: spinner on the first call (transcription)
                with st.spinner("Transcribing audio..."):
                    suffix = Path(audio_file.name).suffix or ".wav"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                        tf.write(audio_file.read())
                        tmp_path = Path(tf.name)
                    endpoint = (
                        "/api/v1/voice/pipeline" if use_pipeline else "/api/v1/voice/transcribe"
                    )
                    with open(tmp_path, "rb") as f:
                        files = {"audio": (audio_file.name, f, "audio/wav")}
                        data = {}
                        if language:
                            data["language"] = language
                        rr = requests.post(
                            f"{API_BASE}{endpoint}",
                            files=files,
                            data=data,
                            headers=_auth_headers(),
                            timeout=120,
                        )
                if rr.status_code == 200:
                    result = rr.json()
                    transcript_text = result.get("text", "")
                    st.session_state["voice_transcript"] = transcript_text
                    st.session_state["voice_transcript_result"] = result
                    st.success("Transcription complete")
                    # W-4: bind to session state via value=
                    st.text_area(
                        "Transcribed text",
                        value=transcript_text,
                        height=200,
                        key="transcript_area",
                    )
                    cols = st.columns(4)
                    cols[0].metric("Language", result.get("language", "?"))
                    cols[1].metric("Confidence", f"{result.get('language_probability', 0):.0%}")
                    cols[2].metric("Duration (s)", f"{result.get('duration_s', 0):.1f}")
                    cols[3].metric("Model", result.get("model", "?"))
                    if "num_segments" in result:
                        st.write(f"Segments: {result['num_segments']}")
                    st.code(
                        f"audio_sha256: {result.get('audio_sha256', '?')[:24]}...",
                        language="text",
                    )

                    # Chain: send to complaint-intake
                    if generate_clicked and transcript_text:
                        with st.spinner("Generating structured complaint from transcript..."):
                            try:
                                intake_r = requests.post(
                                    f"{API_BASE}/api/v1/ai/complaint-intake",
                                    json={
                                        "raw_complaint": transcript_text,
                                        "complainant_name": None,
                                        "complainant_contact": None,
                                        "language": result.get("language", "en") or "en",
                                    },
                                    headers=_auth_headers(),
                                    timeout=60,
                                )
                                if intake_r.status_code == 200:
                                    intake = intake_r.json()
                                    st.success("Complaint generated from audio!")
                                    st.text_area(
                                        "Structured complaint",
                                        intake.get("structured", ""),
                                        height=300,
                                    )
                                    st.write(f"**Registerable:** {intake.get('registerable', '?')}")
                                    st.write(f"**Likely BNS sections:** {intake.get('likely_sections_bns', [])}")
                                    st.write(f"**Offence type:** {intake.get('offence_type', '?')}")
                                else:
                                    st.warning(
                                        f"Complaint intake failed (HTTP {intake_r.status_code}). "
                                        "AI service may be unavailable."
                                    )
                            except Exception as ie:
                                st.warning(f"Complaint intake error: {ie}. Start the API server with: python -m aranmanai.api.main")
                else:
                    st.error(f"Transcription failed: HTTP {rr.status_code}: {rr.text[:300]}")
            except Exception as e:
                st.error(f"Transcription error: {e}")
            finally:
                if tmp_path:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                st.session_state["_voice_in_flight"] = False

    # W-4: also display the persisted transcript if user has one
    elif st.session_state.get("voice_transcript"):
        st.text_area(
            "Transcribed text (from earlier)",
            value=st.session_state["voice_transcript"],
            height=200,
            key="transcript_area_persisted",
            disabled=True,
        )

    st.divider()

    # 3. TTS speak
    st.subheader("Text-to-speech (read aloud)")
    speak_text = st.text_area(
        "Text to speak", height=100, placeholder="Case summary, witness statement, etc."
    )
    speak_in_flight = st.session_state.get("_tts_in_flight", False)
    if st.button("Speak", disabled=speak_in_flight or not speak_text.strip()):
        if not speak_text.strip():
            st.error("Text to speak cannot be empty.")
            st.stop()
        st.session_state["_tts_in_flight"] = True
        try:
            with st.spinner("Synthesizing speech..."):
                rr = requests.post(
                    f"{API_BASE}/api/v1/voice/speak",
                    json={"text": speak_text},
                    headers=_auth_headers(),
                    timeout=30,
                )
            if rr.status_code == 200:
                st.audio(rr.content, format="audio/wav")
                st.caption("Audio (WAV) generated locally. Click play to hear.")
            else:
                st.warning(
                    f"TTS unavailable (HTTP {rr.status_code}). System uses offline pyttsx3; "
                    "on Windows Server / no-audio-device environments, this may return a silent WAV fallback."
                )
        except Exception as e:
            st.warning(f"TTS error: {e}")
        finally:
            st.session_state["_tts_in_flight"] = False
