"""Durable state contract for one Marketing-selected Creative automation run."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol, TypeVar

from .ads_activation import AdsActivationApproval, AdsActivationReceipt, AdsDraft
from .final_review import FinalCreativeReview
from .media_production import (
    PaidMediaArtifact,
    PaidMediaQualityEvaluation,
)


class MarketingCreativeAutomationStatus(StrEnum):
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    PREPARING = "preparing"
    NEEDS_INPUT = "needs_input"
    MANUAL_HANDOFF_READY = "manual_handoff_ready"
    ASSISTED_HANDOFF_READY = "assisted_handoff_ready"
    BRIEF_READY = "brief_ready"
    AWAITING_GENERATION_PROVIDER = "awaiting_generation_provider"
    PRODUCING = "producing"
    PRODUCTION_NEEDS_ATTENTION = "production_needs_attention"
    READY_FOR_REVIEW = "ready_for_review"
    REVISION_REQUESTED = "revision_requested"
    MANUAL_TAKEOVER = "manual_takeover"
    CREATIVE_APPROVED = "creative_approved"
    ADS_DRAFT_READY = "ads_draft_ready"
    ADS_APPROVED = "ads_approved"
    ACTIVATED = "activated"
    FAILED = "failed"


@dataclass(frozen=True)
class PaidMediaAttemptRecord:
    attempt_number: int
    artifact: PaidMediaArtifact
    evaluation: PaidMediaQualityEvaluation

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("Paid media attempt number must be positive")


@dataclass(frozen=True)
class ProducedCreativeAssetRecord:
    asset_version_id: str
    media_kind: Literal["image", "video"]
    variation_key: str
    success: bool
    attempts: tuple[PaidMediaAttemptRecord, ...]
    selected_artifact: PaidMediaArtifact | None
    total_cost: Decimal
    outcome: str
    intermediate_artifacts: tuple[PaidMediaArtifact, ...] = ()
    parent_asset_version_id: str | None = None
    generation_request_id: str | None = None
    revision_feedback: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.asset_version_id, self.variation_key, self.outcome)
        ):
            raise ValueError("Produced Creative asset identity and outcome are required")
        if self.total_cost < 0:
            raise ValueError("Produced Creative asset cost cannot be negative")
        if self.success != (self.selected_artifact is not None):
            raise ValueError("Successful production requires one selected artifact")
        if self.parent_asset_version_id == self.asset_version_id:
            raise ValueError("Produced Creative asset cannot be its own parent")
        if self.revision_feedback is not None and not self.revision_feedback.strip():
            raise ValueError("Produced Creative revision feedback cannot be empty")


@dataclass(frozen=True)
class ExactCreativeReviewDecision:
    decision_id: str
    review_id: str
    decision: Literal["approve", "manual_takeover"]
    asset_version_ids: tuple[str, ...]
    asset_checksums: tuple[str, ...]
    reviewer_alias: str
    reason: str
    decided_at: datetime
    key_visual_asset_version_id: str | None = None

    def __post_init__(self) -> None:
        required = (self.decision_id, self.review_id, self.reviewer_alias, self.reason)
        if not all(value.strip() for value in required):
            raise ValueError("Creative review decision identity and reason are required")
        if not self.asset_version_ids or len(self.asset_version_ids) != len(self.asset_checksums):
            raise ValueError("Creative review decision must pin every exact asset")
        if any(len(value) != 64 for value in self.asset_checksums):
            raise ValueError("Creative review decision asset checksums must be SHA-256")
        if (
            self.key_visual_asset_version_id is not None
            and self.key_visual_asset_version_id not in self.asset_version_ids
        ):
            raise ValueError("Key Visual must be one of the approved Creative assets")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("Creative review decision timestamp must include timezone")


@dataclass(frozen=True)
class ManualGenerationRequest:
    generation_request_id: str
    requested_by: str
    reason: str
    requested_at: datetime
    target_asset_version_ids: tuple[str, ...] = ()
    knowledge_refs: tuple[str, ...] = ()
    revision_guidance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.generation_request_id, self.requested_by, self.reason)
        ):
            raise ValueError("Manual generation request identity and reason are required")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Manual generation request timestamp must include timezone")
        if len(self.target_asset_version_ids) != len(set(self.target_asset_version_ids)):
            raise ValueError("Manual generation request targets must be unique")
        if any(not value.strip() for value in self.target_asset_version_ids):
            raise ValueError("Manual generation request targets cannot be empty")


@dataclass(frozen=True)
class ManualTakeoverRecord:
    takeover_id: str
    requested_by: str
    reason: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.takeover_id, self.requested_by, self.reason)):
            raise ValueError("Manual takeover identity and reason are required")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Manual takeover timestamp must include timezone")


@dataclass(frozen=True)
class MarketingCreativeAutomationState:
    request_id: str
    package_id: str
    package_ref: str
    route: Literal["manual", "assisted", "automated"]
    status: MarketingCreativeAutomationStatus
    final_review: FinalCreativeReview | None
    review_decision: ExactCreativeReviewDecision | None
    ads_draft: AdsDraft | None
    ads_approval: AdsActivationApproval | None
    created_at: datetime
    updated_at: datetime
    ads_receipt: AdsActivationReceipt | None = None
    production_assets: tuple[ProducedCreativeAssetRecord, ...] = ()
    production_error_code: str | None = None
    production_error_detail: str | None = None
    generation_requests: tuple[ManualGenerationRequest, ...] = ()
    manual_takeover: ManualTakeoverRecord | None = None
    revision: int = 0
    schema_version: str = "marketing-creative-automation-state@4"

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.request_id, self.package_id, self.package_ref)):
            raise ValueError("Creative automation state identity is required")
        for timestamp in (self.created_at, self.updated_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Creative automation timestamps must include timezone")
        if self.revision < 0:
            raise ValueError("Creative automation state revision cannot be negative")
        if self.review_decision is not None and self.final_review is None:
            raise ValueError("Creative review decision requires a final review")
        if self.ads_draft is not None and (
            self.review_decision is None or self.review_decision.decision != "approve"
        ):
            raise ValueError("Ads Draft requires an approved exact Creative review")
        if self.ads_approval is not None and self.ads_draft is None:
            raise ValueError("Ads approval requires an Ads Draft")
        if self.ads_receipt is not None and self.ads_approval is None:
            raise ValueError("Ads activation receipt requires an approval")
        if self.status == MarketingCreativeAutomationStatus.ACTIVATED and self.ads_receipt is None:
            raise ValueError("Activated Creative automation requires an Ads receipt")
        if self.status == MarketingCreativeAutomationStatus.MANUAL_TAKEOVER and not (
            self.manual_takeover is not None
            or (
                self.review_decision is not None
                and self.review_decision.decision == "manual_takeover"
            )
        ):
            raise ValueError("Manual takeover status requires a recorded human decision")


T = TypeVar("T")
StateRepositoryCall = T | Awaitable[T]


class IMarketingCreativeAutomationStateRepository(Protocol):
    def save(self, state: MarketingCreativeAutomationState) -> StateRepositoryCall[str]: ...

    def get(
        self, request_id: str
    ) -> StateRepositoryCall[MarketingCreativeAutomationState | None]: ...

    def reference(self, request_id: str) -> str: ...


async def resolve_state_repository_call(value: StateRepositoryCall[T]) -> T:
    if isinstance(value, Awaitable):
        return await value
    return value


__all__ = [
    "ExactCreativeReviewDecision",
    "IMarketingCreativeAutomationStateRepository",
    "MarketingCreativeAutomationState",
    "ManualGenerationRequest",
    "ManualTakeoverRecord",
    "PaidMediaAttemptRecord",
    "ProducedCreativeAssetRecord",
    "MarketingCreativeAutomationStatus",
    "StateRepositoryCall",
    "resolve_state_repository_call",
]
