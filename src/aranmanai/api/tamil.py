"""Tamil/Indian language API routes: language detect, translation, embeddings.

Mounted at /api/v1/tamil/* via the main app.

Endpoints:
- POST /api/v1/tamil/detect: text -> language code + confidence
- POST /api/v1/tamil/translate: text -> translated text + audit
- POST /api/v1/tamil/embed: text -> 384-dim vector (for semantic search)
- POST /api/v1/tamil/pipeline: text -> detect + translate + embed (one shot)
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from aranmanai.core.tamil import (
    TamilPipeline,
    TextEmbedder,
    Translator,
    detect_language,
)
from aranmanai.observability import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/tamil", tags=["tamil"])

# Lazy singletons
_translator: Translator | None = None
_embedder: TextEmbedder | None = None
_pipeline: TamilPipeline | None = None


def _get_translator() -> Translator:
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def _get_embedder() -> TextEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedder()
    return _embedder


def _get_pipeline() -> TamilPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = TamilPipeline()
    return _pipeline


class DetectRequest(BaseModel):
    text: str


class DetectResponse(BaseModel):
    language: str
    language_name: str
    confidence: float
    script: str
    model: str = "script+fasttext-fallback"


class TranslateRequest(BaseModel):
    text: str
    source: str
    target: str = "en"


class TranslateResponse(BaseModel):
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    model: str
    source_sha256: str
    routed: bool = False
    via: str | None = None


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    text: str
    vector: list[float]
    vector_dim: int
    model: str


class PipelineRequest(BaseModel):
    text: str
    target_lang: str = "en"
    translate: bool = True
    embed: bool = True


class PipelineResponse(BaseModel):
    source_text: str
    source_lang: str
    source_confidence: float
    translated_text: str | None = None
    embedding: list[float] | None = None
    model: str = "Helsinki-NLP/opus-mt + paraphrase-multilingual-MiniLM-L12-v2"


@router.post("/detect", response_model=DetectResponse)
async def detect(req: DetectRequest) -> DetectResponse:
    """Detect the language of a text."""
    from aranmanai.core.tamil import LANGUAGE_NAMES, detect_script
    lang, conf = detect_language(req.text)
    script = detect_script(req.text)
    return DetectResponse(
        language=lang,
        language_name=LANGUAGE_NAMES.get(lang, lang),
        confidence=conf,
        script=script,
    )


@router.post("/translate", response_model=TranslateResponse)
async def translate_text(req: TranslateRequest) -> TranslateResponse:
    """Translate text from source language to target language."""
    t = _get_translator()
    r = t.translate(req.text, source=req.source, target=req.target)
    return TranslateResponse(
        source_text=r.source_text,
        translated_text=r.translated_text,
        source_lang=r.source_lang,
        target_lang=r.target_lang,
        model=r.model,
        source_sha256=r.source_sha256,
        routed=r.routed,
        via=r.via,
    )


@router.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest) -> EmbedResponse:
    """Embed a text into a 384-dim vector for semantic search."""
    e = _get_embedder()
    em = e.embed(req.text)
    return EmbedResponse(
        text=em.text,
        vector=em.vector.tolist(),
        vector_dim=int(em.vector.shape[0]),
        model=em.model,
    )


@router.post("/pipeline", response_model=PipelineResponse)
async def pipeline(req: PipelineRequest) -> PipelineResponse:
    """One-shot: detect language, translate, embed."""
    p = _get_pipeline()
    r = p.process(
        req.text,
        target_lang=req.target_lang,
        translate=req.translate,
        embed=req.embed,
    )
    return PipelineResponse(
        source_text=r.source_text,
        source_lang=r.source_lang,
        source_confidence=r.source_confidence,
        translated_text=r.translated_text,
        embedding=r.embedding.vector.tolist() if r.embedding else None,
    )
