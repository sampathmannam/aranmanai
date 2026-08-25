"""Wall-clock elapsed-time measurement. Used to instrument AI drafting calls
so a real district pilot can measure actual time-savings vs. manual drafting
(see docs/superpowers/specs/2026-08-24-aranmanai-plan.md Month-3 milestone).

Deliberately minimal: a `time.perf_counter()` start/end wrapped in a context
manager. No metrics framework, no external dependency, no fabricated numbers
— every value produced here is a real elapsed duration around a real call.
"""
from __future__ import annotations

import time
from types import TracebackType

from aranmanai.observability.logging import get_logger

log = get_logger(__name__)


class Timer:
    """Context manager that measures real wall-clock elapsed time.

    Usage:
        with Timer() as t:
            response = llm.complete(messages)
        elapsed = t.elapsed_seconds  # float, seconds, real measured time

    `elapsed_seconds` is `None` until the `with` block exits, and is always
    a genuine `perf_counter()` delta — never estimated or hardcoded.
    """

    def __init__(self, label: str | None = None) -> None:
        self.label = label
        self._start: float | None = None
        self.elapsed_seconds: float | None = None

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._start is not None
        self.elapsed_seconds = time.perf_counter() - self._start
        if self.label:
            log.debug("timing", label=self.label, elapsed_seconds=self.elapsed_seconds)
