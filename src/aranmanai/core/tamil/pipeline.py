"""Tamil (and other Indian language) pipeline: detect -> translate -> embed.

High-level convenience that composes detect + Translator + TextEmbedder
for the common "I have a chunk of text in any Indian language" workflow.

Usage:
    pipe = TamilPipeline()
    result = pipe.process("Vanakkam! Naan case ezhuthuren.",
                          target_lang="en", embed=True)
    # result.source_lang, result.translated_text, result.embedding
"""
from __future__ import annotations

from dataclasses import dataclass

from aranmanai.core.tamil.detect import detect_language
from aranmanai.core.tamil.embeddings import Embedding, TextEmbedder
from aranmanai.core.tamil.translator import TranslationResult, Translator
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class TamilPipelineResult:
    """Result of a Tamil pipeline call."""
    source_text: str
    source_lang: str
    source_confidence: float
    translated_text: str | None
    translation: TranslationResult | None
    embedding: Embedding | None


class TamilPipeline:
    """Detect language, translate (optional), embed (optional)."""

    def __init__(self, device: str = "cpu"):
        self.translator = Translator(device=device)
        self.embedder = TextEmbedder(device=device)

    def process(
        self,
        text: str,
        target_lang: str | None = "en",
        translate: bool = True,
        embed: bool = True,
    ) -> TamilPipelineResult:
        """Process a text: detect language, optionally translate, optionally embed."""
        if not text or not text.strip():
            return TamilPipelineResult(
                source_text=text,
                source_lang="und",
                source_confidence=0.0,
                translated_text=None,
                translation=None,
                embedding=None,
            )

        # 1. Detect language
        source_lang, source_conf = detect_language(text)

        # 2. Translate (optional)
        translation = None
        translated_text = None
        if translate and target_lang and target_lang != source_lang:
            try:
                translation = self.translator.translate(text, source=source_lang, target=target_lang)
                translated_text = translation.translated_text
            except Exception as e:
                log.warning("pipeline.translate_failed err=%s", e)

        # 3. Embed (optional)
        embedding = None
        if embed:
            text_to_embed = translated_text or text
            try:
                embedding = self.embedder.embed(text_to_embed)
            except Exception as e:
                log.warning("pipeline.embed_failed err=%s", e)

        return TamilPipelineResult(
            source_text=text,
            source_lang=source_lang,
            source_confidence=source_conf,
            translated_text=translated_text,
            translation=translation,
            embedding=embedding,
        )
