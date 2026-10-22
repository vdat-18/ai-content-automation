"""OpenTelemetry process bootstrap and bounded instrumentation helpers."""

from __future__ import annotations

import sys
from base64 import b64encode
from dataclasses import dataclass
from typing import Any

from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from sqlalchemy.ext.asyncio import AsyncEngine

from .ai import configure_ai_observability
from .config import ObservabilitySettings

_provider: TracerProvider | None = None
_httpx_instrumented = False
_botocore_instrumented = False


class _AIOnlySpanExporter(SpanExporter):
    """Forward only explicit AI observations to the Langfuse OTLP endpoint."""

    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter

    def export(self, spans) -> SpanExportResult:
        selected = tuple(span for span in spans if span.name.startswith("aic.ai."))
        if not selected:
            return SpanExportResult.SUCCESS
        return self._exporter.export(selected)

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._exporter.force_flush(timeout_millis)


@dataclass(frozen=True)
class ObservabilityRuntime:
    """Own exporter flushing for one process."""

    provider: TracerProvider | None

    def shutdown(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()


def configure_observability(settings: ObservabilitySettings) -> ObservabilityRuntime:
    """Configure one global tracer provider and outbound client instrumentation."""
    global _botocore_instrumented, _httpx_instrumented, _provider
    _configure_logging(settings)
    configure_ai_observability(settings.ai_telemetry_enabled)
    if not settings.enabled:
        return ObservabilityRuntime(None)
    if _provider is not None:
        return ObservabilityRuntime(_provider)

    provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: settings.service_name,
                DEPLOYMENT_ENVIRONMENT: settings.deployment_environment,
            }
        ),
        sampler=ParentBased(TraceIdRatioBased(settings.trace_sample_ratio)),
    )
    assert settings.otlp_traces_endpoint is not None
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otlp_traces_endpoint,
                timeout=5,
            )
        )
    )
    if settings.langfuse_otlp_endpoint is not None:
        assert settings.langfuse_public_key is not None
        assert settings.langfuse_secret_key is not None
        credentials = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}"
        authorization = "Basic " + b64encode(credentials.encode("utf-8")).decode("ascii")
        provider.add_span_processor(
            BatchSpanProcessor(
                _AIOnlySpanExporter(
                    OTLPSpanExporter(
                        endpoint=settings.langfuse_otlp_endpoint,
                        headers={"Authorization": authorization},
                        timeout=5,
                    )
                )
            )
        )
    trace.set_tracer_provider(provider)
    _provider = provider
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _httpx_instrumented = True
    if not _botocore_instrumented:
        BotocoreInstrumentor().instrument(tracer_provider=provider)
        _botocore_instrumented = True
    return ObservabilityRuntime(provider)


def instrument_fastapi(application: Any, settings: ObservabilitySettings) -> None:
    """Instrument FastAPI before its middleware stack starts serving requests."""
    if not settings.enabled:
        return
    FastAPIInstrumentor.instrument_app(
        application,
        tracer_provider=_provider,
        excluded_urls="/health/live,/health/ready,/internal/metrics",
        exclude_spans=["receive", "send"],
    )


def instrument_sqlalchemy(engine: AsyncEngine, settings: ObservabilitySettings) -> None:
    """Instrument one SQLAlchemy engine without recording SQL parameters."""
    if not settings.enabled:
        return
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        tracer_provider=_provider,
        enable_commenter=False,
    )


def current_trace_id() -> str | None:
    """Return the active W3C trace identifier, if a sampled or unsampled span exists."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"{context.trace_id:032x}"


def set_span_attributes(**attributes: str | int | float | bool | None) -> None:
    """Attach bounded business identifiers to the active span."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def _configure_logging(settings: ObservabilitySettings) -> None:
    if settings.log_format != "json":
        return
    logger.remove()
    logger.add(sys.stderr, serialize=True, level="INFO", backtrace=False, diagnose=False)


__all__ = [
    "ObservabilityRuntime",
    "configure_observability",
    "current_trace_id",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "set_span_attributes",
]
