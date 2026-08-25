"""Tests for the Tamil module: language detection, translation, embeddings.

These tests cover the module surface. Heavy tests (real translation,
real embeddings) are marked `slow` and skipped by default.
"""
from __future__ import annotations

# --- Detect ---

def test_detect_script_tamil_unicode():
    """Actual Tamil script should be detected as Tamil."""
    from aranmanai.core.tamil import detect_script
    # "Vanakkam" in Tamil: வணக்கம்
    assert detect_script("வணக்கம்") == "Tamil"


def test_detect_script_hindi_unicode():
    """Devanagari script should be detected as Devanagari."""
    from aranmanai.core.tamil import detect_script
    # "Namaste" in Hindi: नमस्ते
    assert detect_script("नमस्ते") == "Devanagari"


def test_detect_script_english_unicode():
    """Latin script should be detected as Latin."""
    from aranmanai.core.tamil import detect_script
    assert detect_script("Hello world") == "Latin"


def test_detect_script_telugu_unicode():
    """Telugu script should be detected as Telugu."""
    from aranmanai.core.tamil import detect_script
    # "Namaskaram" in Telugu: నమస్కారం
    assert detect_script("నమస్కారం") == "Telugu"


def test_detect_language_hindi_script():
    """Devanagari text should be detected as Hindi via script fallback."""
    from aranmanai.core.tamil import detect_language
    lang, conf = detect_language("नमस्ते, आप कैसे हैं?")
    assert lang == "hi"
    assert conf > 0.5


def test_detect_language_tamil_script():
    """Tamil script should be detected as Tamil via script fallback."""
    from aranmanai.core.tamil import detect_language
    lang, conf = detect_language("வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?")
    assert lang == "ta"
    assert conf > 0.5


def test_detect_language_empty():
    """Empty text should return a low-confidence fallback."""
    from aranmanai.core.tamil import detect_language
    lang, conf = detect_language("")
    assert conf == 0.0


def test_language_names_complete():
    """LANGUAGE_NAMES should have the v1 supported languages."""
    from aranmanai.core.tamil import LANGUAGE_NAMES
    for lang in ("en", "ta", "hi"):
        assert lang in LANGUAGE_NAMES


# --- Translator ---

def test_translate_result_dataclass():
    """TranslationResult is a dataclass with the expected fields."""
    from aranmanai.core.tamil import TranslationResult
    r = TranslationResult(
        source_text="hello",
        translated_text="வணக்கம்",
        source_lang="en",
        target_lang="ta",
        model="Helsinki-NLP/opus-mt-en-ta",
        source_sha256="abc",
    )
    assert r.source_text == "hello"
    assert r.translated_text == "வணக்கம்"
    assert r.target_lang == "ta"
    assert r.model == "Helsinki-NLP/opus-mt-en-ta"
    d = r.to_dict()
    assert d["source_text"] == "hello"
    assert d["translated_text"] == "வணக்கம்"


def test_translator_resolve_direct():
    """Direct (source, target) pairs should resolve to a model."""
    from aranmanai.core.tamil.translator import Translator
    t = Translator()
    model, routed = t._resolve_model("en", "ta")
    assert model == "Helsinki-NLP/opus-mt-en-ta"
    assert routed is False
    model, routed = t._resolve_model("hi", "en")
    assert model == "Helsinki-NLP/opus-mt-hi-en"
    assert routed is False


def test_translator_resolve_routed():
    """Pairs without a direct model should be routed through English."""
    from aranmanai.core.tamil.translator import Translator
    t = Translator()
    model, routed = t._resolve_model("ta", "hi")
    assert model is None
    assert routed is True
    # Source = target
    model, routed = t._resolve_model("ta", "ta")
    assert model is None
    assert routed is False


# --- Embeddings ---

def test_embedding_dataclass():
    """Embedding is a dataclass with text + vector + model."""
    import numpy as np

    from aranmanai.core.tamil import Embedding
    e = Embedding(text="hello", vector=np.zeros(384, dtype=np.float32), model="test")
    assert e.text == "hello"
    assert e.vector.shape == (384,)
    assert e.model == "test"


# --- Pipeline ---

def test_pipeline_empty_text():
    """Empty text should return a TamilPipelineResult with no translation/embedding."""
    from aranmanai.core.tamil import TamilPipeline
    p = TamilPipeline()
    r = p.process("", translate=False, embed=False)
    assert r.source_lang == "und"
    assert r.translated_text is None
    assert r.embedding is None
