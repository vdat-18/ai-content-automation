"""External boundaries for Creator outreach."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.models import (
    CreatorContactTrigger,
    CreatorEvaluationUpdate,
    CreatorOutreachRun,
    DeliveryReceipt,
    OutreachPlan,
    OutreachPlanVersion,
    OutreachPolicy,
    OutreachReview,
    ReplyRecord,
)


class CreatorOutreachInputDriftError(ValueError):
    """Raised when an idempotency key is reused with changed input."""


class CreatorReplyInputDriftError(ValueError):
    """Raised when a reply event identifier is reused with changed content."""


class IOutreachPlanGenerator(Protocol):
    @property
    def version(self) -> str: ...

    async def generate(
        self,
        trigger: CreatorContactTrigger,
        policy: OutreachPolicy,
        revision_instructions: tuple[str, ...],
    ) -> OutreachPlan: ...


class IOutreachReviewer(Protocol):
    async def review(
        self,
        plan: OutreachPlan,
        trigger: CreatorContactTrigger,
        version_number: int,
    ) -> OutreachReview: ...


class IOutboundChannel(Protocol):
    async def send(
        self,
        run_id: str,
        version: OutreachPlanVersion,
        message: str,
        sequence: int,
        idempotency_key: str,
        sent_at: datetime,
    ) -> DeliveryReceipt: ...


class IReplyEvidenceAppender(Protocol):
    async def append(
        self, run: CreatorOutreachRun, reply: ReplyRecord
    ) -> CreatorEvaluationUpdate: ...


class ICreatorOutreachRepository(Protocol):
    async def save(self, run: CreatorOutreachRun) -> None: ...

    async def get(self, run_id: str) -> CreatorOutreachRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> CreatorOutreachRun | None: ...

    async def list(self) -> list[CreatorOutreachRun]: ...


__all__ = [name for name in globals() if name.startswith("I") or name.endswith("Error")]
