"""Structured JSON logging for production observability.

In dev: human-readable console output.
In production: JSON lines (one event per line) ready for log aggregation
(Loki, Elastic, CloudWatch, etc). All events include: ts, level, env,
module, msg, plus any structured fields passed via `extra=`.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from src.aranmanai.config import settings


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "env": settings.environment,
            "module": record.name,
            "msg": record.getMessage(),
        }
        # Include any extra fields passed via logger.info("msg", extra={...})
        for k, v in record.__dict__.items():
            if k in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "message", "module",
                "msecs", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName", "taskName",
            ):
                continue
            payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable for development."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        base = f"{ts} {record.levelname:5s} {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"
        return base


def configure_logging() -> None:
    """Wire up root logger. Idempotent. Called from main.py on startup."""
    root = logging.getLogger()
    # Remove any existing handlers (e.g., from reloads, uvicorn defaults)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    if settings.environment == "production":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "sqlalchemy.engine", "multipart"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a module-level logger. Use this everywhere instead of logging.getLogger directly."""
    return logging.getLogger(name)
