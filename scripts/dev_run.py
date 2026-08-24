"""Local dev convenience: run the FastAPI app with auto-reload.

Usage:
    python scripts/dev_run.py
    python scripts/dev_run.py --port 8080
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make src importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn

from src.aranmanai.config import settings


def main() -> int:
    p = argparse.ArgumentParser(description="Aranmanai dev server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--no-reload", action="store_true")
    args = p.parse_args()

    settings.ensure_dirs()
    print(f"Aranmanai v{settings.app_version} (env={settings.environment}, llm={settings.llm_backend})")
    print(f"  DB:  {settings.db_path}")
    print(f"  API: http://{args.host}:{args.port}")
    print(f"  Docs: http://{args.host}:{args.port}/docs")
    print(f"  Health: http://{args.host}:{args.port}/health")

    uvicorn.run(
        "src.aranmanai.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
