"""LLM client factory. Reads settings and returns the configured backend."""
from __future__ import annotations

from functools import lru_cache

from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.mock_client import MockLLMClient
from aranmanai.config import get_settings
from aranmanai.observability import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """Get the configured LLM client. Cached for the process lifetime."""
    settings = get_settings()
    backend = settings.llm_backend

    if backend == "mock":
        log.info("llm.factory", backend="mock")
        return MockLLMClient()

    if backend == "llama_cpp":
        # Lazy import — only load if configured
        try:
            from aranmanai.ai.llama_cpp_client import LlamaCppLLMClient
            log.info("llm.factory", backend="llama_cpp", model=str(settings.llm_model_path))
            return LlamaCppLLMClient(
                model_path=settings.llm_model_path,
                n_ctx=settings.llm_n_ctx,
                n_threads=settings.llm_n_threads,
                n_gpu_layers=settings.llm_n_gpu_layers,
            )
        except Exception as e:
            log.warning("llm.factory.llama_cpp_failed", error=str(e), fallback="mock")
            return MockLLMClient()

    if backend == "ollama":
        try:
            from aranmanai.ai.ollama_client import OllamaLLMClient
            log.info("llm.factory", backend="ollama", url=settings.ollama_url, model=settings.ollama_model)
            return OllamaLLMClient(
                base_url=settings.ollama_url,
                model=settings.ollama_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            )
        except Exception as e:
            log.warning("llm.factory.ollama_failed", error=str(e), fallback="mock")
            return MockLLMClient()

    log.warning("llm.factory.unknown_backend", backend=backend, fallback="mock")
    return MockLLMClient()
