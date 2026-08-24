"""LlamaCppLLMClient — wraps llama-cpp-python. Local GGUF inference."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aranmanai.ai.llm_client import LLMClient, LLMMessage, LLMResponse
from aranmanai.observability import get_logger

log = get_logger(__name__)


class LlamaCppLLMClient(LLMClient):
    """Local GGUF model served via llama-cpp-python.

    Runs the model in-process (no background server). n_gpu_layers=0 forces
    CPU; >0 offloads that many layers to CUDA.
    """

    def __init__(
        self,
        model_path: Path,
        n_ctx: int = 4096,
        n_threads: int = 8,
        n_gpu_layers: int = 35,
        verbose: bool = False,
    ) -> None:
        self._model_path = Path(model_path)
        self._n_ctx = n_ctx
        self._n_threads = n_threads
        self._n_gpu_layers = n_gpu_layers
        self._verbose = verbose
        self._llm: Any = None  # lazy load
        self._model_name = self._model_path.stem

    def _load(self) -> None:
        if self._llm is not None:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Model file not found: {self._model_path}. "
                "Download a GGUF (e.g. Qwen2.5-1.5B-Instruct-Q4_K_M) "
                "into models/llm/<name>/ or set ARANMANAI_LLM_BACKEND=mock."
            )
        from llama_cpp import Llama
        log.info("llm.llama_cpp.loading", model=str(self._model_path), n_ctx=self._n_ctx, n_gpu_layers=self._n_gpu_layers)
        self._llm = Llama(
            model_path=str(self._model_path),
            n_ctx=self._n_ctx,
            n_threads=self._n_threads,
            n_gpu_layers=self._n_gpu_layers,
            verbose=self._verbose,
        )
        log.info("llm.llama_cpp.loaded")

    @property
    def model_name(self) -> str:
        return self._model_name

    def health(self) -> bool:
        try:
            self._load()
            return self._llm is not None
        except Exception as e:
            log.warning("llm.llama_cpp.health_failed", error=str(e))
            return False

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        self._load()
        chat_messages = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict[str, Any] = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if stop:
            kwargs["stop"] = stop
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        result = self._llm.create_chat_completion(messages=chat_messages, **kwargs)
        choice = result["choices"][0]
        content = choice["message"]["content"]
        usage = result.get("usage", {})
        return LLMResponse(
            content=content,
            model=self._model_name,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
