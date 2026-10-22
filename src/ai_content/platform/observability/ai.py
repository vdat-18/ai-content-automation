"""Privacy-safe AI spans and low-cardinality operation metrics."""

from __future__ import annotations

from contextlib import suppress
from time import monotonic
from typing import Self

from loguru import logger
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .metrics import (
    AI_GENERATED_OUTPUT_BYTES,
    AI_GENERATED_OUTPUTS,
    AI_HUMAN_EVALUATIONS,
    AI_INPUT_TOKENS,
    AI_OUTPUT_TOKENS,
    AI_REQUEST_DURATION,
    AI_REQUESTS,
    AI_SEMANTIC_REVIEWS,
)

_enabled = False
_tracer = trace.get_tracer("ai_content.platform.observability.ai")
_ALLOWED_ATTRIBUTES = {
    "attempt_number",
    "backend",
    "batch_count",
    "batch_index",
    "config_hash",
    "creative_set_id",
    "criterion_count",
    "decision",
    "error_type",
    "input_hash",
    "input_image_count",
    "input_tokens",
    "issue_count",
    "job_id",
    "model",
    "model_revision",
    "operation",
    "outcome",
    "output_bytes",
    "output_height",
    "output_tokens",
    "output_width",
    "policy_ref",
    "prompt_hash",
    "prompt_version",
    "provider_elapsed_seconds",
    "provider_request_id",
    "reason_present",
    "request_count",
    "review_mode",
    "rubric_ref",
    "runtime_version",
    "semantic_outcome",
    "semantic_reviewer_version",
    "semantic_score",
    "variation_id",
    "version_id",
    "workflow_hash",
}


def configure_ai_observability(enabled: bool) -> None:
    """Enable or disable AI-specific spans and metrics for this process."""
    global _enabled
    _enabled = enabled


