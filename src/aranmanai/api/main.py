"""FastAPI application factory + startup wiring."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from aranmanai.api.v1 import ai, auth, cases, cmc, cms, coordination, dpdp, hearings, pilot, risk, safety, vetting, witnesses
from aranmanai.api import tamil, voice
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

    # CORS - M-1 fix: explicit method list (not ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # M-5: HSTS for production HTTPS (only applied when env=production)
    if settings.environment == "production":
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response

        class HSTSMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                response = await call_next(request)
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                return response

        app.add_middleware(HSTSMiddleware)

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
    app.include_router(coordination.router, prefix="/api/v1/cms", tags=["cms-coordination"])
    app.include_router(cmc.router, prefix="/api/v1", tags=["cmc-loop"])
    app.include_router(risk.router, prefix="/api/v1/risk", tags=["risk"])
    app.include_router(pilot.router, prefix="/api/v1", tags=["pilot"])
    app.include_router(dpdp.router, prefix="/api/v1", tags=["dpdp"])
    app.include_router(vetting.router, prefix="/api/v1", tags=["vetting"])
    app.include_router(safety.router, prefix="/api/v1", tags=["citizen-safety"])
    app.include_router(voice.router, prefix="/api/v1", tags=["voice"])
    app.include_router(tamil.router, prefix="/api/v1", tags=["tamil"])

    # Global error handlers — must register before app is returned
    app.add_exception_handler(IntegrityError, _integrity_handler)
    app.add_exception_handler(ValueError, _value_error_handler)
    from fastapi.exceptions import RequestValidationError
    app.add_exception_handler(RequestValidationError, _value_error_handler)
    app.add_exception_handler(Exception, _generic_500_handler)

    return app


# Global exception handlers — convert DB integrity errors to 4xx instead of 500
async def _integrity_handler(request: Request, exc: Exception) -> JSONResponse:
    log.warning("api.integrity_error path=%s err=%s", request.url.path, str(exc)[:200])
    return JSONResponse(
        status_code=400,
        content={"detail": f"Database integrity error: {str(exc)[:200]}"},
    )


async def _value_error_handler(request: Request, exc: Exception) -> JSONResponse:
    msg = str(exc)[:300]
    # Distinguish "not found" from other validation errors
    if "not found" in msg.lower():
        log.info("api.not_found path=%s err=%s", request.url.path, msg)
        return JSONResponse(status_code=404, content={"detail": msg})
    log.info("api.value_error path=%s err=%s", request.url.path, msg)
    return JSONResponse(status_code=400, content={"detail": msg})


async def _generic_500_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler. Logs the full traceback server-side, returns a
    generic 500 to the client. Prevents stack-trace leakage.

    L-1 fix: returns a fixed string, no exception type name (which can
    reveal internal class names).
    """
    import traceback
    log.error("api.unhandled_500 path=%s err=%s\n%s",
              request.url.path, str(exc)[:200], traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Module-level app for uvicorn
app = create_app()
