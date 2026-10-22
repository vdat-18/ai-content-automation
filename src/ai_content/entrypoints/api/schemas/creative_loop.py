"""API contracts for the unified Marketing Creative loop."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from ai_content.domains.marketing.creative.domain.entities import ApprovalDecision
from ai_content.domains.marketing.creative_feedback.domain.models import (
    EvidenceStatus,
    FeedbackDecision,
)
from ai_content.domains.marketing.creative_loop.ports.contracts import AdsOutcome
from ai_content.domains.marketing.performance_decisions.domain.models import (
    MetricStatus,
    PerformanceDecision,
)


class CreativeLoopRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    input_snapshot_id: str
    context_snapshot_id: str
    state: str
    initial_performance_run_id: str
    initial_evaluation_id: str
    initial_intake_run_id: str | None
    creative_job_id: str | None
    approved_creative_version_id: str | None
    ads_event_id: str | None
    post_ads_performance_run_id: str | None
    feedback_run_id: str | None
    lesson_id: str | None
    next_intake_run_id: str | None
    next_creative_job_id: str | None
    created_at: str
    updated_at: str
    audit_log: list[str]


class CreativeLoopRunListResponse(BaseModel):
    items: list[CreativeLoopRunResponse]
    total: int


class CreativeLoopTimelineStepResponse(BaseModel):
    key: str
    label: str
    status: str
    reference: str | None
    detail: str


class CreativeLoopTimelineResponse(BaseModel):
    run: CreativeLoopRunResponse
    steps: list[CreativeLoopTimelineStepResponse]


class CreativeLoopDemandDecisionRequest(BaseModel):
    evaluation_id: str = Field(min_length=1)
    decision: PerformanceDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CreativeLoopCreativeDecisionRequest(BaseModel):
    decision: ApprovalDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CreativeLoopAdsOutcomeRequest(BaseModel):
    event_id: str = Field(min_length=1)
    creative_version_id: str | None = Field(default=None, min_length=1)
    platform: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    adset_id: str = Field(min_length=1)
    ad_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    purchases: Decimal | None = Field(default=None, ge=0)
    roas: Decimal | None = Field(default=None, ge=0)
    cost_per_atc: Decimal | None = Field(default=None, ge=0)
    evidence_status: MetricStatus
    mapping_status: EvidenceStatus
    observed_at: datetime

    @model_validator(mode="after")
    def evidence_is_consistent(self) -> "CreativeLoopAdsOutcomeRequest":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Ads observation time must include timezone information")
        metrics = (self.purchases, self.roas, self.cost_per_atc)
        if self.evidence_status == MetricStatus.KNOWN and any(value is None for value in metrics):
            raise ValueError("Known Ads evidence requires all metric values")
        if self.evidence_status != MetricStatus.KNOWN and any(
            value is not None for value in metrics
        ):
            raise ValueError("Unresolved Ads evidence cannot select metric values")
        if self.mapping_status == EvidenceStatus.KNOWN and self.creative_version_id is None:
            raise ValueError("Known Ads mapping requires a Creative version ID")
        if self.mapping_status != EvidenceStatus.KNOWN and self.creative_version_id is not None:
            raise ValueError("Unresolved Ads mapping cannot select a Creative version ID")
        return self

    def to_domain(self) -> AdsOutcome:
        return AdsOutcome(**self.model_dump())


class CreativeLoopLessonDecisionRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learning_proposal_id: str | None = Field(default=None, min_length=1)
    decision: FeedbackDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


__all__ = [
    "CreativeLoopAdsOutcomeRequest",
    "CreativeLoopCreativeDecisionRequest",
    "CreativeLoopDemandDecisionRequest",
    "CreativeLoopLessonDecisionRequest",
    "CreativeLoopRunListResponse",
    "CreativeLoopRunResponse",
    "CreativeLoopTimelineResponse",
    "CreativeLoopTimelineStepResponse",
]
