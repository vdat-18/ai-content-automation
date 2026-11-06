"""Low-cardinality Prometheus metrics for API and durable execution."""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Histogram,
    ProcessCollector,
    make_asgi_app,
)
from prometheus_client import Counter as PrometheusCounter

REGISTRY = CollectorRegistry(auto_describe=True)
ProcessCollector(registry=REGISTRY)

HTTP_REQUESTS = PrometheusCounter(
    "aic_http_requests_total",
    "HTTP requests completed by route template.",
    ("service", "method", "route", "status"),
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "aic_http_request_duration_seconds",
    "HTTP request duration by route template.",
    ("service", "method", "route"),
    registry=REGISTRY,
)
HTTP_IN_FLIGHT = Gauge(
    "aic_http_requests_in_flight",
    "HTTP requests currently being handled.",
    ("service", "method"),
    registry=REGISTRY,
)
READINESS = Gauge(
    "aic_dependency_ready",
    "Whether a runtime dependency is ready.",
    ("service", "dependency"),
    registry=REGISTRY,
)
ARTIFACT_PUBLICATIONS = PrometheusCounter(
    "aic_artifact_publications_total",
    "Artifact publication attempts by kind and outcome.",
    ("kind", "outcome"),
    registry=REGISTRY,
)
ARTIFACT_BYTES = Histogram(
    "aic_artifact_size_bytes",
    "Published artifact size by kind.",
    ("kind",),
    buckets=(1_024, 10_240, 102_400, 1_048_576, 10_485_760, 104_857_600, 1_073_741_824),
    registry=REGISTRY,
)
ARTIFACT_DURATION = Histogram(
    "aic_artifact_publication_duration_seconds",
    "Artifact publication duration by kind.",
    ("kind",),
    registry=REGISTRY,
)
AI_REQUESTS = PrometheusCounter(
    "aic_ai_requests_total",
    "AI operations by bounded operation, backend, model and outcome.",
    ("operation", "backend", "model", "outcome"),
    registry=REGISTRY,
)
AI_REQUEST_DURATION = Histogram(
    "aic_ai_request_duration_seconds",
    "AI operation duration by bounded operation, backend and model.",
    ("operation", "backend", "model"),
    registry=REGISTRY,
)
AI_INPUT_TOKENS = PrometheusCounter(
    "aic_ai_input_tokens_total",
    "Input tokens reported by AI operations.",
    ("operation", "model"),
    registry=REGISTRY,
)
AI_OUTPUT_TOKENS = PrometheusCounter(
    "aic_ai_output_tokens_total",
    "Output tokens reported by AI operations.",
    ("operation", "model"),
    registry=REGISTRY,
)
AI_GENERATED_OUTPUTS = PrometheusCounter(
    "aic_ai_generated_outputs_total",
    "Generated media outputs by operation, model and outcome.",
    ("operation", "model", "outcome"),
    registry=REGISTRY,
)
AI_GENERATED_OUTPUT_BYTES = Histogram(
    "aic_ai_generated_output_bytes",
    "Generated media output size by operation and model.",
    ("operation", "model"),
    buckets=(102_400, 512_000, 1_048_576, 5_242_880, 10_485_760, 31_457_280),
    registry=REGISTRY,
)
AI_SEMANTIC_REVIEWS = PrometheusCounter(
    "aic_ai_semantic_reviews_total",
    "Semantic review outcomes by model and operating mode.",
    ("model", "outcome", "mode"),
    registry=REGISTRY,
)
AI_HUMAN_EVALUATIONS = PrometheusCounter(
    "aic_ai_human_evaluations_total",
    "Final human decisions compared with the recorded semantic outcome.",
    ("decision", "semantic_outcome"),
    registry=REGISTRY,
)


def metrics_asgi_app():
    """Return the private ASGI metrics endpoint."""
    return make_asgi_app(registry=REGISTRY)


__all__ = [
    "AI_GENERATED_OUTPUT_BYTES",
    "AI_GENERATED_OUTPUTS",
    "AI_HUMAN_EVALUATIONS",
    "AI_INPUT_TOKENS",
    "AI_OUTPUT_TOKENS",
    "AI_REQUEST_DURATION",
    "AI_REQUESTS",
    "AI_SEMANTIC_REVIEWS",
    "ARTIFACT_BYTES",
    "ARTIFACT_DURATION",
    "ARTIFACT_PUBLICATIONS",
    "HTTP_DURATION",
    "HTTP_IN_FLIGHT",
    "HTTP_REQUESTS",
    "READINESS",
    "REGISTRY",
    "metrics_asgi_app",
]
