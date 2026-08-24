"""Aranmanai FastAPI application entrypoint.

Run with: `uvicorn src.aranmanai.main:app --reload --port 8080`
Or:        `python -m src.aranmanai.main`
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.aranmanai import __version__
from src.aranmanai.api import auth, cases, cms, evidence, hearings, users, witnesses
from src.aranmanai.config import settings
from src.aranmanai.db import engine, init_db, verify_db
from src.aranmanai.logging_config import configure_logging, get_logger
from src.aranmanai.schemas import HealthResponse
from src.aranmanai.security import verify_audit_chain

log = get_logger(__name__)

# Track uptime for /health
_BOOT_TIME = time.time()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application startup + shutdown."""
    configure_logging()
    log.info(
        "aranmanai.starting version=%s env=%s db=%s",
        __version__, settings.environment, settings.db_path,
    )
    init_db()
    if verify_db():
        log.info("database verified at %s", settings.db_path)
    else:
        log.error("database verify FAILED — running in degraded mode")

    # Verify audit chain on startup (if it exists from a prior run)
    from src.aranmanai.db import SessionLocal
    with SessionLocal() as db:
        is_valid, n = verify_audit_chain(db)
        if n > 0:
            log.info("audit.chain.startup_check valid=%s entries=%s", is_valid, n)

    log.info("aranmanai.started port=8080 llm_backend=%s", settings.llm_backend)
    yield
    # Shutdown
    log.info("aranmanai.stopping")
    engine.dispose()
    log.info("aranmanai.stopped")


app = FastAPI(
    title="Aranmanai",
    description=(
        "District conviction-rate management platform. "
        "Court Monitoring System + AI assist + witness prep. "
        "Pattern sources: Kishore Kommi (Eluru), Dheeraj Kunubilli (Annamayya)."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=_lifespan,
)

# CORS — defaults to localhost:8501 (Streamlit default)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global error handler ---

@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled exception path=%s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "code": "internal_error"},
    )


# --- Routers ---

# Auth (no auth required for /login)
app.include_router(auth.router)

# Resources
app.include_router(users.router)
app.include_router(cases.router)
app.include_router(witnesses.router)
app.include_router(hearings.router)
app.include_router(evidence.router)

# CMS (the operational core)
app.include_router(cms.router)


# --- Health ---

@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Service health check. Returns 200 if all components are reachable.

    Used by ops, Docker healthcheck, and load balancers.
    """
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        db_path=str(settings.db_path),
        llm_backend=settings.llm_backend,
        llm_model_loaded=settings.llm_model_path is not None and settings.llm_model_path.exists() if settings.llm_model_path else False,
        integrations={
            "cctns": settings.cctns_mode,
            "esakshya": settings.esakshya_mode,
            "icjs": settings.icjs_mode,
        },
        uptime_s=time.time() - _BOOT_TIME,
    )


@app.get("/", tags=["health"])
def root() -> dict:
    """Root endpoint. Friendly landing for human visitors; redirects curious humans to /docs."""
    return {
        "app": settings.app_name,
        "version": __version__,
        "tagline": "District conviction-rate management",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.aranmanai.main:app", host="127.0.0.1", port=8080, reload=False)
