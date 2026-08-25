"""LLM input sanitization (H-1 fix).

Wraps user-provided text in clear delimiters and neutralizes prompt
injection patterns. Defense-in-depth for the LLM surface across all
AI services.
"""
from __future__ import annotations

import re
from typing import Any


# Characters that often appear in prompt-injection payloads
_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions?\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:prior|above)\b"),
    re.compile(r"(?i)\bsystem\s*:\s*"),
    re.compile(r"(?i)\b<\|.*?\|>"),  # LLM special tokens
    re.compile(r"```"),  # markdown code fences (LLM might treat as new prompt)
]


def sanitize_for_llm(text: str, max_len: int = 100_000) -> str:
    """Sanitize user text before injecting into an LLM prompt.

    H-1 fix: Wraps in <<<>>> delimiters and neutralizes common
    prompt-injection patterns. Does NOT change business logic.
    """
    if not text:
        return ""
    # Truncate first
    t = text[:max_len]
    # Neutralize injection patterns
    for pat in _INJECTION_PATTERNS:
        t = pat.sub("[redacted]", t)
    return t


def delimit(text: str, label: str = "USER_DATA") -> str:
    """Wrap user text in clear delimiters to instruct the LLM to treat it as data.

    H-1 fix.
    """
    sanitized = sanitize_for_llm(text)
    return f"\n<<<{label}>>>\n{sanitized}\n<<<END_{label}>>>\n"
