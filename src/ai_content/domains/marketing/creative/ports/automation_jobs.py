"""Durable monitoring records for selected-SKU Creative automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from .contracts import MarketingCreativeAutomationRequest


@dataclass(frozen=True)
class CreativeAutomationJobIssue:
    code: str
    detail: str
    component: str | None = None


@dataclass(frozen=True)
class CreativeAutomationJobSnapshot:
    job_id: str
    batch_id: str
    request: MarketingCreativeAutomationRequest
    route: str
    routing_reasons: tuple[str, ...]
    status: str
    provider_status: str
    created_at: datetime
    updated_at: datetime
    command_id: str | None = None
    intake_run_id: str | None = None
    creative_job_id: str | None = None
    package_ref: str | None = None
    workflow_ref: str | None = None
    review_id: str | None = None
    asset_count: int = 0
    ads_draft_id: str | None = None
    issues: tuple[CreativeAutomationJobIssue, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.job_id, self.batch_id, self.status)):
            raise ValueError("Creative automation job identity and status are required")
        for value in (self.created_at, self.updated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Creative automation job timestamps must include timezone")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("Input tokens cannot be negative")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("Output tokens cannot be negative")
        if self.total_cost < 0:
            raise ValueError("Creative automation cost cannot be negative")


@dataclass(frozen=True)
class CreativeAutomationBatchSnapshot:
    batch_id: str
    brand_id: str
    requested_by: str
    job_ids: tuple[str, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    idempotency_key: str | None = None


@dataclass(frozen=True)
class CreativeAutomationEvent:
    event_id: str
    job_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ICreativeAutomationJobRepository(Protocol):
    async def create_batch(
        self,
        batch: CreativeAutomationBatchSnapshot,
        jobs: tuple[CreativeAutomationJobSnapshot, ...],
    ) -> tuple[CreativeAutomationJobSnapshot, ...]: ...

    async def save_job(
        self,
        job: CreativeAutomationJobSnapshot,
        event: CreativeAutomationEvent | None = None,
    ) -> None: ...

    async def add_event(self, event: CreativeAutomationEvent) -> None: ...

    async def get_job(self, job_id: str) -> CreativeAutomationJobSnapshot | None: ...

    async def list_jobs(self) -> list[CreativeAutomationJobSnapshot]: ...

    async def list_events(self, job_id: str) -> list[CreativeAutomationEvent]: ...


__all__ = [
    "CreativeAutomationBatchSnapshot",
    "CreativeAutomationEvent",
    "CreativeAutomationJobIssue",
    "CreativeAutomationJobSnapshot",
    "ICreativeAutomationJobRepository",
]
