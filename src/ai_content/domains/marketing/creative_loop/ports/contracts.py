"""Typed inputs for Creative loop orchestration."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ai_content.domains.marketing.creative_feedback.domain.models import EvidenceStatus
from ai_content.domains.marketing.creative_intake.application.contracts import (
    CreativeIntakeFixture,
)
from ai_content.domains.marketing.performance_decisions.application.evaluation import (
    PerformanceDecisionRequest,
)
from ai_content.domains.marketing.performance_decisions.domain.models import MetricStatus


@dataclass(frozen=True)
class AdsOutcome:
    event_id: str
    creative_version_id: str | None
    platform: str
    account_id: str
    campaign_id: str
    adset_id: str
    ad_id: str
    window_id: str
    timezone: str
    attribution: str
    purchases: Decimal | None
    roas: Decimal | None
    cost_per_atc: Decimal | None
    evidence_status: MetricStatus
    mapping_status: EvidenceStatus
    observed_at: datetime


@dataclass(frozen=True)
class CreativeLoopInput:
    input_snapshot_id: str
    source_run_id: str
    source_checksum_sha256: str
    context_snapshot_id: str
    initial_performance: PerformanceDecisionRequest
    intake_template: CreativeIntakeFixture


__all__ = ["AdsOutcome", "CreativeLoopInput"]
