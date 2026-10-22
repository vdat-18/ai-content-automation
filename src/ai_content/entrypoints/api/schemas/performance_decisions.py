"""API schemas for the Performance decision pilot."""

from pydantic import BaseModel

from ai_content.domains.marketing.performance_decisions.domain.models import (
    PerformanceDecision,
)


class PerformanceMetricResponse(BaseModel):
    name: str
    window_id: str
    status: str
    value: str | None
    unit: str
    source_ref: str | None
    observed_at: str


class PerformanceCriterionResponse(BaseModel):
    criterion_id: str
    metric: str
    window_id: str
    outcome: str
    observed_value: str | None
    operator: str
    threshold: str
    source_ref: str | None
    detail: str


class PerformanceRuleAssessmentResponse(BaseModel):
    rule_id: str
    classification: str
    outcome: str
    passed_criteria: int
    required_passes: int
    criteria: list[PerformanceCriterionResponse]


class CreativeDemandPreviewResponse(BaseModel):
    preview_id: str
    state: str
    source_decision_run_id: str
    source_evaluation_id: str
    brand_id: str
    sku_id: str
    objective: str
    channel: str
    action: str
    classification: str
    evidence_refs: list[str]
    missing_context: list[str]


class ExperimentProposalData(BaseModel):
    proposal_id: str
    version_number: int
    sku_id: str
    priority: int
    category: str
    hypothesis: str
    experiment: str
    success_signal: str
    evidence_refs: list[str]
    uncertainty: str


class CreativeOpportunityResponse(BaseModel):
    analysis_id: str
    evidence_pack_id: str
    category: str
    priority: int
    rationale: str
    evidence_refs: list[str]
    uncertainty: str
    counterargument: str
    proposal: ExperimentProposalData
    prompt_version: str
    model: str
    rubric_version: str
    created_at: str


class PerformanceDecisionRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    snapshot_id: str
    subject_type: str
    subject_id: str
    brand_id: str
    store_id: str
    sku_id: str
    platform: str
    objective: str
    channel: str
    timezone: str
    attribution: str
    currency: str
    source_version: str
    observed_at: str
    metrics: list[PerformanceMetricResponse]
    evaluation_id: str
    evaluation_version: int
    evaluation_state: str
    classification: str
    recommendation: str
    rule_set_id: str
    rule_version: str
    rule_mode: str
    rule_status: str
    assessments: list[PerformanceRuleAssessmentResponse]
    evidence_refs: list[str]
    decision: str | None
    decision_evaluation_id: str | None
    reviewer_alias: str | None
    decision_reason: str | None
    decided_at: str | None
    creative_demand_preview: CreativeDemandPreviewResponse | None
    opportunity_analysis: CreativeOpportunityResponse | None
    decision_proposal_id: str | None
    approved_proposal: ExperimentProposalData | None


class PerformanceDecisionRunListResponse(BaseModel):
    items: list[PerformanceDecisionRunResponse]
    total: int


class PerformanceDecisionRequestBody(BaseModel):
    evaluation_id: str
    decision: PerformanceDecision
    reviewer_alias: str
    reason: str
    proposal_id: str | None = None
    edited_proposal: ExperimentProposalData | None = None
