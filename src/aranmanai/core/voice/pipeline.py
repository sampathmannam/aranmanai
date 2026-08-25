"""End-to-end voice pipeline: raw audio → text.

Composition:
1. Load audio (WAV file or numpy array)
2. Run VAD to find speech segments (skip silences)
3. Run STT on each segment
4. Concatenate transcriptions

Used by the /voice/transcribe endpoint and the /voice/case (push-to-talk
for case dictation) endpoint.

DPDP §8(3): every transcription returns the audio SHA-256 hash so
the audit log can record the exact bytes that were transcribed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from aranmanai.core.voice.stt import SpeechToText, TranscriptionResult
from aranmanai.core.voice.vad import VoiceActivityDetector, load_wav
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class PipelineResult:
    """End-to-end pipeline result."""
    text: str
    language: str
    language_probability: float
    duration_s: float
    num_segments: int
    audio_sha256: str
    per_segment: list[TranscriptionResult]


class VoicePipeline:
    """VAD + STT pipeline. Lazy-loads both on first call."""

    def __init__(
        self,
        stt_model_size: str | None = None,
        vad_threshold: float = 0.5,
        device: Literal["cpu", "cuda", "auto"] | None = None,
    ):
        self.stt = SpeechToText(model_size=stt_model_size, device=device)
        self.vad = VoiceActivityDetector(threshold=vad_threshold)

    def transcribe_file(
        self,
        path: str | Path,
        language: str | None = None,
    ) -> PipelineResult:
        """VAD + STT on a WAV file."""
        path = Path(path)
        audio, sr = load_wav(path)
        # Hash original file
        audio_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._transcribe(audio, sr, audio_hash, language)

    def transcribe_array(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str | None = None,
    ) -> PipelineResult:
        """VAD + STT on a numpy array."""
        # Hash the audio
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_hash = hashlib.sha256(audio_int16.tobytes()).hexdigest()
        return self._transcribe(audio, sample_rate, audio_hash, language)

    def _transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int,
        audio_hash: str,
        language: str | None,
    ) -> PipelineResult:
        # 1. VAD segments
        segments = self.vad.detect(audio, sample_rate)
        if not segments:
            log.info("pipeline.no_speech hash=%s", audio_hash[:12])
            return PipelineResult(
                text="",
                language=language or "unknown",
                language_probability=0.0,
                duration_s=len(audio) / sample_rate,
                num_segments=0,
                audio_sha256=audio_hash,
                per_segment=[],
            )
        log.info("pipeline.segments count=%d hash=%s", len(segments), audio_hash[:12])

        # 2. STT each segment
        per_segment: list[TranscriptionResult] = []
        text_parts: list[str] = []
        for seg in segments:
            chunk = audio[seg.start_sample : seg.end_sample]
            try:
                r = self.stt.transcribe_array(chunk, sample_rate=sample_rate, language=language)
            except Exception as e:
                log.warning("pipeline.segment_failed err=%s", e)
                continue
            per_segment.append(r)
            if r.text:
                text_parts.append(r.text)

        joined = " ".join(text_parts).strip()
        # Pick best language detection from segments
        if per_segment:
            best = max(per_segment, key=lambda r: r.language_probability)
            language = best.language
            language_probability = best.language_probability
        else:
            language = language or "unknown"
            language_probability = 0.0

        return PipelineResult(
            text=joined,
            language=language,
            language_probability=language_probability,
            duration_s=len(audio) / sample_rate,
            num_segments=len(segments),
            audio_sha256=audio_hash,
            per_segment=per_segment,
        )


def voice_to_text(
    path: str | Path,
    language: str | None = None,
    model_size: str | None = None,
) -> PipelineResult:
    """Convenience: load file, VAD, STT, return joined text."""
    return VoicePipeline(stt_model_size=model_size).transcribe_file(path, language)
