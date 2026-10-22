"""Evidence-based records for Email Operations QA and health."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _identifier(value: str, name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


class EmailHealthSubjectType(StrEnum):
    CAMPAIGN = "campaign"
    FLOW = "flow"
    ACCOUNT = "account"
    METRIC = "metric"
    FORM = "form"
    COUPON = "coupon"


class HealthObservationName(StrEnum):
    CONSENT_PROTECTION = "consent_protection"
    SUPPRESSION_PROTECTION = "suppression_protection"
    LINKS_VALID = "links_valid"
    UTM_PRESENT = "utm_present"
    COUPON_VALID = "coupon_valid"
    SMART_SENDING_ENABLED = "smart_sending_enabled"
    TIMEZONE_MATCH = "timezone_match"
    NAMING_VALID = "naming_valid"
    PREVIEW_AVAILABLE = "preview_available"
    METRIC_IDENTITY_VALID = "metric_identity_valid"
    EVENT_FRESHNESS_HOURS = "event_freshness_hours"
    FLOW_FILTER_VALID = "flow_filter_valid"
    STOP_CONDITION_VALID = "stop_condition_valid"
    REENTRY_VALID = "reentry_valid"
    COLLECTION_PROPERTY_VALID = "collection_property_valid"
    FORM_LIST_MAPPING_VALID = "form_list_mapping_valid"
    BOUNCE_RATE = "bounce_rate"
    SPAM_COMPLAINT_RATE = "spam_complaint_rate"
    UNSUBSCRIBE_RATE = "unsubscribe_rate"
    DELIVERED_COUNT = "delivered_count"
    DELIVERABILITY_ALERT_PRESENT = "deliverability_alert_present"
    FLOW_ACTIVE = "flow_active"
    ORDER_EVENT_AVAILABLE = "order_event_available"
    REPORT_RECONCILED = "report_reconciled"


class ObservationStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class ObservationValueType(StrEnum):
    BOOLEAN = "boolean"
    DECIMAL = "decimal"
    TEXT = "text"


class HealthRuleOperator(StrEnum):
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    EQUALS = "equals"


class HealthRuleStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class HealthSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


class HealthCheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class EmailHealthClassification(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    BLOCKED = "blocked"
    DATA_HEALTH_EXCEPTION = "data_health_exception"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class EmailHealthEvaluationState(StrEnum):
    HEALTHY = "healthy"
    READY_FOR_TRIAGE = "ready_for_triage"
    NEEDS_EVIDENCE = "needs_evidence"
    BLOCKED_CONFLICT = "blocked_conflict"


class RemediationAction(StrEnum):
    NONE = "none"
    CORRECT_CONFIGURATION = "correct_configuration"
    INVESTIGATE_SOURCE = "investigate_source"
    REVIEW_DELIVERABILITY = "review_deliverability"
    REQUEST_EVIDENCE = "request_evidence"
    MANUAL_REVIEW = "manual_review"


class OperationalDecision(StrEnum):
    APPROVE_ACTION = "approve_action"
    DEFER = "defer"
    DISMISS = "dismiss"


class IssueState(StrEnum):
    HEALTHY = "healthy"
    OPEN = "open"
    ACTION_APPROVED = "action_approved"
    DEFERRED = "deferred"
    DISMISSED = "dismissed"
    VERIFIED_RESOLVED = "verified_resolved"


class RemediationPreviewState(StrEnum):
    NOT_RELEASED = "not_released"
    PREVIEW_READY = "preview_ready"
    VERIFIED = "verified"


class VerificationOutcome(StrEnum):
    RESOLVED = "resolved"
    STILL_OPEN = "still_open"


@dataclass(frozen=True)
class EmailHealthSubject:
    subject_type: EmailHealthSubjectType
    subject_id: str
    brand_id: str
    account_id: str
    source_system: str
    integration_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("subject_id", "brand_id", "account_id"):
            _identifier(getattr(self, name), name)
        if self.integration_id is not None:
            _identifier(self.integration_id, "integration_id")
        if not self.source_system.strip():
            raise ValueError("source_system is required")


@dataclass(frozen=True)
class HealthObservation:
    name: HealthObservationName
    status: ObservationStatus
    value_type: ObservationValueType
    account_id: str
    source_system: str
    integration_id: str | None
    source_ref: str | None
    observed_at: datetime
    boolean_value: bool | None = None
    decimal_value: Decimal | None = None
    text_value: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        _identifier(self.account_id, "account_id")
        if self.integration_id is not None:
            _identifier(self.integration_id, "integration_id")
        if not self.source_system.strip():
            raise ValueError("Observation source_system is required")
        values = (self.boolean_value, self.decimal_value, self.text_value)
        populated = sum(value is not None for value in values)
        if self.status == ObservationStatus.KNOWN:
            if populated != 1 or not self.source_ref:
                raise ValueError("Known observation requires exactly one value and source_ref")
            if self.value_type == ObservationValueType.BOOLEAN and self.boolean_value is None:
                raise ValueError("Boolean observation requires boolean_value")
            if self.value_type == ObservationValueType.DECIMAL and self.decimal_value is None:
                raise ValueError("Decimal observation requires decimal_value")
            if self.value_type == ObservationValueType.TEXT and self.text_value is None:
                raise ValueError("Text observation requires text_value")
            if self.decimal_value is not None and self.decimal_value < 0:
                raise ValueError("Known decimal observation cannot be negative")
        elif populated:
            raise ValueError("Unknown, conflict or not-applicable observation cannot carry a value")
        if self.status != ObservationStatus.KNOWN and not self.reason:
            raise ValueError("Non-known observation requires a reason")
        if self.status == ObservationStatus.CONFLICT and not self.source_ref:
            raise ValueError("Conflicting observation requires source_ref")


@dataclass(frozen=True)
class EmailOperationsSnapshot:
    snapshot_id: str
    subject: EmailHealthSubject
    timezone: str
    source_version: str
    observations: tuple[HealthObservation, ...]
    observed_at: datetime
    upstream_report_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        _aware(self.observed_at, "observed_at")
        if not self.timezone.strip() or not self.source_version.strip():
            raise ValueError("Snapshot timezone and source_version are required")
        names = [item.name for item in self.observations]
        if len(names) != len(set(names)):
            raise ValueError("Observation names must be unique within a snapshot")
        if any(item.account_id != self.subject.account_id for item in self.observations):
            raise ValueError("Observation account must match the snapshot subject account")
        for reference in self.upstream_report_refs:
            _identifier(reference, "upstream_report_ref")


@dataclass(frozen=True)
class EmailHealthRule:
    rule_id: str
    subject_type: EmailHealthSubjectType
    observation: HealthObservationName
    operator: HealthRuleOperator
    severity: HealthSeverity
    failure_classification: EmailHealthClassification
    recommendation: RemediationAction
    description: str
    expected_boolean: bool | None = None
    threshold_decimal: Decimal | None = None
    expected_text: str | None = None
    sample_observation: HealthObservationName | None = None
    minimum_sample: Decimal | None = None

    def __post_init__(self) -> None:
        _identifier(self.rule_id, "rule_id")
        if not self.description.strip():
            raise ValueError("Rule description is required")
        expected = (self.expected_boolean, self.threshold_decimal, self.expected_text)
        if sum(value is not None for value in expected) != 1:
            raise ValueError("Rule requires exactly one expected value")
        if self.operator in {HealthRuleOperator.IS_TRUE, HealthRuleOperator.IS_FALSE}:
            if self.expected_boolean is None:
                raise ValueError("Boolean operator requires expected_boolean")
            if self.expected_boolean != (self.operator == HealthRuleOperator.IS_TRUE):
                raise ValueError("Boolean expected value must match the selected operator")
        elif self.operator in {
            HealthRuleOperator.LESS_THAN,
            HealthRuleOperator.LESS_THAN_OR_EQUAL,
            HealthRuleOperator.GREATER_THAN,
            HealthRuleOperator.GREATER_THAN_OR_EQUAL,
        }:
            if self.threshold_decimal is None or self.threshold_decimal < 0:
                raise ValueError("Numeric operator requires a non-negative threshold")
        elif self.expected_text is None:
            raise ValueError("equals operator requires expected_text")
        if (self.sample_observation is None) != (self.minimum_sample is None):
            raise ValueError("Sample observation and minimum sample must be configured together")
        if self.minimum_sample is not None and self.minimum_sample < 0:
            raise ValueError("minimum_sample cannot be negative")


@dataclass(frozen=True)
class EmailHealthRuleSet:
    rule_set_id: str
    version: str
    status: HealthRuleStatus
    effective_at: datetime
    source: str
    rules: tuple[EmailHealthRule, ...]

    def __post_init__(self) -> None:
        _identifier(self.rule_set_id, "rule_set_id")
        _aware(self.effective_at, "effective_at")
        if not self.version.strip() or not self.source.strip() or not self.rules:
            raise ValueError("Rule set version, source and rules are required")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Rule IDs must be unique")


@dataclass(frozen=True)
class HealthCheckAssessment:
    rule_id: str
    observation: HealthObservationName
    outcome: HealthCheckOutcome
    severity: HealthSeverity
    operator: HealthRuleOperator
    expected_value: str
    observed_value: str | None
    sample_observation: HealthObservationName | None
    sample_value: Decimal | None
    source_ref: str | None
    detail: str


@dataclass(frozen=True)
class EmailHealthEvaluation:
    evaluation_id: str
    version_number: int
    state: EmailHealthEvaluationState
    classification: EmailHealthClassification
    recommendation: RemediationAction
    rule_set_id: str
    rule_version: str
    rule_status: HealthRuleStatus
    rule_source: str
    assessments: tuple[HealthCheckAssessment, ...]
    evidence_refs: tuple[str, ...]
    missing_observations: tuple[HealthObservationName, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.evaluation_id, "evaluation_id")
        _aware(self.created_at, "created_at")
        if self.version_number < 1:
            raise ValueError("version_number must be positive")


@dataclass(frozen=True)
class RemediationPreview:
    preview_id: str
    state: RemediationPreviewState
    source_run_id: str
    source_evaluation_id: str
    action: RemediationAction
    checklist: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    missing_evidence: tuple[HealthObservationName, ...]
    prohibited_external_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("preview_id", "source_run_id", "source_evaluation_id"):
            _identifier(getattr(self, name), name)
        if not self.checklist:
            raise ValueError("Remediation preview requires a checklist")


@dataclass(frozen=True)
class VerificationRecord:
    outcome: VerificationOutcome
    evidence_ref: str
    reviewer_alias: str
    note: str
    verified_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.evidence_ref, "evidence_ref")
        _aware(self.verified_at, "verified_at")
        if not self.reviewer_alias.strip() or not self.note.strip():
            raise ValueError("Verification reviewer and note are required")


@dataclass(frozen=True)
class EmailHealthRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    issue_fingerprint: str
    snapshot: EmailOperationsSnapshot
    evaluation: EmailHealthEvaluation
    created_at: datetime
    issue_state: IssueState
    decision: OperationalDecision | None = None
    decision_evaluation_id: str | None = None
    reviewer_alias: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    remediation_preview: RemediationPreview | None = None
    verifications: tuple[VerificationRecord, ...] = ()
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("run_id", "source_run_id", "issue_fingerprint"):
            _identifier(getattr(self, name), name)
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        _aware(self.created_at, "created_at")
        preview = self.remediation_preview
        if preview is not None and (
            preview.source_run_id != self.run_id
            or preview.source_evaluation_id != self.evaluation.evaluation_id
        ):
            raise ValueError("Remediation preview must match its health run")

    def decide(
        self,
        decision: OperationalDecision,
        evaluation_id: str,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
    ) -> EmailHealthRun:
        _aware(decided_at, "decided_at")
        if self.decision is not None:
            raise ValueError("Operational decision has already been recorded")
        if self.evaluation.state == EmailHealthEvaluationState.HEALTHY:
            raise ValueError("Healthy evaluations do not require an operational decision")
        if evaluation_id != self.evaluation.evaluation_id:
            raise ValueError("Decision must pin the current evaluation version")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and decision reason are required")
        if decision == OperationalDecision.APPROVE_ACTION and (
            self.evaluation.state != EmailHealthEvaluationState.READY_FOR_TRIAGE
        ):
            raise ValueError("Incomplete or conflicting evidence blocks action approval")
        preview = self.remediation_preview
        state = (
            IssueState.DEFERRED if decision == OperationalDecision.DEFER else IssueState.DISMISSED
        )
        if decision == OperationalDecision.APPROVE_ACTION:
            if preview is None:
                raise ValueError("Action approval requires a remediation preview")
            preview = replace(preview, state=RemediationPreviewState.PREVIEW_READY)
            state = IssueState.ACTION_APPROVED
        return replace(
            self,
            decision=decision,
            decision_evaluation_id=evaluation_id,
            reviewer_alias=reviewer_alias,
            decision_reason=reason,
            decided_at=decided_at,
            remediation_preview=preview,
            issue_state=state,
            audit_log=(*self.audit_log, f"decision:{decision.value}:{evaluation_id}"),
        )

    def verify(
        self,
        outcome: VerificationOutcome,
        evidence_ref: str,
        reviewer_alias: str,
        note: str,
        verified_at: datetime,
    ) -> EmailHealthRun:
        if self.issue_state not in {IssueState.ACTION_APPROVED, IssueState.VERIFIED_RESOLVED}:
            raise ValueError("Verification requires an approved remediation action")
        if evidence_ref in self.evaluation.evidence_refs or any(
            item.evidence_ref == evidence_ref for item in self.verifications
        ):
            raise ValueError("Verification requires new evidence")
        record = VerificationRecord(outcome, evidence_ref, reviewer_alias, note, verified_at)
        preview = self.remediation_preview
        state = IssueState.ACTION_APPROVED
        if outcome == VerificationOutcome.RESOLVED:
            state = IssueState.VERIFIED_RESOLVED
            if preview is not None:
                preview = replace(preview, state=RemediationPreviewState.VERIFIED)
        return replace(
            self,
            issue_state=state,
            remediation_preview=preview,
            verifications=(*self.verifications, record),
            audit_log=(*self.audit_log, f"verification:{outcome.value}:{evidence_ref}"),
        )


__all__ = [
    "EmailHealthClassification",
    "EmailHealthEvaluation",
    "EmailHealthEvaluationState",
    "EmailHealthRule",
    "EmailHealthRuleSet",
    "EmailHealthRun",
    "EmailHealthSubject",
    "EmailHealthSubjectType",
    "EmailOperationsSnapshot",
    "HealthCheckAssessment",
    "HealthCheckOutcome",
    "HealthObservation",
    "HealthObservationName",
    "HealthRuleOperator",
    "HealthRuleStatus",
    "HealthSeverity",
    "IssueState",
    "ObservationStatus",
    "ObservationValueType",
    "OperationalDecision",
    "RemediationAction",
    "RemediationPreview",
    "RemediationPreviewState",
    "VerificationOutcome",
    "VerificationRecord",
]
