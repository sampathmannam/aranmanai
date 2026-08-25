"""Voice API routes: STT, TTS, full pipeline.

Mounted at /api/v1/voice/* via the main app.

Endpoints:
- POST /api/v1/voice/transcribe: file upload -> text (STT only)
- POST /api/v1/voice/pipeline: file upload -> text + segments + language (full VAD+STT)
- POST /api/v1/voice/speak: text -> audio file (TTS)
- GET  /api/v1/voice/capabilities: model + device + languages

All voice data is processed locally. DPDP §8(3): every transcription
returns the audio SHA-256 hash for audit.
"""
from __future__ import annotations

import tempfile
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from aranmanai.config import get_settings
from aranmanai.core.voice import (
    SpeechToText,
    TextToSpeech,
    VoicePipeline,
)
from aranmanai.observability import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


# Module-level singletons (lazy-init on first request)
_stt: SpeechToText | None = None
_pipeline: VoicePipeline | None = None
_tts: TextToSpeech | None = None


def _get_pipeline() -> VoicePipeline:
    global _pipeline
    if _pipeline is None:
        s = get_settings()
        _pipeline = VoicePipeline(stt_model_size=s.whisper_model, device=s.whisper_device)
    return _pipeline


def _get_stt() -> SpeechToText:
    global _stt
    if _stt is None:
        s = get_settings()
        _stt = SpeechToText(model_size=s.whisper_model, device=s.whisper_device)
    return _stt


def _get_tts() -> TextToSpeech:
    global _tts
    if _tts is None:
        _tts = TextToSpeech()
    return _tts


class TranscribeResponse(BaseModel):
    text: str
    language: str
    language_probability: float
    duration_s: float
    model: str
    audio_sha256: str


class PipelineResponse(BaseModel):
    text: str
    language: str
    language_probability: float
    duration_s: float
    num_segments: int
    audio_sha256: str
    segments: list[dict] = Field(default_factory=list)


class SpeakRequest(BaseModel):
    text: str
    voice_id: str | None = None
    rate: int | None = None


class CapabilitiesResponse(BaseModel):
    stt_model: str
    stt_device: str
    tts_available: bool
    supported_languages: list[str]
    max_audio_size_mb: int


# F-9: server-side content sniff. Upload size checks alone let a
# non-audio file renamed to `.wav` through to faster-whisper, which can
# crash or misbehave on garbage bytes. This is a cheap magic-byte check
# on the container signatures of the 4 formats this API documents as
# supported (WAV/MP3/M4A/OGG) — not a full audio decode/validation, and
# deliberately not a new dependency (no python-magic/libmagic) for 4
# well-known, simple-to-sniff signatures.
def _looks_like_audio(data: bytes) -> bool:
    """Best-effort magic-byte sniff for WAV/MP3/M4A(MP4)/OGG container signatures.

    Each check only requires as many bytes as its own signature needs (an
    MP3 ID3 tag is a valid, if minimal, MP3 file at just 10 bytes) rather
    than gating the whole function behind one flat minimum length.
    """
    # WAV: "RIFF"....."WAVE"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE":
        return True
    # OGG: "OggS"
    if len(data) >= 4 and data[0:4] == b"OggS":
        return True
    # M4A / MP4: bytes 4-7 == "ftyp"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return True
    # MP3: ID3 tag, or a frame sync (11 set bits: 0xFF followed by 0xE0-0xFF)
    if len(data) >= 3 and data[0:3] == b"ID3":
        return True
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile = File(..., description="Audio file (WAV/MP3/M4A/OGG)"),
    language: str | None = Form(None, description="ISO 639-1: en/ta/hi/..."),
) -> TranscribeResponse:
    """STT-only: convert audio to text. Returns language + confidence + audio hash."""
    settings = get_settings()
    # Read + size check
    data = await audio.read()
    if len(data) > settings.max_audio_size_mb * 1024 * 1024:
        raise HTTPException(413, f"Audio file too large (>{settings.max_audio_size_mb}MB)")
    # F-9: content sniff — reject non-audio bytes before they reach faster-whisper
    if not _looks_like_audio(data):
        raise HTTPException(415, "File does not appear to be a supported audio format (WAV/MP3/M4A/OGG)")
    # Write to temp file (faster-whisper expects path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tf.write(data)
        tmp_path = Path(tf.name)
    try:
        stt = _get_stt()
        r = stt.transcribe_file(tmp_path, language=language)
        log.info("voice.transcribe lang=%s dur=%.1fs model=%s",
                 r.language, r.duration_s, r.model)
        return TranscribeResponse(
            text=r.text,
            language=r.language,
            language_probability=r.language_probability,
            duration_s=r.duration_s,
            model=r.model,
            audio_sha256=r.audio_sha256,
        )
    finally:
        with suppress(OSError):
            tmp_path.unlink()


@router.post("/pipeline", response_model=PipelineResponse)
async def pipeline(
    audio: UploadFile = File(..., description="Audio file (WAV/MP3/M4A/OGG)"),
    language: str | None = Form(None, description="ISO 639-1: en/ta/hi/..."),
) -> PipelineResponse:
    """Full VAD+STT pipeline: split speech segments, transcribe each, join."""
    settings = get_settings()
    data = await audio.read()
    if len(data) > settings.max_audio_size_mb * 1024 * 1024:
        raise HTTPException(413, f"Audio file too large (>{settings.max_audio_size_mb}MB)")
    # F-9: content sniff — reject non-audio bytes before they reach faster-whisper
    if not _looks_like_audio(data):
        raise HTTPException(415, "File does not appear to be a supported audio format (WAV/MP3/M4A/OGG)")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tf.write(data)
        tmp_path = Path(tf.name)
    try:
        pipe = _get_pipeline()
        r = pipe.transcribe_file(tmp_path, language=language)
        log.info("voice.pipeline lang=%s dur=%.1fs segs=%d",
                 r.language, r.duration_s, r.num_segments)
        return PipelineResponse(
            text=r.text,
            language=r.language,
            language_probability=r.language_probability,
            duration_s=r.duration_s,
            num_segments=r.num_segments,
            audio_sha256=r.audio_sha256,
            segments=[  # flat list of per-segment dicts
                {"start": ps.segments[0]["start"] if ps.segments else 0,
                 "end": ps.segments[0]["end"] if ps.segments else 0,
                 "text": ps.text}
                for ps in r.per_segment
            ],
        )
    finally:
        with suppress(OSError):
            tmp_path.unlink()


@router.post("/speak")
async def speak(req: SpeakRequest):
    """TTS: synthesize text to a WAV file. Returns audio/wav."""
    tts = _get_tts()
    if req.rate:
        tts.rate = req.rate
    if req.voice_id:
        tts.voice_id = req.voice_id
    out_path = Path(tempfile.gettempdir()) / f"aranmanai_tts_{hash(req.text) & 0xffffffff}.wav"
    tts.to_file(out_path, req.text)
    return FileResponse(
        path=str(out_path),
        media_type="audio/wav",
        filename=out_path.name,
    )


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    """Report what the voice module can do."""
    settings = get_settings()
    return CapabilitiesResponse(
        stt_model=settings.whisper_model,
        stt_device=settings.whisper_device,
        tts_available=_get_tts()._ensure_engine() is not None if _tts is not None else False,
        supported_languages=[
            "en", "ta", "hi", "te", "kn", "ml", "mr", "bn", "gu", "pa", "ur",
        ],
        max_audio_size_mb=settings.max_audio_size_mb,
    )
