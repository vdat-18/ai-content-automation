"""Public response schemas for business-facing AI usage reporting."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AIUsageCostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: str
    amount: Decimal


class AIUsageBreakdownResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    costs: tuple[AIUsageCostResponse, ...]


class AIUsageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    workstream: str
    operation: str
    backend: str
    model: str
    model_revision: str | None
    status: str
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


class AIUsageEventPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: tuple[AIUsageEventResponse, ...]
    total: int
    limit: int
    offset: int


class AIUsageRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    costs: tuple[AIUsageCostResponse, ...]
    models: tuple[str, ...]
    operations: tuple[str, ...]
    started_at: datetime
    completed_at: datetime | None


class AIUsageRunPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: tuple[AIUsageRunResponse, ...]
    total: int
    limit: int
    offset: int


class AIUsageSummaryResponse(BaseModel):
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
    costs: tuple[AIUsageCostResponse, ...]
    by_model: tuple[AIUsageBreakdownResponse, ...]
    by_workstream: tuple[AIUsageBreakdownResponse, ...]
    by_operation: tuple[AIUsageBreakdownResponse, ...]
    by_backend: tuple[AIUsageBreakdownResponse, ...]
    by_day: tuple[AIUsageBreakdownResponse, ...]
    recent_failures: tuple[AIUsageEventResponse, ...]
    from_time: datetime
    to_time: datetime


__all__ = [
    "AIUsageEventPageResponse",
    "AIUsageEventResponse",
    "AIUsageRunPageResponse",
    "AIUsageSummaryResponse",
]
