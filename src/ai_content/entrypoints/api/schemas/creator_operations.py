"""API schemas for Creator Operations pilot."""

from pydantic import BaseModel

from ai_content.domains.marketing.creator_operations.domain.models import CandidateDecision


class CreatorCriterionResponse(BaseModel):
    criterion: str
    outcome: str
    evidence_refs: list[str]
    detail: str
    missing_fields: list[str]


class CreatorEvaluationVersionResponse(BaseModel):
    evaluation_id: str
    version_number: int
    package_id: str
    state: str
    created_at: str
    policy_version: str
    criteria: list[CreatorCriterionResponse]


class LarkPreviewFieldResponse(BaseModel):
    target_field: str
    current_value: str | None
    proposed_value: str | None
    action: str
    source_ref: str | None


class LarkPreviewResponse(BaseModel):
    mapping_version: str
    target_base_ref: str
    state: str
    fields: list[LarkPreviewFieldResponse]


class CreatorRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    candidate_id: str
    campaign_id: str
    brand_id: str
    store_id: str
    sku_id: str
    creator_id: str
    creator_alias: str
    source_platform: str
    policy_version: str
    location_reference_version: str
    created_at: str
    decision: str | None
    decision_version_id: str | None
    reviewer_alias: str | None
    decision_reason: str | None
    decided_at: str | None
    evaluations: list[CreatorEvaluationVersionResponse]
    preview: LarkPreviewResponse


class CreatorRunListResponse(BaseModel):
    items: list[CreatorRunResponse]
    total: int


class CreatorDecisionRequest(BaseModel):
    evaluation_id: str
    decision: CandidateDecision
    reviewer_alias: str
    reason: str
