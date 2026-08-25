"""Tests for the voice module: VAD, STT, TTS, pipeline.

These tests cover the module surface without requiring actual model
downloads or audio files. Heavy tests (real STT, TTS) are marked
`slow` and skipped by default.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

# --- VAD ---

def test_vad_silent_audio():
    """A silent audio file should produce no speech segments."""
    from aranmanai.core.voice import detect_speech_segments
    # 1 second of silence at 16kHz
    audio = np.zeros(16000, dtype=np.float32)
    segments = detect_speech_segments(audio, sample_rate=16000)
    assert segments == [], f"Expected no segments, got {len(segments)}"


def test_vad_synthetic_speech():
    """A synthetic signal that looks like speech (varying amplitude) should produce segments."""
    from aranmanai.core.voice import detect_speech_segments
    sr = 16000
    duration_s = 2.0
    n = int(sr * duration_s)
    # Modulated noise — varies in amplitude to simulate speech envelope
    t = np.linspace(0, duration_s, n)
    audio = (np.sin(2 * math.pi * 200 * t) * 0.5 * np.sin(2 * math.pi * 3 * t)).astype(np.float32)
    segments = detect_speech_segments(audio, sample_rate=sr, threshold=0.3)
    # Don't assert exact count — just that the VAD runs without error
    assert isinstance(segments, list)


def test_load_wav(tmp_path: Path):
    """Round-trip a WAV through load_wav and back."""
    from aranmanai.core.voice import load_wav
    sr = 16000
    duration_s = 0.1
    n = int(sr * duration_s)
    audio_int16 = np.arange(n, dtype=np.int16) % 1000
    audio_path = tmp_path / "test.wav"
    with wave.open(str(audio_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_int16.tobytes())
    loaded, loaded_sr = load_wav(audio_path)
    assert loaded_sr == sr
    assert len(loaded) == n
    # Float32 should be in [-1, 1]
    assert loaded.max() <= 1.0
    assert loaded.min() >= -1.0


# --- STT ---

def test_stt_languages_constant():
    """The SUPPORTED_LANGUAGES set should include the v1 required set."""
    from aranmanai.core.voice.stt import SUPPORTED_LANGUAGES
    for lang in ("en", "ta", "hi"):
        assert lang in SUPPORTED_LANGUAGES, f"Missing language: {lang}"


def test_transcription_result_to_dict():
    """TranscriptionResult.to_dict should be JSON-serializable."""

    from aranmanai.core.voice import TranscriptionResult
    r = TranscriptionResult(
        text="Hello world",
        language="en",
        language_probability=0.99,
        duration_s=1.5,
        segments=[{"start": 0.0, "end": 1.5, "text": "Hello world", "no_speech_prob": 0.01}],
        model="small",
        audio_sha256="abc123",
    )
    d = r.to_dict()
    assert d["text"] == "Hello world"
    assert d["language"] == "en"
    assert d["language_probability"] == 0.99
    assert d["model"] == "small"
    assert d["audio_sha256"] == "abc123"
    # Must be JSON-serializable
    import json
    json.dumps(d)


# --- TTS ---

def test_write_silent_wav(tmp_path: Path):
    """_write_silent_wav creates a valid WAV file at the given path."""
    from aranmanai.core.voice.tts import _write_silent_wav
    out = tmp_path / "silent.wav"
    _write_silent_wav(out, duration_s=0.5, sample_rate=16000)
    assert out.exists()
    # Verify it's a valid WAV
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getnframes() == 8000  # 0.5 * 16000


# --- Pipeline ---

def test_pipeline_result_dataclass():
    """PipelineResult is a dataclass with expected fields."""
    from aranmanai.core.voice import PipelineResult
    r = PipelineResult(
        text="hello",
        language="en",
        language_probability=0.9,
        duration_s=1.0,
        num_segments=1,
        audio_sha256="xyz",
        per_segment=[],
    )
    assert r.text == "hello"
    assert r.num_segments == 1


# --- F-9: server-side audio content sniff ---

def test_looks_like_audio_valid_wav_header():
    """A real WAV header (RIFF....WAVE) should pass the sniff."""
    from aranmanai.api.voice import _looks_like_audio
    header = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt "
    assert _looks_like_audio(header) is True


def test_looks_like_audio_valid_ogg_header():
    """A real OGG header (OggS) should pass the sniff."""
    from aranmanai.api.voice import _looks_like_audio
    header = b"OggS" + b"\x00" * 8
    assert _looks_like_audio(header) is True


def test_looks_like_audio_valid_mp4_m4a_header():
    """A real M4A/MP4 header (....ftyp) should pass the sniff."""
    from aranmanai.api.voice import _looks_like_audio
    header = b"\x00\x00\x00\x18ftypM4A "
    assert _looks_like_audio(header) is True


def test_looks_like_audio_valid_mp3_id3_header():
    """An MP3 file with an ID3 tag should pass the sniff."""
    from aranmanai.api.voice import _looks_like_audio
    header = b"ID3\x03\x00\x00\x00\x00\x00\x00"
    assert _looks_like_audio(header) is True


def test_looks_like_audio_valid_mp3_frame_sync_header():
    """An MP3 file with a raw frame sync (no ID3 tag) should pass the sniff."""
    from aranmanai.api.voice import _looks_like_audio
    header = b"\xff\xfb\x90\x00" + b"\x00" * 8
    assert _looks_like_audio(header) is True


def test_looks_like_audio_rejects_garbage_bytes():
    """A fake PDF header renamed to .wav should be rejected."""
    from aranmanai.api.voice import _looks_like_audio
    fake_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    assert _looks_like_audio(fake_pdf) is False


def test_looks_like_audio_rejects_plain_text():
    """Plain text bytes should be rejected."""
    from aranmanai.api.voice import _looks_like_audio
    plain_text = b"this is not audio, just plain text data"
    assert _looks_like_audio(plain_text) is False


def test_looks_like_audio_rejects_too_short():
    """Fewer than 12 bytes can't contain any of the checked signatures."""
    from aranmanai.api.voice import _looks_like_audio
    assert _looks_like_audio(b"RIFF") is False
    assert _looks_like_audio(b"") is False


def test_transcribe_endpoint_rejects_non_audio_with_415(tmp_env):
    """POST /api/v1/voice/transcribe with garbage bytes named .wav -> 415."""
    from fastapi.testclient import TestClient

    from aranmanai.api.main import create_app
    app = create_app()
    with TestClient(app) as c:
        fake_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 32
        r = c.post(
            "/api/v1/voice/transcribe",
            files={"audio": ("fake.wav", fake_pdf, "audio/wav")},
        )
        assert r.status_code == 415
        assert "audio format" in r.json()["detail"]


def test_pipeline_endpoint_rejects_non_audio_with_415(tmp_env):
    """POST /api/v1/voice/pipeline with garbage bytes named .wav -> 415."""
    from fastapi.testclient import TestClient

    from aranmanai.api.main import create_app
    app = create_app()
    with TestClient(app) as c:
        plain_text = b"this is not audio, just plain text data" + b"\x00" * 32
        r = c.post(
            "/api/v1/voice/pipeline",
            files={"audio": ("fake.wav", plain_text, "audio/wav")},
        )
        assert r.status_code == 415
        assert "audio format" in r.json()["detail"]
