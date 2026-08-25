"""Silero VAD wrapper for speech segment detection.

Silero V5 is a small (~2 MB) ONNX model. Runs on CPU. Detects speech
vs silence in 30 ms chunks. Used to cut the raw audio into segments
before sending each segment to Whisper (which is slow on long audio).

API: see detect_speech_segments(audio, sample_rate) -> list[Segment].
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class Segment:
    """A continuous speech segment, in audio sample indices."""
    start_sample: int
    end_sample: int
    confidence: float  # 0-1, average VAD confidence for this segment

    @property
    def start_s(self) -> float:
        return self.start_sample  # caller divides by sample_rate

    @property
    def duration_s(self) -> float:
        return (self.end_sample - self.start_sample)


class VoiceActivityDetector:
    """Silero V5 VAD wrapper. Lazy-loads the ONNX model on first use.

    Usage:
        vad = VoiceActivityDetector()
        for seg in vad.detect(audio_np, sample_rate=16000):
            print(seg.start_s, seg.duration_s, seg.confidence)
    """

    _MODEL = None  # shared across instances

    def __init__(self, threshold: float = 0.5, min_speech_ms: int = 250, min_silence_ms: int = 100):
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms
        self.min_silence_ms = min_silence_ms
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            from silero_vad import load_silero_vad  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "silero-vad not installed. Install voice extras: pip install silero-vad==5.1"
            ) from e
        VoiceActivityDetector._MODEL = load_silero_vad(onnx=True)
        self._loaded = True
        log.info("vad.loaded threshold=%s", self.threshold)

    @staticmethod
    def _to_torch(audio: np.ndarray) -> torch.Tensor:  # noqa: F821 -- `torch` is optional/lazy-imported below; safe because `from __future__ import annotations` (line 9) defers this annotation to a string, never evaluated at runtime
        """Convert numpy float32 audio to a torch tensor (silero-vad requirement)."""
        import torch  # type: ignore
        return torch.from_numpy(audio.astype(np.float32, copy=False))

    def detect(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> list[Segment]:
        """Detect speech segments in mono float32 audio.

        Args:
            audio: 1-D numpy array, float32, range [-1, 1], sample_rate Hz
            sample_rate: must be 8000 or 16000 (Silero V5 supported rates)

        Returns:
            List of Segment objects in sample indices.
        """
        self._load()
        assert VoiceActivityDetector._MODEL is not None
        if sample_rate not in (8000, 16000):
            # Silero V5 supports 8k and 16k. Resample if needed.
            audio = _resample(audio, sample_rate, 16000)
            sample_rate = 16000

        # Silero expects int16 or float32; we use float32
        audio = audio.astype(np.float32, copy=False)
        # The ONNX silero VAD accepts 512-sample chunks at 16k (32ms) or
        # 256 at 8k. We chunk and run.
        chunk_size = 512 if sample_rate == 16000 else 256
        n_chunks = len(audio) // chunk_size
        if n_chunks == 0:
            return []

        # Reshape to (n_chunks, chunk_size) and pass as torch tensor
        # (silero-vad requires torch tensors, not numpy)
        import torch
        chunks_np = audio[: n_chunks * chunk_size].reshape(n_chunks, chunk_size)
        chunks = torch.from_numpy(chunks_np)
        # silero_vad returns float in [0,1] per chunk
        probs = VoiceActivityDetector._MODEL(chunks, sample_rate).cpu().numpy()

        # Convert to segments
        segments: list[Segment] = []
        in_speech = False
        seg_start = 0
        seg_probs: list[float] = []

        min_speech_chunks = max(1, self.min_speech_ms * sample_rate // (chunk_size * 1000))
        min_silence_chunks = max(1, self.min_silence_ms * sample_rate // (chunk_size * 1000))

        silence_run = 0
        for i, p in enumerate(probs):
            p_val = float(p) if not hasattr(p, 'item') else float(p.item())
            if p_val >= self.threshold:
                if not in_speech:
                    seg_start = i * chunk_size
                    in_speech = True
                    seg_probs = []
                seg_probs.append(p_val)
                silence_run = 0
            else:
                if in_speech:
                    silence_run += 1
                    seg_probs.append(p_val)
                    if silence_run >= min_silence_chunks:
                        # End the segment
                        seg_end = (i - silence_run + 1) * chunk_size
                        if (i - seg_start // chunk_size) >= min_speech_chunks:
                            segments.append(
                                Segment(
                                    start_sample=seg_start,
                                    end_sample=seg_end,
                                    confidence=sum(seg_probs) / len(seg_probs),
                                )
                            )
                        in_speech = False
                        seg_probs = []
                        silence_run = 0
        # Trailing segment
        if in_speech:
            seg_end = len(audio)
            if (i - seg_start // chunk_size) >= min_speech_chunks:
                segments.append(
                    Segment(
                        start_sample=seg_start,
                        end_sample=seg_end,
                        confidence=sum(seg_probs) / len(seg_probs),
                    )
                )
        return segments


def detect_speech_segments(
    audio: np.ndarray,
    sample_rate: int = 16000,
    threshold: float = 0.5,
) -> list[Segment]:
    """Convenience: detect segments in a numpy array using default VAD."""
    return VoiceActivityDetector(threshold=threshold).detect(audio, sample_rate)


def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Linear resample. Adequate for VAD (not for STT — STT resamples properly)."""
    if src_sr == dst_sr:
        return audio
    duration = len(audio) / src_sr
    n_dst = int(duration * dst_sr)
    src_idx = np.linspace(0, len(audio) - 1, n_dst)
    return np.interp(src_idx, np.arange(len(audio)), audio).astype(np.float32)


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Load a WAV file as float32 mono. Returns (audio, sample_rate)."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(n)
    if sampwidth == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, sr
