"""Multilingual text embeddings for semantic search.

Uses sentence-transformers paraphrase-multilingual-MiniLM-L12-v2
(~120MB, supports 50+ languages incl. Tamil, English, Hindi).

Used by:
- /search: semantic search over cases, witness statements, judgments
- /tamil/case-search: Tamil-language semantic search
- acquittal-risk model: text features (witness statements, evidence)

For v1: 384-dim embeddings, cosine similarity, runs CPU.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from aranmanai.observability import get_logger

log = get_logger(__name__)


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass
class Embedding:
    """A single text embedding."""
    text: str
    vector: np.ndarray  # 384-dim float32
    model: str

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "vector_dim": int(self.vector.shape[0]),
            "model": self.model,
        }


class TextEmbedder:
    """Multilingual sentence embedder with lazy model loading.

    Usage:
        e = TextEmbedder()
        v = e.embed("Vanakkam! Naan case ezhuthuren.")
        # v.vector shape: (384,)
    """

    _MODELS: ClassVar[dict[str, object]] = {}

    def __init__(self, model_name: str | None = None, device: str = "cpu"):
        self.model_name = model_name or DEFAULT_MODEL
        self.device = device
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        if self.model_name in TextEmbedder._MODELS:
            self._model = TextEmbedder._MODELS[self.model_name]
            self._loaded = True
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers not installed. Install: "
                "pip install sentence-transformers==3.0.1"
            ) from e
        log.info("embedder.loading model=%s device=%s", self.model_name, self.device)
        self._model = SentenceTransformer(self.model_name, device=self.device)
        TextEmbedder._MODELS[self.model_name] = self._model
        self._loaded = True
        log.info("embedder.loaded model=%s", self.model_name)

    def embed(self, text: str) -> Embedding:
        """Embed a single text."""
        self._load()
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return Embedding(text=text, vector=vec, model=self.model_name)

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[Embedding]:
        """Embed a list of texts in batches."""
        self._load()
        if not texts:
            return []
        vecs = self._model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        return [Embedding(text=t, vector=v, model=self.model_name) for t, v in zip(texts, vecs, strict=False)]

    def similarity(self, a: Embedding, b: Embedding) -> float:
        """Cosine similarity between two embeddings (assumes normalized)."""
        return float(np.dot(a.vector, b.vector))


def embed_text(text: str, model_name: str | None = None) -> Embedding:
    """Convenience: embed a single text using default model."""
    return TextEmbedder(model_name=model_name).embed(text)


def embed_batch(texts: list[str], model_name: str | None = None, batch_size: int = 32) -> list[Embedding]:
    """Convenience: embed a list of texts."""
    return TextEmbedder(model_name=model_name).embed_batch(texts, batch_size=batch_size)
