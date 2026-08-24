"""Aranmanai voice module: STT (Whisper), VAD (Silero), and TTS (pyttsx3/SAPI).

Voice-first interface for IOs and SPs in the field. Push-to-talk to:
- File a complaint (Tamil/English/Hindi)
- Add a case diary entry
- Search cases / witnesses
- Dictate witness prep notes

Components:
- VAD: Silero V5 (~2 MB ONNX, runs CPU, ~1ms per 30ms chunk)
- STT: faster-whisper (CTranslate2, runs on CPU + GPU, multilingual)
- TTS: pyttsx3 (offline, Windows SAPI / macOS say / Linux espeak) for readouts
- Pipeline: VAD-segments raw audio → STT per segment → text

Design principles:
- Local-only: no cloud upload of voice data
- DPDP §8(3) compliant: every transcription logged with hash
- Works on RTX 2050 4GB (Whisper tiny/base/small) and CPU fallback
- Tamil + English + Hindi out of the box (Whisper is trained on 99 languages)
"""
from aranmanai.core.voice.vad import VoiceActivityDetector, detect_speech_segments, load_wav
from aranmanai.core.voice.stt import SpeechToText, TranscriptionResult, transcribe_wav
from aranmanai.core.voice.tts import TextToSpeech
from aranmanai.core.voice.pipeline import VoicePipeline, voice_to_text, PipelineResult

__all__ = [
    "VoiceActivityDetector",
    "detect_speech_segments",
    "load_wav",
    "SpeechToText",
    "TranscriptionResult",
    "transcribe_wav",
    "TextToSpeech",
    "VoicePipeline",
    "voice_to_text",
    "PipelineResult",
]
