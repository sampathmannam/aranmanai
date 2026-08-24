"""Local LLM client.

Three backends, selected by settings.llm_backend:
- "llama-cpp-python": load a GGUF model file directly, run on RTX 2050
- "ollama":          call an Ollama server (assumes ollama is installed + model pulled)
- "mock":            return canned responses (always works; used for CI / demos)

The same LLMClient API surface is used regardless of backend, so
upgrading the backend requires no changes to callers.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.aranmanai.config import settings
from src.aranmanai.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class LLMResponse:
    """A single LLM response with metadata."""
    text: str
    model: str
    backend: str
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: int
    raw: dict[str, Any] | None = None


class LLMClient:
    """Provider-agnostic local LLM client.

    Construct with: `client = LLMClient()` — picks backend from settings.
    Use: `client.complete(prompt, system=..., temperature=...)`.
    """

    def __init__(self) -> None:
        self._backend = settings.llm_backend
        self._model = None  # lazy init
        self._init_backend()

    def _init_backend(self) -> None:
        """Initialize the active backend. Lazy + best-effort."""
        if self._backend == "llama-cpp-python":
            try:
                from llama_cpp import Llama  # type: ignore
                if settings.llm_model_path and Path(settings.llm_model_path).exists():
                    self._model = Llama(
                        model_path=str(settings.llm_model_path),
                        n_ctx=settings.llm_n_ctx,
                        n_gpu_layers=settings.llm_n_gpu_layers,
                        verbose=False,
                    )
                    log.info("llm.loaded backend=llama-cpp-python model=%s", settings.llm_model_path)
                else:
                    log.warning(
                        "llm.model_path not set or file missing; falling back to mock. "
                        "Set ARANMANAI_LLM_MODEL_PATH to a Phi-3.5-mini-instruct Q4_K_M GGUF."
                    )
                    self._backend = "mock"
            except ImportError:
                log.warning("llama-cpp-python not installed; falling back to mock")
                self._backend = "mock"
            except Exception as e:
                log.error("llm.init failed: %s; falling back to mock", e)
                self._backend = "mock"

        elif self._backend == "ollama":
            try:
                import ollama  # type: ignore
                self._model = ollama.Client(host="http://127.0.0.1:11434")
                log.info("llm.loaded backend=ollama")
            except ImportError:
                log.warning("ollama package not installed; falling back to mock")
                self._backend = "mock"
            except Exception as e:
                log.error("ollama.init failed: %s; falling back to mock", e)
                self._backend = "mock"

        else:  # mock
            log.info("llm.loaded backend=mock (no LLM, returns canned responses)")

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_real(self) -> bool:
        """True if a real model is loaded (not mock)."""
        return self._backend != "mock" and self._model is not None

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        """One-shot completion. Returns LLMResponse with metadata.

        On error, falls back to a structured error message (does NOT
        raise) so callers can surface a graceful failure to the IO.
        """
        temp = temperature if temperature is not None else settings.llm_temperature
        max_tok = max_tokens if max_tokens is not None else settings.llm_max_tokens
        start = time.time()

        try:
            if self._backend == "llama-cpp-python" and self._model is not None:
                return self._complete_llama_cpp(prompt, system, temp, max_tok, stop, start)
            elif self._backend == "ollama" and self._model is not None:
                return self._complete_ollama(prompt, system, temp, max_tok, stop, start)
            else:
                return self._complete_mock(prompt, system, start)
        except Exception as e:
            log.error("llm.complete failed: %s", e)
            elapsed = int((time.time() - start) * 1000)
            return LLMResponse(
                text=f"[LLM error: {type(e).__name__}: {e}. Review required: route to manual draft.]",
                model="error",
                backend=self._backend,
                prompt_tokens=len(prompt.split()),
                completion_tokens=0,
                elapsed_ms=elapsed,
            )

    # --- Backends ---

    def _complete_llama_cpp(
        self, prompt: str, system: str | None, temp: float, max_tok: int,
        stop: list[str] | None, start: float,
    ) -> LLMResponse:
        from llama_cpp import Llama  # type: ignore
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        out = self._model.create_chat_completion(  # type: ignore[union-attr]
            messages=messages,
            temperature=temp,
            max_tokens=max_tok,
            stop=stop or [],
        )
        text = out["choices"][0]["message"]["content"]
        usage = out.get("usage", {})
        return LLMResponse(
            text=text,
            model=str(settings.llm_model_path) if settings.llm_model_path else "llama-cpp",
            backend="llama-cpp-python",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            elapsed_ms=int((time.time() - start) * 1000),
            raw={"model": out.get("model")},
        )

    def _complete_ollama(
        self, prompt: str, system: str | None, temp: float, max_tok: int,
        stop: list[str] | None, start: float,
    ) -> LLMResponse:
        import ollama  # type: ignore
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        out = self._model.chat(  # type: ignore[union-attr]
            model="phi3.5:3.8b-mini-instruct-q4_K_M",
            messages=messages,
            options={"temperature": temp, "num_predict": max_tok, "stop": stop or []},
        )
        text = out["message"]["content"]
        return LLMResponse(
            text=text,
            model="phi3.5:3.8b-mini-instruct-q4_K_M",
            backend="ollama",
            prompt_tokens=out.get("prompt_eval_count", 0),
            completion_tokens=out.get("eval_count", 0),
            elapsed_ms=int((time.time() - start) * 1000),
        )

    def _complete_mock(
        self, prompt: str, system: str | None, start: float,
    ) -> LLMResponse:
        """Mock backend. Returns a structured, schema-valid response
        so callers can be developed + tested without a real LLM.
        The mock response is deterministic (hash-based) so tests are stable.
        """
        h = hashlib.sha256((system or "") .encode() + prompt.encode()).hexdigest()[:8]
        text = (
            f"[MOCK LLM response {h}]\n\n"
            f"System: {system or '(none)'}\n"
            f"Prompt length: {len(prompt)} chars\n"
            f"Prompt preview: {prompt[:200]}{'...' if len(prompt) > 200 else ''}\n\n"
            "This is a canned response from the mock LLM backend. "
            "Replace with a real model by setting ARANMANAI_LLM_BACKEND=llama-cpp-python "
            "and ARANMANAI_LLM_MODEL_PATH to a GGUF file."
        )
        return LLMResponse(
            text=text,
            model="mock-0.1.0",
            backend="mock",
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(text.split()),
            elapsed_ms=int((time.time() - start) * 1000),
        )


# --- Singleton ---

_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Cached LLM client singleton. First call constructs; later calls reuse."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
