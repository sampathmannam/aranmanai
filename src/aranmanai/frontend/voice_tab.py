"""Voice tab for the Aranmanai Streamlit app.

Push-to-talk interface for IOs and SPs to file complaints, dictate case
diary entries, search cases, and dictate witness prep notes.

Uses the /api/v1/voice/* endpoints (transcribe, pipeline, speak).
"""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import requests
import streamlit as st

from aranmanai.config import get_settings

API_BASE = f"http://{get_settings().host}:{get_settings().port}"


def _auth_headers() -> dict:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def render_voice_tab() -> None:
    """Render the Voice tab inside the Streamlit app."""
    st.header("Voice")
    st.caption("Push-to-talk for IOs and SPs. Tamil + English + Hindi.")

    # 1. Voice capabilities
    try:
        r = requests.get(f"{API_BASE}/api/v1/voice/capabilities",
                          headers=_auth_headers(), timeout=10)
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
    audio_file = st.file_uploader(
        "Upload an audio file (WAV/MP3/M4A/OGG)",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
        help="Audio is processed locally. Not uploaded to any cloud.",
    )
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

    # Persist transcribed text in session state across re-renders
    if "voice_transcript" not in st.session_state:
        st.session_state.voice_transcript = ""
    if "voice_transcript_result" not in st.session_state:
        st.session_state.voice_transcript_result = None

    col_btn = st.columns([1, 1, 3])
    transcribe_clicked = col_btn[0].button("Transcribe", type="primary")
    # "Transcribe and generate complaint" — both in one shot
    generate_clicked = col_btn[1].button("Transcribe + Generate complaint")

    if audio_file and (transcribe_clicked or generate_clicked):
        try:
            # Save to temp file (faster-whisper expects path)
            suffix = Path(audio_file.name).suffix or ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                tf.write(audio_file.read())
                tmp_path = Path(tf.name)
            endpoint = "/api/v1/voice/pipeline" if use_pipeline else "/api/v1/voice/transcribe"
            with open(tmp_path, "rb") as f:
                files = {"audio": (audio_file.name, f, "audio/wav")}
                data = {}
                if language:
                    data["language"] = language
                r = requests.post(
                    f"{API_BASE}{endpoint}",
                    files=files,
                    data=data,
                    headers=_auth_headers(),
                    timeout=120,
                )
            try:
                tmp_path.unlink()
            except OSError:
                pass
            if r.status_code == 200:
                result = r.json()
                transcript_text = result.get("text", "")
                st.session_state.voice_transcript = transcript_text
                st.session_state.voice_transcript_result = result
                st.success("Transcription complete")
                st.text_area("Transcribed text", transcript_text, height=200, key="transcript_area")
                cols = st.columns(4)
                cols[0].metric("Language", result.get("language", "?"))
                cols[1].metric("Confidence", f"{result.get('language_probability', 0):.0%}")
                cols[2].metric("Duration (s)", f"{result.get('duration_s', 0):.1f}")
                cols[3].metric("Model", result.get("model", "?"))
                if "num_segments" in result:
                    st.write(f"Segments: {result['num_segments']}")
                st.code(f"audio_sha256: {result.get('audio_sha256', '?')[:24]}...", language="text")

                # Chain: send directly to complaint-intake
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
                                st.text_area("Structured complaint", intake.get("structured", ""), height=300)
                                st.write(f"**Registerable:** {intake.get('registerable', '?')}")
                                st.write(f"**Likely BNS sections:** {intake.get('likely_sections_bns', [])}")
                                st.write(f"**Offence type:** {intake.get('offence_type', '?')}")
                            else:
                                st.warning(f"Complaint intake failed (HTTP {intake_r.status_code}). "
                                           "AI service may be unavailable — start the API server first.")
                        except Exception as ie:
                            st.warning(f"Complaint intake error: {ie}. Start the API server with: python -m aranmanai.api.main")
            else:
                st.error(f"Transcription failed: HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            st.error(f"Transcription error: {e}")

    st.divider()

    # 3. TTS speak
    st.subheader("Text-to-speech (read aloud)")
    speak_text = st.text_area("Text to speak", height=100, placeholder="Case summary, witness statement, etc.")
    if st.button("Speak") and speak_text:
        try:
            r = requests.post(
                f"{API_BASE}/api/v1/voice/speak",
                json={"text": speak_text},
                headers=_auth_headers(),
                timeout=30,
            )
            if r.status_code == 200:
                st.audio(r.content, format="audio/wav")
                st.caption("Audio (WAV) generated locally. Click play to hear.")
            else:
                st.warning(f"TTS unavailable (HTTP {r.status_code}). System uses offline pyttsx3; on Windows Server / no-audio-device environments, this may return a silent WAV fallback.")
        except Exception as e:
            st.warning(f"TTS error: {e}")
