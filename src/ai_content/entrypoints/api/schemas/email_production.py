"""API schemas for the Email production pilot."""

from pydantic import BaseModel

from ai_content.domains.marketing.email_production.domain.models import HumanDecision

from .email_health import EmailHealthRunResponse


class EmailTriggerResponse(BaseModel):
    trigger_id: str
    source_run_id: str
    source: str
    brand_id: str
    account_id: str
    objective: str
    scheduled_at: str
    evidence_refs: list[str]


class EmailContextEvidenceResponse(BaseModel):
    component: str
    status: str
    evidence_refs: list[str]
    observed_at: str
    valid_until: str | None
    detail: str | None


class EmailContextResponse(BaseModel):
    snapshot_id: str
    version: str
    brand_id: str
    account_id: str
    timezone: str
    collection_ref: str
    product_refs: list[str]
    offer_ref: str | None
    audience_ref: str
    exclusion_ref: str
    approved_claim_refs: list[str]
    asset_refs: list[str]
    forbidden_phrases: list[str]
    forbidden_punctuation: list[str]
    cross_brand_terms: list[str]
    components: list[EmailContextEvidenceResponse]
    version_refs: list[str]
    evidence_refs: list[str]
    captured_at: str


class EmailSectionResponse(BaseModel):
    section_id: str
    heading: str
    body: str
    cta_label: str | None
    destination_url: str | None
    product_refs: list[str]
    asset_refs: list[str]
    design_note: str


class EmailPackageResponse(BaseModel):
    campaign_name: str
    subject_variants: list[str]
    preview_text: str
    outline: list[str]
    sections: list[EmailSectionResponse]
    offer_ref: str | None
    claim_refs: list[str]
    audience_ref: str
    exclusion_ref: str
    send_at: str
    timezone: str


class EmailSemanticReviewResponse(BaseModel):
    reviewer_version: str
    outcome: str
    score: int
    issues: list[str]
    repair_instructions: list[str]
    evidence_refs: list[str]


class EmailPackageVersionResponse(BaseModel):
    version_id: str
    version_number: int
    package: EmailPackageResponse
    generator_version: str
    input_hash: str
    prompt_version: str
    policy_version: str
    workflow_version: str
    created_at: str
    deterministic_issues: list[str]
    semantic_review: EmailSemanticReviewResponse | None
    preview_ref: str | None


class EmailProductionIssueResponse(BaseModel):
    code: str
    detail: str
    evidence_refs: list[str]


class EmailPreflightReferenceResponse(BaseModel):
    run_id: str
    evaluation_id: str
    email_version_id: str
    classification: str
    allowed_for_approval: bool
    warnings: list[str]


class EmailApprovalCardResponse(BaseModel):
    email_version_id: str
    preflight_evaluation_id: str
    summary: str
    evidence_refs: list[str]
    warnings: list[str]
    decision: str | None
    reviewer_alias: str | None
    reason: str | None
    decided_at: str | None


class EmailHandoffPreviewResponse(BaseModel):
    preview_id: str
    email_version_id: str
    preflight_evaluation_id: str
    account_id: str
    campaign_name: str
    scheduled_at: str
    timezone: str
    prohibited_external_actions: list[str]


class EmailProductionJobResponse(BaseModel):
    job_id: str
    source_run_id: str
    source_checksum_sha256: str
    trigger: EmailTriggerResponse
    context: EmailContextResponse
    state: str
    versions: list[EmailPackageVersionResponse]
    issues: list[EmailProductionIssueResponse]
    preflight: EmailPreflightReferenceResponse | None
    approval_card: EmailApprovalCardResponse | None
    handoff_preview: EmailHandoffPreviewResponse | None
    created_at: str
    audit_log: list[str]


class EmailProductionJobListResponse(BaseModel):
    items: list[EmailProductionJobResponse]
    total: int


class EmailProductionDecisionRequest(BaseModel):
    email_version_id: str
    preflight_evaluation_id: str
    decision: HumanDecision
    reviewer_alias: str
    reason: str


class EmailProductionPipelineResponse(BaseModel):
    job: EmailProductionJobResponse
    preflight: EmailHealthRunResponse | None


__all__ = [
    "EmailHandoffPreviewResponse",
    "EmailProductionDecisionRequest",
    "EmailProductionJobListResponse",
    "EmailProductionJobResponse",
    "EmailProductionPipelineResponse",
]
