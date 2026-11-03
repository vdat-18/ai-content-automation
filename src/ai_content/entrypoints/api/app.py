"""FastAPI application for the affiliate content dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_content.platform.observability import (
    READINESS,
    HttpObservabilityMiddleware,
    configure_observability,
    instrument_fastapi,
    metrics_asgi_app,
)
from ai_content.settings import ApplicationSettings

from .ai_usage import router as ai_usage_router
from .creative_knowledge import router as creative_knowledge_router
from .dependencies import check_runtime_readiness, get_runtime_settings, lifespan
from .notifications import router as notifications_router
from .products import router as products_router

_APPLICATION_SETTINGS = ApplicationSettings()
_OBSERVABILITY_SETTINGS = _APPLICATION_SETTINGS.observability("aicontent-api")
_OBSERVABILITY_RUNTIME = configure_observability(_OBSERVABILITY_SETTINGS)


class HealthResponse(BaseModel):
    """Simple service health check payload."""

    status: str = "ok"
    service: str = "affiliate-content-api"
    checks: dict[str, str] = Field(default_factory=dict)


app = FastAPI(
    title="Affiliate Content API",
    version="0.1.0",
    description="Collects TikTok Shop products and Pinterest references for affiliate content.",
    lifespan=lifespan,
)
app.state.observability_settings = _OBSERVABILITY_SETTINGS
app.state.observability_runtime = _OBSERVABILITY_RUNTIME
app.add_middleware(
    HttpObservabilityMiddleware,
    service_name=_OBSERVABILITY_SETTINGS.service_name,
)
app.mount("/internal/metrics", metrics_asgi_app(), name="internal-metrics")
app.include_router(ai_usage_router)
app.include_router(creative_knowledge_router)
app.include_router(notifications_router)
app.include_router(products_router)


def _configure_cors(application: FastAPI) -> None:
    """Allow local browser origin access during dashboard development."""
    allow_origins = [
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    allow_pattern = _APPLICATION_SETTINGS.cors_allow_origin
    if allow_pattern:
        allow_origins.append(allow_pattern)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report process liveness without touching external dependencies."""
    return HealthResponse(checks={"process": "ok"})


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    """Report whether the data directory and the selected database are usable."""
    container = getattr(request.app.state, "postgres_runtime", None)
    database = container.database if container is not None else None
    readiness = await check_runtime_readiness(get_runtime_settings(), database)
    for dependency, value in readiness.checks.items():
        READINESS.labels(
            service=_OBSERVABILITY_SETTINGS.service_name,
            dependency=dependency,
        ).set(value == "ok")
    response = HealthResponse(
        status="ok" if readiness.ready else "not_ready",
        checks=readiness.checks,
    )
    if readiness.ready:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )


class DashboardStaticFiles(StaticFiles):
    """Serve the React entrypoint for client-side dashboard routes."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            return await super().get_response("index.html", scope)


def _mount_frontend(application: FastAPI) -> None:
    """Serve the production dashboard build when it exists."""
    frontend_dir = Path(__file__).resolve().parents[4] / "frontend" / "dist"
    if frontend_dir.is_dir():
        application.mount(
            "/dashboard",
            DashboardStaticFiles(directory=str(frontend_dir), html=True),
            name="dashboard",
        )
    else:
        logger.debug("No dashboard frontend found at {}", frontend_dir)


_configure_cors(app)
_mount_frontend(app)
instrument_fastapi(app, _OBSERVABILITY_SETTINGS)


def create_app() -> FastAPI:
    """Factory for external callers (tests / app factories)."""
    return app


app.add_exception_handler(
    ValueError,
    lambda _request, exc: JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    ),
)
