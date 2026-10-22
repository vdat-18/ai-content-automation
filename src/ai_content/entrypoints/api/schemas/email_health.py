"""API schemas for the Email Operations health pilot."""

from pydantic import BaseModel

from ai_content.domains.marketing.email_health.domain.models import (
    OperationalDecision,
    VerificationOutcome,
)


class EmailHealthObservationResponse(BaseModel):
    name: str
    status: str
    value_type: str
    account_id: str
    source_system: str
    integration_id: str | None
    boolean_value: bool | None
    decimal_value: str | None
    text_value: str | None
    source_ref: str | None
    reason: str | None
    observed_at: str


class EmailHealthAssessmentResponse(BaseModel):
    rule_id: str
    observation: str
    outcome: str
    severity: str
    operator: str
    expected_value: str
    observed_value: str | None
    sample_observation: str | None
    sample_value: str | None
    source_ref: str | None
    detail: str


class EmailHealthVerificationResponse(BaseModel):
    outcome: str
    evidence_ref: str
    reviewer_alias: str
    note: str
    verified_at: str


class EmailRemediationPreviewResponse(BaseModel):
    preview_id: str
    state: str
    action: str
    checklist: list[str]
    evidence_refs: list[str]
    missing_evidence: list[str]
    prohibited_external_actions: list[str]


class EmailHealthRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    issue_fingerprint: str
    snapshot_id: str
    subject_type: str
    subject_id: str
    brand_id: str
    account_id: str
    source_system: str
    integration_id: str | None
    timezone: str
    source_version: str
    observed_at: str
    upstream_report_refs: list[str]
    observations: list[EmailHealthObservationResponse]
    evaluation_id: str
    evaluation_version: int
    evaluation_state: str
    classification: str
    recommendation: str
    rule_set_id: str
    rule_version: str
    rule_status: str
    rule_source: str
    assessments: list[EmailHealthAssessmentResponse]
    evidence_refs: list[str]
    missing_observations: list[str]
    issue_state: str
    decision: str | None
    decision_evaluation_id: str | None
    reviewer_alias: str | None
    decision_reason: str | None
    decided_at: str | None
    remediation_preview: EmailRemediationPreviewResponse | None
    verifications: list[EmailHealthVerificationResponse]


class EmailHealthRunListResponse(BaseModel):
    items: list[EmailHealthRunResponse]
    total: int


class EmailHealthDecisionRequest(BaseModel):
    evaluation_id: str
    decision: OperationalDecision
    reviewer_alias: str
    reason: str


class EmailHealthVerificationRequest(BaseModel):
    outcome: VerificationOutcome
    evidence_ref: str
    reviewer_alias: str
    note: str
