"""Strict synthetic fixture loader for Creative feedback lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..application.evaluation import CreativeFeedbackRequest
from ..domain.models import (
    AdPlacementMapping,
    CreativeReleaseSnapshot,
    CriterionOutcome,
    EvaluationState,
    EvidenceStatus,
    HumanFeedbackObservation,
    PerformanceClassification,
    PerformanceCriterionFact,
    PerformanceOutcomeSnapshot,
    RecommendationAction,
)


class ReleaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str
    creative_job_id: str
    creative_id: str
    creative_version_id: str
    current_version_id: str
    brand_id: str
    sku_id: str
    idea_id: str
    approval_ref: str
    approved_at: datetime
    persona_id: str | None = None
    angle_id: str | None = None
    hook_id: str | None = None
    concept_id: str | None = None
    creative_set_id: str | None = None
    variation_id: str | None = None


class MappingFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping_id: str
    status: EvidenceStatus
    platform: str
    account_id: str
    evidence_ref: str | None = None
    observed_at: datetime
    mapped_version_id: str | None = None
    candidate_version_ids: list[str] = Field(default_factory=list)
    campaign_id: str | None = None
    adset_id: str | None = None
    ad_id: str | None = None
    raw_creative_name: str | None = None


class CriterionFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    metric: str
    window_id: str
    outcome: CriterionOutcome
    observed_value: str | None = None
    operator: str
    threshold: str
    detail: str
    source_ref: str | None = None


class PerformanceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    performance_run_id: str
    evaluation_id: str
    state: EvaluationState
    classification: PerformanceClassification
    recommendation: RecommendationAction
    subject_creative_id: str
    subject_version_id: str | None = None
    brand_id: str
    sku_id: str
    platform: str
    grain: str
    window_id: str
    timezone: str
    attribution: str
    rule_set_id: str
    rule_version: str
    rule_mode: str
    rule_status: str
    criteria: list[CriterionFixture] = Field(min_length=1)
    evidence_refs: list[str]
    observed_at: datetime


class HumanFeedbackFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback_id: str
    status: EvidenceStatus
    creative_version_id: str | None = None
    decision: str | None = None
    issue_codes: list[str] = Field(default_factory=list)
    summary: str | None = None
    source_ref: str | None = None
    observed_at: datetime


class FeedbackCaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_run_id: str
    release: ReleaseFixture
    ad_mapping: MappingFixture
    performance: PerformanceFixture
    human_feedback: HumanFeedbackFixture | None = None

    def request(self) -> CreativeFeedbackRequest:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        feedback = (
            HumanFeedbackObservation(
                **self.human_feedback.model_dump(exclude={"issue_codes"}),
                issue_codes=tuple(self.human_feedback.issue_codes),
            )
            if self.human_feedback
            else None
        )
        return CreativeFeedbackRequest(
            source_run_id=self.source_run_id,
            source_checksum_sha256=hashlib.sha256(canonical).hexdigest(),
            release=CreativeReleaseSnapshot(**self.release.model_dump()),
            ad_mapping=AdPlacementMapping(
                **self.ad_mapping.model_dump(exclude={"candidate_version_ids"}),
                candidate_version_ids=tuple(self.ad_mapping.candidate_version_ids),
            ),
            performance=PerformanceOutcomeSnapshot(
                **self.performance.model_dump(exclude={"criteria", "evidence_refs"}),
                criteria=tuple(
                    PerformanceCriterionFact(**item.model_dump())
                    for item in self.performance.criteria
                ),
                evidence_refs=tuple(self.performance.evidence_refs),
            ),
            human_feedback=feedback,
        )


class CreativeFeedbackFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases: list[FeedbackCaseFixture] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_ids(self) -> CreativeFeedbackFixture:
        source_ids = [item.source_run_id for item in self.cases]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Creative feedback source_run_id values must be unique")
        return self

    def requests(self) -> tuple[CreativeFeedbackRequest, ...]:
        return tuple(case.request() for case in self.cases)


def load_creative_feedback_fixture(path: Path) -> CreativeFeedbackFixture:
    return CreativeFeedbackFixture.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["CreativeFeedbackFixture", "load_creative_feedback_fixture"]