class AIObservation:
    """Record one bounded AI operation without capturing raw inputs or outputs."""

    def __init__(self, operation: str, backend: str, model: str, **attributes: object) -> None:
        self.operation = operation
        self.backend = backend
        self.model = model
        self._attributes = attributes
        self._started = 0.0
        self._outcome: str | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._output_bytes: int | None = None
        self._generated_output = operation.startswith("image.")
        self._semantic_outcome: tuple[str, str] | None = None
        self._span = None
        self._span_context = None
        self._active = False

    def __enter__(self) -> Self:
        if not _enabled:
            return self
        try:
            self._started = monotonic()
            self._span_context = _tracer.start_as_current_span(f"aic.ai.{self.operation}")
            self._span = self._span_context.__enter__()
            self._active = True
            self._set_span_attributes(self._attributes)
            self._set_span_attributes(
                {
                    "operation": self.operation,
                    "backend": self.backend,
                    "model": self.model,
                }
            )
            self._span.set_attribute("gen_ai.operation.name", self.operation)
            self._span.set_attribute("gen_ai.provider.name", self.backend)
            self._span.set_attribute("gen_ai.request.model", self.model)
            observation_type = (
                "evaluator"
                if self.operation
                in {
                    "semantic_review",
                    "research_screening",
                    "human_evaluation",
                }
                else "generation"
            )
            self._span.set_attribute("langfuse.observation.type", observation_type)
            self._span.set_attribute("langfuse.observation.model.name", self.model)
            self._span.set_attribute("langfuse.trace.name", self.operation)
            job_id = self._attributes.get("job_id")
            if isinstance(job_id, str):
                self._span.set_attribute("session.id", job_id)
            prompt_version = self._attributes.get("prompt_version")
            if isinstance(prompt_version, str):
                self._span.set_attribute("langfuse.observation.prompt.version", prompt_version)
        except Exception:
            self._active = False
            if self._span_context is not None:
                with suppress(Exception):
                    self._span_context.__exit__(None, None, None)
            logger.warning("AI observation could not start for operation {}", self.operation)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if not self._active:
            return False
        try:
            if exc is not None and self._outcome is None:
                self.fail(type(exc).__name__)
            if self._outcome is None:
                self.succeed()
            assert self._outcome is not None
            elapsed = monotonic() - self._started
            AI_REQUESTS.labels(
                operation=self.operation,
                backend=self.backend,
                model=self.model,
                outcome=self._outcome,
            ).inc()
            AI_REQUEST_DURATION.labels(
                operation=self.operation,
                backend=self.backend,
                model=self.model,
            ).observe(elapsed)
            if self._input_tokens is not None:
                AI_INPUT_TOKENS.labels(operation=self.operation, model=self.model).inc(
                    self._input_tokens
                )
            if self._output_tokens is not None:
                AI_OUTPUT_TOKENS.labels(operation=self.operation, model=self.model).inc(
                    self._output_tokens
                )
            if self._generated_output:
                AI_GENERATED_OUTPUTS.labels(
                    operation=self.operation,
                    model=self.model,
                    outcome=self._outcome,
                ).inc()
                if self._output_bytes is not None:
                    AI_GENERATED_OUTPUT_BYTES.labels(
                        operation=self.operation,
                        model=self.model,
                    ).observe(self._output_bytes)
            if self._semantic_outcome is not None:
                outcome, mode = self._semantic_outcome
                AI_SEMANTIC_REVIEWS.labels(model=self.model, outcome=outcome, mode=mode).inc()
            assert self._span is not None and self._span_context is not None
            self._span.set_attribute("aic.ai.duration_seconds", elapsed)
            # Do not let the OTel context manager record exception messages or stack traces.
            self._span_context.__exit__(None, None, None)
        except Exception:
            if self._span_context is not None:
                with suppress(Exception):
                    self._span_context.__exit__(None, None, None)
            logger.warning("AI observation could not finish for operation {}", self.operation)
        return False

    def update(self, *, model: str | None = None, **attributes: object) -> None:
        if model is not None:
            self.model = model
            attributes["model"] = model
            if self._span is not None:
                with suppress(Exception):
                    self._span.set_attribute("gen_ai.request.model", model)
                    self._span.set_attribute("langfuse.observation.model.name", model)
        if self._active:
            try:
                self._set_span_attributes(attributes)
            except Exception:
                logger.warning("AI observation update failed for operation {}", self.operation)

    def usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.update(input_tokens=input_tokens, output_tokens=output_tokens)
        if self._span is not None:
            try:
                if input_tokens is not None:
                    self._span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                if output_tokens is not None:
                    self._span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            except Exception:
                logger.warning("AI usage telemetry failed for operation {}", self.operation)

    def generated(self, output_bytes: int) -> None:
        self._generated_output = True
        self._output_bytes = output_bytes
        self.update(output_bytes=output_bytes)

    def semantic_review(self, outcome: str, mode: str) -> None:
        self._semantic_outcome = (outcome, mode)
        self.update(semantic_outcome=outcome, review_mode=mode)

    def human_evaluation(self, decision: str, semantic_outcome: str) -> None:
        if self._active:
            try:
                AI_HUMAN_EVALUATIONS.labels(
                    decision=decision,
                    semantic_outcome=semantic_outcome,
                ).inc()
            except Exception:
                logger.warning("Human evaluation telemetry failed for operation {}", self.operation)
        self.update(decision=decision, semantic_outcome=semantic_outcome)

    def succeed(self, **attributes: object) -> None:
        self._outcome = "success"
        self.update(outcome="success", **attributes)
        if self._span is not None:
            with suppress(Exception):
                self._span.set_status(Status(StatusCode.OK))

    def fail(self, error_type: str, **attributes: object) -> None:
        self._outcome = "failure"
        self.update(outcome="failure", error_type=error_type, **attributes)
        if self._span is not None:
            with suppress(Exception):
                self._span.set_status(Status(StatusCode.ERROR, error_type))

    def _set_span_attributes(self, attributes: dict[str, object]) -> None:
        if self._span is None:
            return
        for key, value in attributes.items():
            if key not in _ALLOWED_ATTRIBUTES or value is None:
                continue
            if not isinstance(value, (str, bool, int, float)):
                continue
            self._span.set_attribute(f"aic.ai.{key}", value)


def observe_ai_call(
    operation: str, backend: str, model: str, **attributes: object
) -> AIObservation:
    """Build an AI observation context for one model or human-evaluation operation."""
    return AIObservation(operation, backend, model, **attributes)


__all__ = ["AIObservation", "configure_ai_observability", "observe_ai_call"]
