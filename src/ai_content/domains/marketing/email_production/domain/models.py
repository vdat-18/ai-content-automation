"""Evidence-aware records for multi-brand Email production."""

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


class ContextComponent(StrEnum):
    BRAND = "brand"
    ACCOUNT = "account"
    PRODUCT = "product"
    OFFER = "offer"
    AUDIENCE_POLICY = "audience_policy"
    CONTENT_POLICY = "content_policy"
    DESIGN_SYSTEM = "design_system"
    CAMPAIGN_FRAMEWORK = "campaign_framework"
    VERSIONS = "versions"


class ContextStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class EmailProductionState(StrEnum):
    NEEDS_CONTEXT = "needs_context"
    BLOCKED_CONFLICT = "blocked_conflict"
    GENERATING = "generating"
    CONTENT_QA = "content_qa"
    REVISION_PENDING = "revision_pending"
    PREFLIGHT_CHECKING = "preflight_checking"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXCEPTION_POLICY = "exception_policy"
    EXCEPTION_OPERATIONAL = "exception_operational"


class ReviewOutcome(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    POLICY_BLOCK = "policy_block"


class HumanDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class EmailTrigger:
    trigger_id: str
    source_run_id: str
    source: str
    brand_id: str
    account_id: str
    objective: str
    scheduled_at: datetime
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("trigger_id", "source_run_id", "brand_id", "account_id"):
            _identifier(getattr(self, name), name)
        _aware(self.scheduled_at, "scheduled_at")
        if not self.source.strip() or not self.objective.strip() or not self.evidence_refs:
            raise ValueError("Trigger source, objective and evidence are required")


@dataclass(frozen=True)
class ContextEvidence:
    component: ContextComponent
    status: ContextStatus
    evidence_refs: tuple[str, ...]
    observed_at: datetime
    valid_until: datetime | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        if self.valid_until is not None:
            _aware(self.valid_until, "valid_until")
            if self.valid_until <= self.observed_at:
                raise ValueError("valid_until must be later than observed_at")
        if self.status != ContextStatus.UNKNOWN and not self.evidence_refs:
            raise ValueError("Known or conflicting context requires evidence")
        if self.status != ContextStatus.KNOWN and not self.detail:
            raise ValueError("Unknown or conflicting context requires detail")


@dataclass(frozen=True)
class EmailContextSnapshot:
    snapshot_id: str
    version: str
    brand_id: str
    account_id: str
    timezone: str
    collection_ref: str
    product_refs: tuple[str, ...]
    offer_ref: str | None
    audience_ref: str
    exclusion_ref: str
    approved_claim_refs: tuple[str, ...]
    asset_refs: tuple[str, ...]
    forbidden_phrases: tuple[str, ...]
    forbidden_punctuation: tuple[str, ...]
    cross_brand_terms: tuple[str, ...]
    components: tuple[ContextEvidence, ...]
    version_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "brand_id", "account_id", "collection_ref"):
            _identifier(getattr(self, name), name)
        _aware(self.captured_at, "captured_at")
        if not self.version.strip() or not self.timezone.strip():
            raise ValueError("Context version and timezone are required")
        if not self.product_refs or not self.asset_refs or not self.version_refs:
            raise ValueError("Product, asset and version references are required")
        component_names = [item.component for item in self.components]
        if len(component_names) != len(set(component_names)):
            raise ValueError("Context components must be unique")
        evidence = set(self.evidence_refs)
        if not evidence or any(
            not set(item.evidence_refs).issubset(evidence) for item in self.components
        ):
            raise ValueError("Context evidence must belong to the snapshot")


@dataclass(frozen=True)
class EmailSection:
    section_id: str
    heading: str
    body: str
    cta_label: str | None = None
    destination_url: str | None = None
    product_refs: tuple[str, ...] = ()
    asset_refs: tuple[str, ...] = ()
    design_note: str = ""

    def __post_init__(self) -> None:
        _identifier(self.section_id, "section_id")
        if not self.heading.strip() or not self.body.strip() or not self.design_note.strip():
            raise ValueError("Email section heading, body and design note are required")
        if (self.cta_label is None) != (self.destination_url is None):
            raise ValueError("CTA label and destination URL must be provided together")


@dataclass(frozen=True)
class EmailPackage:
    campaign_name: str
    subject_variants: tuple[str, ...]
    preview_text: str
    outline: tuple[str, ...]
    sections: tuple[EmailSection, ...]
    offer_ref: str | None
    claim_refs: tuple[str, ...]
    audience_ref: str
    exclusion_ref: str
    send_at: datetime
    timezone: str

    def __post_init__(self) -> None:
        _aware(self.send_at, "send_at")
        if not self.campaign_name.strip() or len(self.subject_variants) < 2:
            raise ValueError("Campaign name and at least two subject variants are required")
        if not self.preview_text.strip() or not self.outline or not self.sections:
            raise ValueError("Preview, outline and sections are required")

    @property
    def searchable_text(self) -> str:
        parts = [self.campaign_name, *self.subject_variants, self.preview_text, *self.outline]
        for section in self.sections:
            parts.extend(
                [
                    section.heading,
                    section.body,
                    section.cta_label or "",
                    section.design_note,
                ]
            )
        return "\n".join(parts)


