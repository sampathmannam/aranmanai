"""Run the Aranmanai FastAPI server. Development entry point.

Production should use uvicorn directly:
    uvicorn aranmanai.api.main:app --host 0.0.0.0 --port 8080 --workers 4
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import uvicorn

from aranmanai.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "aranmanai.api.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    main()
