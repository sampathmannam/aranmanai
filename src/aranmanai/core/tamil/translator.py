"""Translation: Tamil <-> English <-> Hindi via Helsinki-NLP/Opus-MT.

Helsinki-NLP/Opus-MT models are small (~300MB each) and run on CPU.
Models are loaded lazily on first use. Cached per language pair.

For v1: en<->ta, en<->hi. Direct ta<->hi translation is not always
available; we route through en (en-x then x-en is a known pipeline).

DPDP §8(3): every translation returns input + output text + lang pair
+ model version for audit.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import ClassVar

from aranmanai.observability import get_logger

log = get_logger(__name__)


# Helsinki-NLP/Opus-MT model names per language pair.
# en<->x models exist; ta<->hi is route through en.
_HELSINKI_MODELS = {
    ("en", "ta"): "Helsinki-NLP/opus-mt-en-ta",
    ("ta", "en"): "Helsinki-NLP/opus-mt-ta-en",
    ("en", "hi"): "Helsinki-NLP/opus-mt-en-hi",
    ("hi", "en"): "Helsinki-NLP/opus-mt-hi-en",
    # ta<->hi is routed through en (chain two models)
}


@dataclass
class TranslationResult:
    """Result of a translation call."""
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    model: str
    # SHA-256 of the source text for DPDP §8(3) audit
    source_sha256: str
    # Was this a direct translation or a routed pipeline (e.g. ta->en->hi)?
    routed: bool = False
    via: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "model": self.model,
            "source_sha256": self.source_sha256,
            "routed": self.routed,
            "via": self.via,
        }


class Translator:
    """MarianMT wrapper with lazy model loading and routing.

    Usage:
        t = Translator()
        r = t.translate("Vanakkam! Naan case ezhuthuren.", target="en")
        print(r.translated_text)
    """

    _PIPELINES: ClassVar[dict[str, object]] = {}  # shared cache

    def __init__(self, device: str = "cpu"):
        self.device = device

    def _get_pipeline(self, model_name: str):
        if model_name in Translator._PIPELINES:
            return Translator._PIPELINES[model_name]
        try:
            import torch
            from transformers import MarianMTModel, MarianTokenizer
        except ImportError as e:
            raise RuntimeError(
                "transformers/torch not installed. Install: pip install transformers torch"
            ) from e
        log.info("translator.loading model=%s", model_name)
        tokenizer = MarianTokenizer.from_pretrained(model_name)
        # Use float32 for CPU; use float16 for GPU
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        model = MarianMTModel.from_pretrained(model_name, torch_dtype=dtype)
        model.eval()
        if self.device == "cuda":
            model = model.to("cuda")
        # Build a pipeline-like object
        class _P:
            def __init__(self, tok, mdl):
                self.tok = tok
                self.mdl = mdl
            def __call__(self, text):
                batch = self.tok([text], return_tensors="pt", padding=True, truncation=True, max_length=512)
                if self.device == "cuda":
                    batch = {k: v.to("cuda") for k, v in batch.items()}
                with torch.no_grad():
                    out = self.mdl.generate(**batch, max_length=512, num_beams=2, early_stopping=True)
                return self.tok.decode(out[0], skip_special_tokens=True)
        p = _P(tokenizer, model)
        Translator._PIPELINES[model_name] = p
        log.info("translator.loaded model=%s", model_name)
        return p

    def _resolve_model(self, source: str, target: str) -> tuple[str | None, bool]:
        """Resolve the model name for a (source, target) pair.

        Returns (model_name, routed). routed=True means we need to chain
        through en (e.g. ta->en->hi).
        """
        # No translation needed when source == target
        if source == target:
            return (None, False)
        if (source, target) in _HELSINKI_MODELS:
            return (_HELSINKI_MODELS[(source, target)], False)
        if (target, source) in _HELSINKI_MODELS:
            return (_HELSINKI_MODELS[(target, source)], False)
        # Route through English
        if source != "en" and target != "en":
            return (None, True)
        return (None, False)

    def translate(
        self,
        text: str,
        source: str,
        target: str | None = None,
    ) -> TranslationResult:
        """Translate text from source lang to target lang (or auto-detect target)."""
        if not text or not text.strip():
            return TranslationResult(
                source_text=text,
                translated_text=text,
                source_lang=source,
                target_lang=target or source,
                model="noop",
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        if target is None:
            target = "en" if source != "en" else "ta"

        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        model_name, routed = self._resolve_model(source, target)
        if model_name is None and not routed:
            raise ValueError(f"No model for {source}->{target}")

        if routed:
            # Route through en: source -> en -> target
            r1 = self.translate(text, source, "en")
            r2 = self.translate(r1.translated_text, "en", target)
            return TranslationResult(
                source_text=text,
                translated_text=r2.translated_text,
                source_lang=source,
                target_lang=target,
                model=f"{r1.model}+{r2.model}",
                source_sha256=source_hash,
                routed=True,
                via="en",
            )

        # Direct translation. model_name is guaranteed non-None here: the
        # only way to reach this point is either (a) model_name was resolved
        # above, or (b) routed is True and we already returned above -- the
        # `model_name is None and not routed` guard ruled out the remaining
        # case.
        assert model_name is not None
        pipe = self._get_pipeline(model_name)
        translated = pipe(text)
        return TranslationResult(
            source_text=text,
            translated_text=translated,
            source_lang=source,
            target_lang=target,
            model=model_name,
            source_sha256=source_hash,
        )


def translate(
    text: str,
    source: str,
    target: str = "en",
) -> TranslationResult:
    """Convenience: translate text using default Translator."""
    return Translator().translate(text, source, target)


def batch_translate(
    texts: list[str],
    source: str,
    target: str = "en",
) -> list[TranslationResult]:
    """Translate a batch of texts. Each text is translated independently."""
    t = Translator()
    return [t.translate(x, source, target) for x in texts]
