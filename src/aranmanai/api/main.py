"""FastAPI application factory + startup wiring."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aranmanai.api.v1 import ai, auth, cases, cms, hearings, risk, witnesses
from aranmanai.config import get_settings
from aranmanai.db import init_db
from aranmanai.observability import get_logger, setup_logging

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    log.info("app.startup", env=settings.environment, version=settings.version)
    init_db()
    log.info("app.ready", host=settings.host, port=settings.port)
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    """Application factory. Returns a configured FastAPI instance."""
    setup_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Aranmanai (அரண்மனை) — district-scoped conviction-rate management",
        lifespan=_lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name, "version": settings.version}

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "app": settings.app_name,
            "version": settings.version,
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    # Mount v1 routes
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(cases.router, prefix="/api/v1/cases", tags=["cases"])
    app.include_router(witnesses.router, prefix="/api/v1/witnesses", tags=["witnesses"])
    app.include_router(hearings.router, prefix="/api/v1/hearings", tags=["hearings"])
    app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
    app.include_router(cms.router, prefix="/api/v1/cms", tags=["cms"])
    app.include_router(risk.router, prefix="/api/v1/risk", tags=["risk"])

    return app


# Module-level app for uvicorn
app = create_app()
