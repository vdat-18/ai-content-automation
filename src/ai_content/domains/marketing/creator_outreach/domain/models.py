"""Versioned records for Creator outreach, follow-up and reply handling."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")


def _identifier(value: str, name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


class OutreachState(StrEnum):
    NEEDS_CONTEXT = "needs_context"
    GENERATING = "generating"
    CONTENT_QA = "content_qa"
    REVISION_PENDING = "revision_pending"
    AWAITING_APPROVAL = "awaiting_approval"
    WAITING_REPLY = "waiting_reply"
    NEEDS_BUSINESS_REVIEW = "needs_business_review"
    AWAITING_DEAL_APPROVAL = "awaiting_deal_approval"
    READY_FOR_LARK_PREVIEW = "ready_for_lark_preview"
    CLOSED_DECLINED = "closed_declined"
    CLOSED_NO_REPLY = "closed_no_reply"
    REJECTED = "rejected"
    EXCEPTION_POLICY = "exception_policy"
    EXCEPTION_OPERATIONAL = "exception_operational"


class ReviewOutcome(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    POLICY_BLOCK = "policy_block"


class OutreachDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class DealDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


class ReplyOutcome(StrEnum):
    INTERESTED = "interested"
    DECLINED = "declined"
    NEGOTIATION = "negotiation"
    UNCLEAR = "unclear"


class ReplyFieldStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class CreatorContactTrigger:
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
    missing_fields: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "trigger_id",
            "source_run_id",
            "creator_run_id",
            "evaluation_id",
            "candidate_id",
            "campaign_id",
            "brand_id",
            "creator_id",
        ):
            _identifier(getattr(self, name), name)
        if self.source_decision not in {"contact", "shortlist"}:
            raise ValueError("Creator contact requires an approved contact or shortlist decision")
        if not self.creator_alias.strip() or not self.evidence_refs:
            raise ValueError("Creator alias and source evidence are required")


@dataclass(frozen=True)
class OutreachPolicy:
    version: str
    channel: str
    followup_interval_hours: int
    max_followups: int
    allowed_request_fields: tuple[str, ...]
    forbidden_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.channel.strip():
            raise ValueError("Outreach policy version and channel are required")
        if self.followup_interval_hours < 1 or self.max_followups < 0:
            raise ValueError("Follow-up interval and limit are invalid")
        if len(self.allowed_request_fields) != len(set(self.allowed_request_fields)):
            raise ValueError("Allowed request fields must be unique")


@dataclass(frozen=True)
class OutreachPlan:
    channel: str
    initial_message: str
    followup_messages: tuple[str, ...]
    requested_fields: tuple[str, ...]
    personalization_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.channel.strip() or not self.initial_message.strip():
            raise ValueError("Outreach channel and initial message are required")
        if any(not item.strip() for item in self.followup_messages):
            raise ValueError("Follow-up messages cannot be blank")
        if len(self.requested_fields) != len(set(self.requested_fields)):
            raise ValueError("Requested fields must be unique")

    @property
    def searchable_text(self) -> str:
        return "\n".join((self.initial_message, *self.followup_messages))


@dataclass(frozen=True)
class OutreachReview:
    reviewer_version: str
    outcome: ReviewOutcome
    issues: tuple[str, ...]
    repair_instructions: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reviewer_version.strip():
            raise ValueError("Reviewer version is required")
        if self.outcome == ReviewOutcome.PASS and self.issues:
            raise ValueError("Passing review cannot contain issues")
        if self.outcome == ReviewOutcome.REVISE and not self.repair_instructions:
            raise ValueError("Revision review requires repair instructions")


@dataclass(frozen=True)
class OutreachPlanVersion:
    version_id: str
    version_number: int
    plan: OutreachPlan
    generator_version: str
    input_hash: str
    prompt_version: str
    policy_version: str
    workflow_version: str
    created_at: datetime
    deterministic_issues: tuple[str, ...] = ()
    semantic_review: OutreachReview | None = None

    def __post_init__(self) -> None:
        _identifier(self.version_id, "version_id")
        _aware(self.created_at, "created_at")
        if self.version_number < 1:
            raise ValueError("version_number must be positive")


@dataclass(frozen=True)
class OutreachIssue:
    code: str
    detail: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.code, "issue code")
        if not self.detail.strip():
            raise ValueError("Issue detail is required")


@dataclass(frozen=True)
class OutreachApprovalCard:
    plan_version_id: str
    evaluation_id: str
    summary: str
    evidence_refs: tuple[str, ...]
    decision: OutreachDecision | None = None
    reviewer_alias: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        _identifier(self.plan_version_id, "plan_version_id")
        _identifier(self.evaluation_id, "evaluation_id")
        if self.decided_at is not None:
            _aware(self.decided_at, "decided_at")


@dataclass(frozen=True)
class DeliveryReceipt:
    receipt_id: str
    plan_version_id: str
    sequence: int
    channel: str
    sent_at: datetime
    idempotency_key: str
    synthetic: bool = True

    def __post_init__(self) -> None:
        _identifier(self.receipt_id, "receipt_id")
        _aware(self.sent_at, "sent_at")
        if self.sequence < 0 or not self.channel.strip() or not self.idempotency_key.strip():
            raise ValueError("Delivery receipt is invalid")


@dataclass(frozen=True)
class ReplyField:
    field_name: str
    status: ReplyFieldStatus
    value: str | None
    source_ref: str | None
    observed_at: datetime
    supports_criterion: bool | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        if not self.field_name.strip():
            raise ValueError("Reply field name is required")
        if self.status == ReplyFieldStatus.KNOWN and (
            not self.value or not self.source_ref or self.supports_criterion is None
        ):
            raise ValueError("Known reply evidence requires value, source and support judgement")
        if self.status == ReplyFieldStatus.UNKNOWN and self.value is not None:
            raise ValueError("Unknown reply evidence cannot carry a value")
        if self.status == ReplyFieldStatus.CONFLICT and not self.source_ref:
            raise ValueError("Conflicting reply evidence requires a source")


@dataclass(frozen=True)
class ReplyRecord:
    event_id: str
    event_checksum_sha256: str
    outcome: ReplyOutcome
    received_at: datetime
    source_ref: str
    summary: str
    evidence_package_id: str
    cumulative_fields: tuple[ReplyField, ...]
    suggested_response: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _identifier(self.evidence_package_id, "evidence_package_id")
        _aware(self.received_at, "received_at")
        if len(self.event_checksum_sha256) != 64:
            raise ValueError("event_checksum_sha256 must be SHA-256")
        if not self.source_ref.strip() or not self.summary.strip():
            raise ValueError("Reply source and sanitized summary are required")


@dataclass(frozen=True)
class CreatorEvaluationUpdate:
    evaluation_id: str
    evaluation_state: str
    lark_preview_state: str
    missing_fields: tuple[str, ...]
    preview_ref: str

    def __post_init__(self) -> None:
        _identifier(self.evaluation_id, "evaluation_id")
        if not self.evaluation_state.strip() or not self.lark_preview_state.strip():
            raise ValueError("Creator evaluation update state is required")


@dataclass(frozen=True)
class DealApprovalCard:
    reply_event_id: str
    evaluation_id: str
    summary: str
    evidence_refs: tuple[str, ...]
    decision: DealDecision | None = None
    reviewer_alias: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        _identifier(self.reply_event_id, "reply_event_id")
        _identifier(self.evaluation_id, "evaluation_id")
        if self.decided_at is not None:
            _aware(self.decided_at, "decided_at")


@dataclass(frozen=True)
class LarkHandoffPreview:
    preview_id: str
    candidate_id: str
    evaluation_id: str
    lark_preview_ref: str
    prohibited_external_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("preview_id", "candidate_id", "evaluation_id"):
            _identifier(getattr(self, name), name)
        if not self.lark_preview_ref.strip() or not self.prohibited_external_actions:
            raise ValueError("Lark handoff preview boundary is required")


@dataclass(frozen=True)
class CreatorOutreachRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    trigger: CreatorContactTrigger
    policy: OutreachPolicy
    state: OutreachState
    versions: tuple[OutreachPlanVersion, ...]
    issues: tuple[OutreachIssue, ...]
    outreach_approval: OutreachApprovalCard | None
    receipts: tuple[DeliveryReceipt, ...]
    next_followup_at: datetime | None
    reply: ReplyRecord | None
    evaluation_update: CreatorEvaluationUpdate | None
    deal_approval: DealApprovalCard | None
    handoff_preview: LarkHandoffPreview | None
    mapping_version: str
    target_base_ref: str
    field_mapping: tuple[tuple[str, str], ...]
    existing_record: tuple[tuple[str, str], ...]
    created_at: datetime
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.source_run_id, "source_run_id")
        _aware(self.created_at, "created_at")
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        if self.trigger.source_run_id != self.source_run_id:
            raise ValueError("Trigger and outreach source identity must match")
        if self.next_followup_at is not None:
            _aware(self.next_followup_at, "next_followup_at")

    @property
    def latest_version(self) -> OutreachPlanVersion | None:
        return self.versions[-1] if self.versions else None

    def decide_outreach(
        self,
        decision: OutreachDecision,
        plan_version_id: str,
        evaluation_id: str,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
    ) -> CreatorOutreachRun:
        _aware(decided_at, "decided_at")
        if self.state != OutreachState.AWAITING_APPROVAL or self.outreach_approval is None:
            raise ValueError("Outreach run is not awaiting approval")
        if plan_version_id != self.outreach_approval.plan_version_id:
            raise ValueError("Decision must pin the current outreach plan version")
        if evaluation_id != self.outreach_approval.evaluation_id:
            raise ValueError("Decision must pin the source evaluation version")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and reason are required")
        card = replace(
            self.outreach_approval,
            decision=decision,
            reviewer_alias=reviewer_alias,
            reason=reason,
            decided_at=decided_at,
        )
        return replace(
            self,
            state=(OutreachState.REJECTED if decision == OutreachDecision.REJECT else self.state),
            outreach_approval=card,
            audit_log=(*self.audit_log, f"outreach_decision:{decision.value}:{plan_version_id}"),
        )


__all__ = [
    "CreatorContactTrigger",
    "CreatorEvaluationUpdate",
    "CreatorOutreachRun",
    "DealApprovalCard",
    "DealDecision",
    "DeliveryReceipt",
    "LarkHandoffPreview",
    "OutreachApprovalCard",
    "OutreachDecision",
    "OutreachIssue",
    "OutreachPlan",
    "OutreachPlanVersion",
    "OutreachPolicy",
    "OutreachReview",
    "OutreachState",
    "ReplyField",
    "ReplyFieldStatus",
    "ReplyOutcome",
    "ReplyRecord",
    "ReviewOutcome",
]
