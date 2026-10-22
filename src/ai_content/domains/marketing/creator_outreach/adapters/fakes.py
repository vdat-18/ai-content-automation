"""Deterministic fake model and channel adapters for Creator outreach."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from ..domain.models import (
    CreatorContactTrigger,
    DeliveryReceipt,
    OutreachPlan,
    OutreachPlanVersion,
    OutreachPolicy,
    OutreachReview,
)


class FixtureOutreachGenerator:
    def __init__(self, plans: tuple[OutreachPlan, ...], version: str) -> None:
        if not plans:
            raise ValueError("Fixture outreach generator requires at least one plan")
        self._plans = plans
        self._version = version
        self._calls = 0

    @property
    def version(self) -> str:
        return self._version

    async def generate(
        self,
        _trigger: CreatorContactTrigger,
        _policy: OutreachPolicy,
        _revision_instructions: tuple[str, ...],
    ) -> OutreachPlan:
        index = min(self._calls, len(self._plans) - 1)
        self._calls += 1
        return self._plans[index]


class FixtureOutreachReviewer:
    def __init__(self, reviews: tuple[OutreachReview, ...]) -> None:
        if not reviews:
            raise ValueError("Fixture outreach reviewer requires at least one review")
        self._reviews = reviews

    async def review(
        self,
        _plan: OutreachPlan,
        _trigger: CreatorContactTrigger,
        version_number: int,
    ) -> OutreachReview:
        return self._reviews[min(version_number - 1, len(self._reviews) - 1)]


class FixtureOutboundChannel:
    async def send(
        self,
        _run_id: str,
        version: OutreachPlanVersion,
        _message: str,
        sequence: int,
        idempotency_key: str,
        sent_at: datetime,
    ) -> DeliveryReceipt:
        receipt_id = str(uuid5(NAMESPACE_URL, f"creator-delivery:{idempotency_key}"))
        return DeliveryReceipt(
            receipt_id=receipt_id,
            plan_version_id=version.version_id,
            sequence=sequence,
            channel=version.plan.channel,
            sent_at=sent_at,
            idempotency_key=idempotency_key,
        )


__all__ = [
    "FixtureOutboundChannel",
    "FixtureOutreachGenerator",
    "FixtureOutreachReviewer",
]
