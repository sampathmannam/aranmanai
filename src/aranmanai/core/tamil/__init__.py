"""Aranmanai Tamil module: language detection, translation, embeddings.

For v1, supports Tamil (ta), English (en), Hindi (hi) with these components:
- Language detection: fasttext lid.176 (small, ~1MB) with Unicode-script fallback
- Translation: Helsinki-NLP/Opus-MT models (Tamil↔English, Hindi↔English)
  via HuggingFace transformers MarianMT (small, fast, runs CPU)
- Embeddings: sentence-transformers paraphrase-multilingual-MiniLM-L12-v2
  (~120MB, 50+ languages incl. Tamil)

All local. No cloud calls. DPDP §8(3) audit on every translation.
"""
from aranmanai.core.tamil.detect import detect_language, detect_script, LANGUAGE_NAMES
from aranmanai.core.tamil.translator import Translator, translate, batch_translate, TranslationResult
from aranmanai.core.tamil.embeddings import TextEmbedder, embed_text, embed_batch, Embedding
from aranmanai.core.tamil.pipeline import TamilPipeline, TamilPipelineResult

__all__ = [
    "detect_language",
    "detect_script",
    "LANGUAGE_NAMES",
    "Translator",
    "translate",
    "batch_translate",
    "TranslationResult",
    "TextEmbedder",
    "embed_text",
    "embed_batch",
    "Embedding",
    "TamilPipeline",
    "TamilPipelineResult",
]
