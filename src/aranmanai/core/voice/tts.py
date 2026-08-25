"""TTS wrapper for readouts.

For v1, uses pyttsx3 (offline, Windows SAPI / macOS say / Linux espeak).
Piper-TTS was tried but piper-phonemize has no Windows wheel. Coqui TTS
is too heavy. Edge-TTS would require cloud calls (rejected for v1).

Scope for v1: simple system TTS for case summary readouts. Tamil support
is whatever pyttsx3 gives us on Windows SAPI (typically the system
Tamil voice if installed).
"""
from __future__ import annotations

from pathlib import Path

from aranmanai.observability import get_logger

log = get_logger(__name__)


class TextToSpeech:
    """Offline TTS via pyttsx3.

    Usage:
        tts = TextToSpeech()
        tts.speak("Case FIR-2024-123 has 3 FATAL lapses.")
        tts.to_file("summary.wav", "First hearing on 2026-09-15.")
    """

    def __init__(self, rate: int = 175, voice_id: str | None = None):
        self.rate = rate
        self.voice_id = voice_id
        self._engine = None

    def _ensure_engine(self):
        if self._engine is None:
            try:
                import pyttsx3
            except ImportError as e:
                raise RuntimeError(
                    "pyttsx3 not installed. Install: pip install pyttsx3==2.90"
                ) from e
            self._engine = None
            try:
                self._engine = pyttsx3.init()
            except Exception as e:
                log.warning("tts.engine_init_failed err=%s", e)
                self._engine = None
                return
            self._engine.setProperty("rate", self.rate)
            if self.voice_id:
                self._engine.setProperty("voice", self.voice_id)
            log.info("tts.engine_ready rate=%s voice=%s", self.rate, self.voice_id or "default")
        return self._engine

    def list_voices(self) -> list[dict]:
        """List available system voices."""
        engine = self._ensure_engine()
        if not engine:
            return []
        return [
            {"id": v.id, "name": v.name, "languages": v.languages, "gender": v.gender}
            for v in engine.getProperty("voices") or []
        ]

    def speak(self, text: str) -> None:
        """Speak the text aloud. Blocks until done."""
        engine = self._ensure_engine()
        if not engine:
            log.warning("tts.unavailable text=%r", text[:80])
            return
        engine.say(text)
        engine.runAndWait()
        log.debug("tts.spoke text=%r", text[:80])

    def to_file(self, output_path: str | Path, text: str) -> Path:
        """Synthesize to a WAV file. Returns the output path."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        engine = self._ensure_engine()
        if not engine:
            # Fallback: write silent WAV
            log.warning("tts.unavailable writing_silent output=%s", output_path)
            _write_silent_wav(output_path, duration_s=max(1.0, len(text) * 0.05))
            return output_path
        engine.save_to_file(text, str(output_path))
        engine.runAndWait()
        log.info("tts.saved output=%s text_len=%d", output_path, len(text))
        return output_path


def _write_silent_wav(path: Path, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    """Write a silent WAV file (fallback when no TTS engine)."""
    import wave
    n = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * (n * 2))
