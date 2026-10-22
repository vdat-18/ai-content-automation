"""API schemas for Creator outreach pilot."""

from datetime import datetime

from pydantic import BaseModel, Field

from ai_content.domains.marketing.creator_outreach.domain.models import (
    DealDecision,
    OutreachDecision,
    ReplyFieldStatus,
    ReplyOutcome,
)

from .creator_operations import CreatorRunResponse


class OutreachPlanResponse(BaseModel):
    channel: str
    initial_message: str
    followup_messages: list[str]
    requested_fields: list[str]
    personalization_evidence_refs: list[str]


class OutreachReviewResponse(BaseModel):
    reviewer_version: str
    outcome: str
    issues: list[str]
    repair_instructions: list[str]
    evidence_refs: list[str]


class OutreachVersionResponse(BaseModel):
    version_id: str
    version_number: int
    plan: OutreachPlanResponse
    generator_version: str
    input_hash: str
    prompt_version: str
    policy_version: str
    workflow_version: str
    created_at: datetime
    deterministic_issues: list[str]
    semantic_review: OutreachReviewResponse | None


class OutreachIssueResponse(BaseModel):
    code: str
    detail: str
    evidence_refs: list[str]


class OutreachApprovalResponse(BaseModel):
    plan_version_id: str
    evaluation_id: str
    summary: str
    evidence_refs: list[str]
    decision: str | None
    reviewer_alias: str | None
    reason: str | None
    decided_at: datetime | None


class DeliveryReceiptResponse(BaseModel):
    receipt_id: str
    plan_version_id: str
    sequence: int
    channel: str
    sent_at: datetime
    idempotency_key: str
    synthetic: bool


class ReplyFieldResponse(BaseModel):
    field_name: str
    status: str
    value: str | None
    source_ref: str | None
    observed_at: datetime
    supports_criterion: bool | None


class ReplyResponse(BaseModel):
    event_id: str
    event_checksum_sha256: str
    outcome: str
    received_at: datetime
    source_ref: str
    summary: str
    evidence_package_id: str
    cumulative_fields: list[ReplyFieldResponse]
    suggested_response: str | None


class EvaluationUpdateResponse(BaseModel):
    evaluation_id: str
    evaluation_state: str
    lark_preview_state: str
    missing_fields: list[str]
    preview_ref: str


class DealApprovalResponse(BaseModel):
    reply_event_id: str
    evaluation_id: str
    summary: str
    evidence_refs: list[str]
    decision: str | None
    reviewer_alias: str | None
    reason: str | None
    decided_at: datetime | None


class LarkHandoffResponse(BaseModel):
    preview_id: str
    candidate_id: str
    evaluation_id: str
    lark_preview_ref: str
    prohibited_external_actions: list[str]


class ContactTriggerResponse(BaseModel):
    trigger_id: str
    source_run_id: str
    creator_run_id: str
    evaluation_id: str
    candidate_id: str
    campaign_id: str
    brand_id: str
    creator_id: str
    creator_alias: str
    source_decision: str
    missing_fields: list[str]
    evidence_refs: list[str]


class OutreachPolicyResponse(BaseModel):
    version: str
    channel: str
    followup_interval_hours: int
    max_followups: int
    allowed_request_fields: list[str]
    forbidden_terms: list[str]


class CreatorOutreachRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    trigger: ContactTriggerResponse
    policy: OutreachPolicyResponse
    state: str
    versions: list[OutreachVersionResponse]
    issues: list[OutreachIssueResponse]
    outreach_approval: OutreachApprovalResponse | None
    receipts: list[DeliveryReceiptResponse]
    next_followup_at: datetime | None
    reply: ReplyResponse | None
    evaluation_update: EvaluationUpdateResponse | None
    deal_approval: DealApprovalResponse | None
    handoff_preview: LarkHandoffResponse | None
    mapping_version: str
    target_base_ref: str
    created_at: datetime
    audit_log: list[str]


class CreatorOutreachListResponse(BaseModel):
    items: list[CreatorOutreachRunResponse]
    total: int


class CreatorOutreachPipelineResponse(BaseModel):
    outreach: CreatorOutreachRunResponse
    creator_evaluation: CreatorRunResponse


class OutreachDecisionRequest(BaseModel):
    plan_version_id: str
    evaluation_id: str
    decision: OutreachDecision
    reviewer_alias: str
    reason: str


class ProcessFollowupsRequest(BaseModel):
    as_of: datetime
    run_id: str | None = None


class ProcessFollowupsResponse(BaseModel):
    items: list[CreatorOutreachRunResponse]
    total: int


class ReplyFieldRequest(BaseModel):
    field_name: str
    status: ReplyFieldStatus
    value: str | None = None
    source_ref: str | None = None
    observed_at: datetime
    supports_criterion: bool | None = None


class CreatorReplyRequest(BaseModel):
    event_id: str
    outcome: ReplyOutcome
    received_at: datetime
    source_ref: str
    summary: str
    evidence_package_id: str
    cumulative_fields: list[ReplyFieldRequest] = Field(default_factory=list)
    suggested_response: str | None = None


class DealDecisionRequest(BaseModel):
    reply_event_id: str
    evaluation_id: str
    decision: DealDecision
    reviewer_alias: str
    reason: str
