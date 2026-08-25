"""Structured logging setup. JSON in production, text in development."""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from aranmanai.config import get_settings

_CONFIGURED = False


def setup_logging() -> None:
    """Configure structlog + stdlib logging once. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_format == "json":
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ]

    # SIM115: this file handle is intentionally NOT opened in a `with`
    # block -- structlog.WriteLoggerFactory holds it open for every log
    # write over the process's whole lifetime (same pattern as passing
    # sys.stderr above), not a single short-lived operation. Closing it
    # on function exit would break all subsequent logging.
    log_file_handle = (
        open(settings.log_file, "a", encoding="utf-8") if settings.log_file else None  # noqa: SIM115
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr)
        if log_file_handle is None
        else structlog.WriteLoggerFactory(file=log_file_handle),
        cache_logger_on_first_use=True,
    )

    # Stdlib logging — route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )
    # Quiet noisy libraries
    for noisy in ["httpx", "httpcore", "chromadb", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured structlog logger."""
    if not _CONFIGURED:
        setup_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()
