"""Abstract LLM client interface. All AI services depend on this, not on a
specific backend. Backends: mock, llama_cpp, ollama.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LLMMessage:
    """A single message in a chat conversation."""
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Optional structured fields — backends can populate if the prompt asks
    # for JSON output
    extra: dict = field(default_factory=dict)


class LLMClient(ABC):
    """Abstract LLM client. Swap mock / llama_cpp / ollama by configuration."""

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion for the given chat messages."""

    @abstractmethod
    def health(self) -> bool:
        """Check whether the backend is reachable / loaded."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model name for audit logs."""
