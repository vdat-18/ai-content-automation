"""Durable, payload-free AI usage records and reporting contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

AIUsageStatus = Literal["started", "succeeded", "failed"]


@dataclass(frozen=True)
class AIUsageStart:
    workstream: str
    operation: str
    backend: str
    model: str
    model_revision: str | None = None
    source_run_id: str | None = None
    workflow_run_id: str | None = None
    job_id: str | None = None
    version_id: str | None = None
    brand_id: str | None = None
    batch_id: str | None = None
    run_id: str | None = None
    parent_event_id: str | None = None
    attempt_number: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.attempt_number is not None and self.attempt_number < 1:
            raise ValueError("AI usage attempt number must be positive")


@dataclass(frozen=True)
class AIUsageCompletion:
    request_count: int = 1
    input_tokens: int | None = None
    output_tokens: int | None = None
    output_count: int | None = None
    output_bytes: int | None = None
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    model: str | None = None
    model_revision: str | None = None
    provider_request_id: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if (self.cost_amount is None) != (self.cost_currency is None):
            raise ValueError("Cost amount and currency must be supplied together")
        if self.cost_amount is not None and self.cost_amount < 0:
            raise ValueError("AI usage cost cannot be negative")
        if self.cost_currency is not None and not self.cost_currency.strip():
            raise ValueError("AI usage cost currency cannot be blank")
        _validate_counts(
            self.request_count,
            self.input_tokens,
            self.output_tokens,
            self.output_count,
            self.output_bytes,
        )


@dataclass(frozen=True)
class AIUsageFailure:
    error_code: str
    request_count: int = 1
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    model_revision: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        _validate_counts(self.request_count, self.input_tokens, self.output_tokens)


@dataclass(frozen=True)
class AIUsageEvent:
    event_id: str
    workstream: str
    operation: str
    backend: str
    model: str
    model_revision: str | None
    status: AIUsageStatus
    request_count: int
    input_tokens: int | None
    output_tokens: int | None
    output_count: int | None
    output_bytes: int | None
    cost_amount: Decimal | None
    cost_currency: str | None
    error_code: str | None
    source_run_id: str | None
    workflow_run_id: str | None
    job_id: str | None
    version_id: str | None
    brand_id: str | None
    batch_id: str | None
    run_id: str | None
    parent_event_id: str | None
    attempt_number: int | None
    provider_request_id: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


@dataclass(frozen=True)
class AIUsageFilters:
    from_time: datetime
    to_time: datetime
    workstream: str | None = None
    model: str | None = None
    brand_id: str | None = None
    operation: str | None = None
    backend: str | None = None
    status: AIUsageStatus | None = None
    cost_state: Literal["priced", "unpriced"] | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class AIUsageCost:
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class AIUsageBreakdown:
    key: str
    attempts: int
    succeeded: int
    failed: int
    incomplete: int
    request_count: int
    input_tokens: int
    output_tokens: int
    output_count: int
    output_bytes: int
    token_reported_attempts: int
    duration_reported_attempts: int
    total_duration_ms: int
    linked_attempts: int
    unpriced_attempts: int
    costs: tuple[AIUsageCost, ...] = ()


@dataclass(frozen=True)
class AIUsageSummary:
    attempts: int
    succeeded: int
    failed: int
    incomplete: int
    request_count: int
    input_tokens: int
    output_tokens: int
    output_count: int
    output_bytes: int
    token_reported_attempts: int
    duration_reported_attempts: int
    total_duration_ms: int
    p50_duration_ms: int | None
    p95_duration_ms: int | None
    linked_attempts: int
    unpriced_attempts: int
    costs: tuple[AIUsageCost, ...]
    by_model: tuple[AIUsageBreakdown, ...]
    by_workstream: tuple[AIUsageBreakdown, ...]
    by_operation: tuple[AIUsageBreakdown, ...]
    by_backend: tuple[AIUsageBreakdown, ...]
    by_day: tuple[AIUsageBreakdown, ...]
    recent_failures: tuple[AIUsageEvent, ...]


@dataclass(frozen=True)
class AIUsageEventPage:
    items: tuple[AIUsageEvent, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class AIUsageRun:
    run_id: str
    batch_id: str | None
    brand_id: str | None
    status: str
    attempts: int
    succeeded: int
    failed: int
    incomplete: int
    input_tokens: int
    output_tokens: int
    output_count: int
    output_bytes: int
    total_duration_ms: int
    costs: tuple[AIUsageCost, ...]
    models: tuple[str, ...]
    operations: tuple[str, ...]
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class AIUsageRunPage:
    items: tuple[AIUsageRun, ...]
    total: int
    limit: int
    offset: int


def _validate_counts(*values: int | None) -> None:
    if any(value is not None and value < 0 for value in values):
        raise ValueError("AI usage counts cannot be negative")


__all__ = [
    "AIUsageBreakdown",
    "AIUsageCompletion",
    "AIUsageCost",
    "AIUsageEvent",
    "AIUsageEventPage",
    "AIUsageFailure",
    "AIUsageFilters",
    "AIUsageRun",
    "AIUsageRunPage",
    "AIUsageStart",
    "AIUsageStatus",
    "AIUsageSummary",
]
