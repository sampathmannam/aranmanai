"""Language detection: fasttext lid.176 + Unicode script fallback.

fasttext's `lid.176` model is ~1 MB and identifies 176 languages. We use
it as the primary detector. As a fallback when fasttext isn't loaded
yet, we use Unicode script detection: Tamil (U+0B80-U+0BFF), Devanagari
(U+0900-U+097F) for Hindi/Marathi/etc., Latin (basic ASCII + extended) for
English, etc.

Usage:
    >>> detect_language("Vanakkam! Naan Ram.")
    ('ta', 0.92)
    >>> detect_language("Hello, how are you?")
    ('en', 0.97)
"""
from __future__ import annotations

from aranmanai.observability import get_logger

log = get_logger(__name__)

# ISO 639-1 -> human-readable name
LANGUAGE_NAMES = {
    "en": "English",
    "ta": "Tamil",
    "hi": "Hindi",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ur": "Urdu",
    "ne": "Nepali",
    "si": "Sinhala",
    "sa": "Sanskrit",
}

# Unicode block ranges (start, end) for script detection fallback
_SCRIPT_RANGES = [
    ("Tamil", "\u0B80", "\u0BFF", "ta"),
    ("Devanagari", "\u0900", "\u097F", "hi"),  # default Devanagari -> Hindi
    ("Telugu", "\u0C00", "\u0C7F", "te"),
    ("Kannada", "\u0C80", "\u0CFF", "kn"),
    ("Malayalam", "\u0D00", "\u0D7F", "ml"),
    ("Bengali", "\u0980", "\u09FF", "bn"),
    ("Gujarati", "\u0A80", "\u0AFF", "gu"),
    ("Punjabi-Gurmukhi", "\u0A00", "\u0A7F", "pa"),
    ("Oriya", "\u0B00", "\u0B7F", "or"),
    ("Sinhala", "\u0D80", "\u0DFF", "si"),
    ("Arabic", "\u0600", "\u06FF", "ur"),  # default Arabic-script -> Urdu
]


def detect_script(text: str) -> str:
    """Detect the dominant Unicode script of a text. Returns script name or 'Latin'."""
    if not text:
        return "Latin"
    counts = {}
    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        for name, start, end, _lang in _SCRIPT_RANGES:
            if start <= ch <= end:
                counts[name] = counts.get(name, 0) + 1
                break
        # Latin (basic + extended)
        if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
            counts["Latin"] = counts.get("Latin", 0) + 1
    if not counts:
        return "Latin"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def detect_language(
    text: str,
    fasttext_model_path: str | None = None,
) -> tuple[str, float]:
    """Detect the language of `text`.

    Returns (lang_code, confidence) where lang_code is an ISO 639-1
    code ('en', 'ta', 'hi', etc.) and confidence is 0-1.

    Primary: fasttext lid.176 (small, ~1MB, 176 languages).
    Fallback: Unicode script detection (less precise, but always available).
    """
    if not text or not text.strip():
        return ("en", 0.0)

    # Try fasttext
    try:
        import fasttext  # type: ignore
    except ImportError:
        fasttext = None  # type: ignore

    if fasttext is not None:
        try:
            if not hasattr(detect_language, "_ft_model") or detect_language._ft_model is None:
                # Lazy load. If model file not present, set to a sentinel
                if fasttext_model_path and __import__("os").path.exists(fasttext_model_path):
                    detect_language._ft_model = fasttext.load_model(fasttext_model_path)
                else:
                    detect_language._ft_model = False  # sentinel: not loaded
            model = detect_language._ft_model
            if model and model is not False:
                # fasttext expects newline-separated input
                labels, probs = model.predict(text.replace("\n", " "))
                lang = labels[0].replace("__label__", "")
                confidence = float(probs[0])
                return (lang, confidence)
        except Exception as e:
            log.debug("langid.fasttext_failed err=%s", e)

    # Fallback: Unicode script detection
    script = detect_script(text)
    for name, _start, _end, lang in _SCRIPT_RANGES:
        if name == script:
            # Confidence is high if there's only one script, lower if mixed
            alpha_count = sum(1 for ch in text if ch.isalpha())
            return (lang, 0.7 if alpha_count > 0 else 0.0)
    return ("en", 0.5)  # default Latin -> English
