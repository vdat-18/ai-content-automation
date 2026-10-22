"""Typed observability configuration shared by API and worker processes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse


@dataclass(frozen=True)
class ObservabilitySettings:
    """Process-local telemetry settings loaded from the deployment environment."""

    enabled: bool = False
    service_name: str = "aicontent-service"
    deployment_environment: str = "development"
    otlp_traces_endpoint: str | None = None
    trace_sample_ratio: float = 1.0
    metrics_enabled: bool = True
    metrics_port: int = 9464
    command_metrics_interval_seconds: float = 15.0
    log_format: Literal["text", "json"] = "text"
    ai_telemetry_enabled: bool = False
    langfuse_otlp_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.service_name.strip():
            raise ValueError("Observability service name is required")
        if not self.deployment_environment.strip():
            raise ValueError("Deployment environment is required")
        if not 0 <= self.trace_sample_ratio <= 1:
            raise ValueError("Trace sample ratio must be between zero and one")
        if not 1 <= self.metrics_port <= 65535:
            raise ValueError("Metrics port must be between 1 and 65535")
        if self.command_metrics_interval_seconds <= 0:
            raise ValueError("Command metrics interval must be positive")
        if self.enabled:
            if not self.otlp_traces_endpoint:
                raise ValueError("OTLP traces endpoint is required when tracing is enabled")
            endpoint = urlparse(self.otlp_traces_endpoint)
            if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
                raise ValueError("OTLP traces endpoint must be an HTTP(S) URL")
        if self.ai_telemetry_enabled and not self.enabled:
            raise ValueError("AI telemetry requires tracing to be enabled")
        langfuse_values = (
            self.langfuse_otlp_endpoint,
            self.langfuse_public_key,
            self.langfuse_secret_key,
        )
        if any(langfuse_values) and not all(langfuse_values):
            raise ValueError("Langfuse OTLP endpoint and credentials must be configured together")
        if all(langfuse_values) and not self.enabled:
            raise ValueError("Langfuse OTLP export requires tracing to be enabled")
        if self.langfuse_otlp_endpoint is not None:
            endpoint = urlparse(self.langfuse_otlp_endpoint)
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.netloc
                or endpoint.username
                or endpoint.password
            ):
                raise ValueError(
                    "Langfuse OTLP endpoint must be an HTTP(S) URL without credentials"
                )


__all__ = ["ObservabilitySettings"]
