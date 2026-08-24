"""OllamaLLMClient — talks to a local Ollama server (http://127.0.0.1:11434)."""
from __future__ import annotations

from typing import Any

import httpx

from aranmanai.ai.llm_client import LLMClient, LLMMessage, LLMResponse
from aranmanai.observability import get_logger

log = get_logger(__name__)


class OllamaLLMClient(LLMClient):
    """HTTP client for Ollama's /api/chat endpoint."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "phi3.5:3.8b-mini-instruct-q4_K_M",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout_s: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout_s

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as c:
                r = c.get(f"{self._base_url}/api/tags")
                return r.status_code == 200
        except Exception as e:
            log.warning("llm.ollama.health_failed", error=str(e))
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
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": self._temperature if temperature is None else temperature,
                "num_predict": self._max_tokens if max_tokens is None else max_tokens,
            },
        }
        if stop:
            body["options"]["stop"] = stop
        if json_mode:
            body["format"] = "json"

        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self._base_url}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()

        content = data.get("message", {}).get("content", "")
        return LLMResponse(
            content=content,
            model=self._model_name,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=(data.get("prompt_eval_count", 0) + data.get("eval_count", 0)),
        )
