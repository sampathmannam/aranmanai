"""faster-whisper STT wrapper.

faster-whisper is a CTranslate2 reimplementation of OpenAI Whisper.
4x faster than openai-whisper on CPU. Supports tiny/base/small/medium/large-v3.
Multilingual (99 languages incl. Tamil, English, Hindi).

For v1 we use `small` (466 MB) on GPU, with `base` (74 MB) as CPU fallback.
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Union

import numpy as np

from aranmanai.config import get_settings
from aranmanai.observability import get_logger

log = get_logger(__name__)


# Whisper language codes we support out of the box
SUPPORTED_LANGUAGES = {
    "en": "english",
    "ta": "tamil",
    "hi": "hindi",
    "te": "telugu",
    "kn": "kannada",
    "ml": "malayalam",
    "mr": "marathi",
    "bn": "bengali",
    "gu": "gujarati",
    "pa": "punjabi",
    "ur": "urdu",
}


@dataclass
class TranscriptionResult:
    """Result of a speech-to-text call."""
    text: str
    language: str
    language_probability: float
    duration_s: float
    segments: list[dict] = field(default_factory=list)  # per-segment details
    model: str = ""
    # Hash of the input audio (DPDP §8(3))
    audio_sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration_s": self.duration_s,
            "segments": self.segments,
            "model": self.model,
            "audio_sha256": self.audio_sha256,
        }


class SpeechToText:
    """faster-whisper wrapper with lazy model loading.

    Usage:
        stt = SpeechToText(model_size="small", device="cuda")
        result = stt.transcribe_file("complaint.wav", language="ta")
        print(result.text)
    """

    _MODELS: dict[str, object] = {}  # shared cache

    def __init__(
        self,
        model_size: Optional[str] = None,  # defaults to settings.whisper_model
        device: Optional[Literal["cpu", "cuda", "auto"]] = None,
        compute_type: Optional[str] = None,  # "int8", "float16", "float32"
    ):
        s = get_settings()
        self.model_size = model_size or s.whisper_model
        self.device = device or s.whisper_device
        self.compute_type = compute_type or ("float16" if self.device == "cuda" else "int8")
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        cache_key = f"{self.model_size}_{self.device}_{self.compute_type}"
        if cache_key in SpeechToText._MODELS:
            self._model = SpeechToText._MODELS[cache_key]
            self._loaded = True
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper not installed. Install voice extras: "
                "pip install faster-whisper==1.0.3"
            ) from e
        log.info("stt.loading model=%s device=%s compute_type=%s",
                 self.model_size, self.device, self.compute_type)
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        SpeechToText._MODELS[cache_key] = self._model
        self._loaded = True
        log.info("stt.loaded model=%s device=%s", self.model_size, self.device)

    def transcribe_file(
        self,
        path: Union[str, Path],
        language: Optional[str] = None,  # "ta" / "en" / "hi" / None=auto-detect
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> TranscriptionResult:
        """Transcribe a WAV file (or any format ffmpeg supports)."""
        self._load()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        # Hash the audio for DPDP §8(3) audit
        import hashlib
        audio_bytes = path.read_bytes()
        audio_hash = hashlib.sha256(audio_bytes).hexdigest()

        language = language or None  # None = auto-detect
        segments_iter, info = self._model.transcribe(
            str(path),
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )
        segments = []
        text_parts = []
        for s in segments_iter:
            segments.append({
                "start": s.start,
                "end": s.end,
                "text": s.text.strip(),
                "no_speech_prob": s.no_speech_prob,
            })
            text_parts.append(s.text.strip())
        text = " ".join(text_parts).strip()
        return TranscriptionResult(
            text=text,
            language=info.language,
            language_probability=info.language_probability,
            duration_s=info.duration,
            segments=segments,
            model=self.model_size,
            audio_sha256=audio_hash,
        )

    def transcribe_array(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe a numpy array (mono float32, [-1, 1])."""
        self._load()

        # Write to in-memory WAV
        buf = io.BytesIO()
        audio_int16 = (audio * 32767).astype(np.int16)
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        buf.seek(0)
        audio_bytes = buf.read()

        import hashlib
        audio_hash = hashlib.sha256(audio_bytes).hexdigest()

        language = language or None
        segments_iter, info = self._model.transcribe(
            buf,
            language=language,
            beam_size=5,
            vad_filter=True,
        )
        segments = []
        text_parts = []
        for s in segments_iter:
            segments.append({
                "start": s.start,
                "end": s.end,
                "text": s.text.strip(),
                "no_speech_prob": s.no_speech_prob,
            })
            text_parts.append(s.text.strip())
        text = " ".join(text_parts).strip()
        return TranscriptionResult(
            text=text,
            language=info.language,
            language_probability=info.language_probability,
            duration_s=info.duration,
            segments=segments,
            model=self.model_size,
            audio_sha256=audio_hash,
        )


def transcribe_wav(
    path: Union[str, Path],
    language: Optional[str] = None,
    model_size: Optional[str] = None,
) -> TranscriptionResult:
    """Convenience: transcribe a WAV with default settings."""
    return SpeechToText(model_size=model_size).transcribe_file(path, language=language)