@dataclass(frozen=True)
class SemanticReview:
    reviewer_version: str
    outcome: ReviewOutcome
    score: int
    issues: tuple[str, ...]
    repair_instructions: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reviewer_version.strip() or not 0 <= self.score <= 100:
            raise ValueError("Reviewer version and score are required")
        if self.outcome == ReviewOutcome.PASS and self.issues:
            raise ValueError("Passing review cannot contain issues")
        if self.outcome == ReviewOutcome.REVISE and not self.repair_instructions:
            raise ValueError("Revision review requires repair instructions")


@dataclass(frozen=True)
class EmailPackageVersion:
    version_id: str
    version_number: int
    package: EmailPackage
    generator_version: str
    input_hash: str
    prompt_version: str
    policy_version: str
    workflow_version: str
    created_at: datetime
    deterministic_issues: tuple[str, ...] = ()
    semantic_review: SemanticReview | None = None
    preview_ref: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.version_id, "version_id")
        _aware(self.created_at, "created_at")
        if self.version_number < 1:
            raise ValueError("version_number must be positive")
        if not all(
            value.strip()
            for value in (
                self.generator_version,
                self.input_hash,
                self.prompt_version,
                self.policy_version,
                self.workflow_version,
            )
        ):
            raise ValueError("Email version provenance is required")


@dataclass(frozen=True)
class ProductionIssue:
    code: str
    detail: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.code, "issue code")
        if not self.detail.strip():
            raise ValueError("Issue detail is required")


@dataclass(frozen=True)
class PreflightReference:
    run_id: str
    evaluation_id: str
    email_version_id: str
    classification: str
    allowed_for_approval: bool
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("run_id", "evaluation_id", "email_version_id"):
            _identifier(getattr(self, name), name)


@dataclass(frozen=True)
class EmailApprovalCard:
    email_version_id: str
    preflight_evaluation_id: str
    summary: str
    evidence_refs: tuple[str, ...]
    warnings: tuple[str, ...]
    decision: HumanDecision | None = None
    reviewer_alias: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        _identifier(self.email_version_id, "email_version_id")
        _identifier(self.preflight_evaluation_id, "preflight_evaluation_id")


@dataclass(frozen=True)
class EmailHandoffPreview:
    preview_id: str
    email_version_id: str
    preflight_evaluation_id: str
    account_id: str
    campaign_name: str
    scheduled_at: datetime
    timezone: str
    prohibited_external_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "preview_id",
            "email_version_id",
            "preflight_evaluation_id",
            "account_id",
        ):
            _identifier(getattr(self, name), name)
        _aware(self.scheduled_at, "scheduled_at")


@dataclass(frozen=True)
class EmailProductionJob:
    job_id: str
    source_run_id: str
    source_checksum_sha256: str
    trigger: EmailTrigger
    context: EmailContextSnapshot
    state: EmailProductionState
    versions: tuple[EmailPackageVersion, ...]
    issues: tuple[ProductionIssue, ...]
    preflight: PreflightReference | None
    approval_card: EmailApprovalCard | None
    handoff_preview: EmailHandoffPreview | None
    created_at: datetime
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _identifier(self.job_id, "job_id")
        _identifier(self.source_run_id, "source_run_id")
        _aware(self.created_at, "created_at")
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        if self.trigger.source_run_id != self.source_run_id:
            raise ValueError("Trigger and job source identity must match")

    @property
    def latest_version(self) -> EmailPackageVersion | None:
        return self.versions[-1] if self.versions else None

    def decide(
        self,
        decision: HumanDecision,
        email_version_id: str,
        preflight_evaluation_id: str,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
    ) -> EmailProductionJob:
        _aware(decided_at, "decided_at")
        if self.state != EmailProductionState.AWAITING_APPROVAL or self.approval_card is None:
            raise ValueError("Email production job is not awaiting approval")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and decision reason are required")
        card = self.approval_card
        if email_version_id != card.email_version_id:
            raise ValueError("Decision must pin the current Email version")
        if preflight_evaluation_id != card.preflight_evaluation_id:
            raise ValueError("Decision must pin the current preflight evaluation")
        updated_card = replace(
            card,
            decision=decision,
            reviewer_alias=reviewer_alias,
            reason=reason,
            decided_at=decided_at,
        )
        handoff = None
        state = EmailProductionState.REJECTED
        if decision == HumanDecision.APPROVE:
            assert self.latest_version is not None
            handoff = EmailHandoffPreview(
                preview_id=f"khp-{self.job_id}",
                email_version_id=email_version_id,
                preflight_evaluation_id=preflight_evaluation_id,
                account_id=self.context.account_id,
                campaign_name=self.latest_version.package.campaign_name,
                scheduled_at=self.latest_version.package.send_at,
                timezone=self.latest_version.package.timezone,
                prohibited_external_actions=(
                    "create_or_update_klaviyo_campaign",
                    "schedule_or_send_email",
                    "change_segment_or_suppression",
                    "change_coupon",
                ),
            )
            state = EmailProductionState.APPROVED
        return replace(
            self,
            state=state,
            approval_card=updated_card,
            handoff_preview=handoff,
            audit_log=(*self.audit_log, f"decision:{decision.value}:{email_version_id}"),
        )


__all__ = [
    "ContextComponent",
    "ContextEvidence",
    "ContextStatus",
    "EmailApprovalCard",
    "EmailContextSnapshot",
    "EmailHandoffPreview",
    "EmailPackage",
    "EmailPackageVersion",
    "EmailProductionJob",
    "EmailProductionState",
    "EmailSection",
    "EmailTrigger",
    "HumanDecision",
    "PreflightReference",
    "ProductionIssue",
    "ReviewOutcome",
    "SemanticReview",
]
