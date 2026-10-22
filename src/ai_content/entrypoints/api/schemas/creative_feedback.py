"""API schemas for exact-version Creative feedback lineage."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai_content.domains.marketing.creative_feedback.domain.models import FeedbackDecision


class FeedbackCriterionResponse(BaseModel):
    criterion_id: str
    metric: str
    window_id: str
    outcome: str
    observed_value: str | None
    operator: str
    threshold: str
    detail: str
    source_ref: str | None


class CreativeReleaseResponse(BaseModel):
    release_id: str
    creative_job_id: str
    creative_id: str
    creative_version_id: str
    current_version_id: str
    brand_id: str
    sku_id: str
    idea_id: str
    approval_ref: str
    approved_at: str
    persona_id: str | None
    angle_id: str | None
    concept_id: str | None
    creative_set_id: str | None
    variation_id: str | None


class AdPlacementMappingResponse(BaseModel):
    mapping_id: str
    status: str
    platform: str
    account_id: str
    evidence_ref: str | None
    observed_at: str
    mapped_version_id: str | None
    candidate_version_ids: list[str]
    campaign_id: str | None
    adset_id: str | None
    ad_id: str | None
    raw_creative_name: str | None


class PerformanceOutcomeResponse(BaseModel):
    performance_run_id: str
    evaluation_id: str
    state: str
    classification: str
    recommendation: str
    subject_creative_id: str
    subject_version_id: str | None
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
    criteria: list[FeedbackCriterionResponse]
    evidence_refs: list[str]
    observed_at: str


class HumanFeedbackResponse(BaseModel):
    feedback_id: str
    status: str
    creative_version_id: str | None
    decision: str | None
    issue_codes: list[str]
    summary: str | None
    source_ref: str | None
    observed_at: str


class FeedbackLessonResponse(BaseModel):
    lesson_id: str
    version_number: int
    creative_version_id: str
    outcome: str
    summary: str
    supported_facts: list[str]
    non_conclusions: list[str]
    evidence_refs: list[str]
    performance_evaluation_id: str
    rule_set_id: str
    rule_version: str
    created_at: str


class NextCreativeTaskPreviewResponse(BaseModel):
    preview_id: str
    state: str
    action: str
    source_lesson_id: str
    source_evaluation_id: str
    source_creative_version_id: str
    brand_id: str
    sku_id: str
    reusable_context_refs: list[str]
    missing_context: list[str]
    evidence_refs: list[str]


class AdsEvidencePackResponse(BaseModel):
    pack_id: str
    evaluation_id: str
    creative_id: str
    creative_version_id: str
    brand_id: str
    sku_id: str
    platform: str
    window_id: str
    attribution: str
    classification: str
    recommendation: str
    criteria: list[FeedbackCriterionResponse]
    human_feedback: HumanFeedbackResponse | None
    evidence_refs: list[str]
    version: str


class AdsDiagnosisResponse(BaseModel):
    observations: list[str]
    hypotheses: list[str]
    confounders: list[str]
    uncertainty: str
    evidence_refs: list[str]


class LearningProposalResponse(BaseModel):
    proposal_id: str
    version_number: int
    creative_version_id: str
    sku_id: str
    priority: int
    recommended_action: str
    hypothesis: str
    experiment: str
    success_signal: str
    evidence_refs: list[str]
    uncertainty: str


class PerformanceLearningAnalysisResponse(BaseModel):
    analysis_id: str
    evidence_pack_id: str
    creative_version_id: str
    sku_id: str
    diagnosis: AdsDiagnosisResponse
    proposal: LearningProposalResponse | None
    prompt_version: str
    model: str
    rubric_version: str
    created_at: str


class CreativeFeedbackRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    release: CreativeReleaseResponse
    ad_mapping: AdPlacementMappingResponse
    performance: PerformanceOutcomeResponse
    human_feedback: HumanFeedbackResponse | None
    state: str
    lesson: FeedbackLessonResponse | None
    next_task_preview: NextCreativeTaskPreviewResponse | None
    warnings: list[str]
    created_at: str
    ads_evidence_pack: AdsEvidencePackResponse | None
    learning_analysis: PerformanceLearningAnalysisResponse | None
    decision: str | None
    decision_lesson_id: str | None
    decision_learning_proposal_id: str | None
    approved_learning_proposal: LearningProposalResponse | None
    reviewer_alias: str | None
    decision_reason: str | None
    decided_at: str | None


class CreativeFeedbackRunListResponse(BaseModel):
    items: list[CreativeFeedbackRunResponse]
    total: int


class CreativeFeedbackDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_id: str
    learning_proposal_id: str | None = None
    decision: FeedbackDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


__all__ = [
    "AdPlacementMappingResponse",
    "AdsDiagnosisResponse",
    "AdsEvidencePackResponse",
    "CreativeFeedbackDecisionRequest",
    "CreativeFeedbackRunListResponse",
    "CreativeFeedbackRunResponse",
    "CreativeReleaseResponse",
    "FeedbackCriterionResponse",
    "FeedbackLessonResponse",
    "HumanFeedbackResponse",
    "LearningProposalResponse",
    "NextCreativeTaskPreviewResponse",
    "PerformanceOutcomeResponse",
    "PerformanceLearningAnalysisResponse",
]
