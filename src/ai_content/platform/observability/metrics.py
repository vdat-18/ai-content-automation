"""Low-cardinality Prometheus metrics for API and durable execution."""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Histogram,
    ProcessCollector,
    make_asgi_app,
    multiprocess,
    start_http_server,
)
from prometheus_client import Counter as PrometheusCounter

if TYPE_CHECKING:
    from ai_content.platform.execution.models import CommandStatus, ExecutionCommand

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
COMMANDS = Gauge(
    "aic_execution_commands",
    "Current durable commands by queue and status.",
    ("queue", "status"),
    registry=REGISTRY,
)
OLDEST_COMMAND_AGE = Gauge(
    "aic_execution_oldest_active_command_age_seconds",
    "Age of the oldest non-terminal command by queue.",
    ("queue",),
    registry=REGISTRY,
)
COMMAND_ATTEMPTS = PrometheusCounter(
    "aic_execution_attempts_total",
    "Command dispatch attempts by command type and outcome.",
    ("command", "outcome"),
    registry=REGISTRY,
)
COMMAND_DURATION = Histogram(
    "aic_execution_duration_seconds",
    "Command dispatch duration by command type.",
    ("command",),
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
CREATIVE_AUTOMATION_STEP_DURATION = Histogram(
    "aic_creative_automation_step_duration_seconds",
    "Creative automation business-step duration by step and outcome.",
    ("step", "outcome"),
    registry=REGISTRY,
)
CREATIVE_AUTOMATION_TOTAL_DURATION = Histogram(
    "aic_creative_automation_total_duration_seconds",
    "Creative automation end-to-end duration by route and outcome.",
    ("route", "outcome"),
    registry=REGISTRY,
)

_COMMAND_STATUSES = (
    "pending",
    "running",
    "retry_wait",
    "cancel_requested",
    "cancelled",
    "completed",
    "failed",
)
_TERMINAL_STATUSES = {"cancelled", "completed", "failed"}


class CommandStatusReader(Protocol):
    async def list(
        self,
        status: CommandStatus | None = None,
        workflow_run_id: str | None = None,
    ) -> list[ExecutionCommand]: ...


class CommandMetricsSampler:
    """Rebuild queue gauges from durable state so process restarts do not skew them."""

    def __init__(self) -> None:
        self._known_queues: set[str] = set()

    def update(self, commands: list[ExecutionCommand], now: datetime | None = None) -> None:
        observed_at = now or datetime.now(UTC)
        counts: Counter[tuple[str, str]] = Counter(
            (command.queue_name, command.status.value) for command in commands
        )
        queues = {command.queue_name for command in commands} | self._known_queues
        for queue in queues:
            for status in _COMMAND_STATUSES:
                COMMANDS.labels(queue=queue, status=status).set(counts[(queue, status)])
            active = [
                command
                for command in commands
                if command.queue_name == queue and command.status.value not in _TERMINAL_STATUSES
            ]
            age = max(
                ((observed_at - command.created_at).total_seconds() for command in active),
                default=0,
            )
            OLDEST_COMMAND_AGE.labels(queue=queue).set(max(age, 0))
        self._known_queues = queues


async def sample_commands_forever(
    reader: CommandStatusReader,
    stop_event: asyncio.Event,
    interval_seconds: float,
) -> None:
    """Refresh durable queue gauges until process shutdown."""
    sampler = CommandMetricsSampler()
    while not stop_event.is_set():
        sampler.update(await reader.list())
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)


def metrics_asgi_app():
    """Return the private ASGI metrics endpoint."""
    return make_asgi_app(registry=REGISTRY)


def worker_metrics_registry() -> CollectorRegistry:
    """Build a scrape registry that aggregates Celery prefork worker processes."""
    if not os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        return REGISTRY
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return registry


def start_worker_metrics_server(port: int):
    """Expose worker metrics only on its internal container interface."""
    return start_http_server(port, addr="0.0.0.0", registry=worker_metrics_registry())


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
    "COMMAND_ATTEMPTS",
    "COMMAND_DURATION",
    "CREATIVE_AUTOMATION_STEP_DURATION",
    "CREATIVE_AUTOMATION_TOTAL_DURATION",
    "CommandMetricsSampler",
    "HTTP_DURATION",
    "HTTP_IN_FLIGHT",
    "HTTP_REQUESTS",
    "READINESS",
    "REGISTRY",
    "metrics_asgi_app",
    "sample_commands_forever",
    "start_worker_metrics_server",
    "worker_metrics_registry",
]
