"""Business records for evidence-based creator evaluation and Lark preview."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _identifier(value: str, name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


class FieldStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class CriterionOutcome(StrEnum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class EvaluationState(StrEnum):
    NEEDS_EVIDENCE = "needs_evidence"
    READY_FOR_REVIEW = "ready_for_review"


class CandidateDecision(StrEnum):
    CONTACT = "contact"
    SHORTLIST = "shortlist"
    HOLD = "hold"
    EXCLUDE = "exclude"


class HandoffState(StrEnum):
    PREVIEW_READY = "preview_ready"
    BLOCKED_CONFLICT = "blocked_conflict"


class PreviewAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"
    SKIP_UNKNOWN = "skip_unknown"


@dataclass(frozen=True)
class CampaignRequirement:
    campaign_id: str
    brand_id: str
    store_id: str
    sku_id: str
    market: str
    target_creators: int
    brief: str
    version: str

    def __post_init__(self) -> None:
        for name in ("campaign_id", "brand_id", "store_id", "sku_id"):
            _identifier(getattr(self, name), name)
        if self.target_creators < 1:
            raise ValueError("target_creators must be positive")
        if not self.market.strip() or not self.brief.strip() or not self.version.strip():
            raise ValueError("Campaign market, brief and version are required")


@dataclass(frozen=True)
class CreatorProfile:
    creator_id: str
    source_platform: str
    source_creator_id: str
    display_alias: str

    def __post_init__(self) -> None:
        _identifier(self.creator_id, "creator_id")
        if not all(
            value.strip()
            for value in (self.source_platform, self.source_creator_id, self.display_alias)
        ):
            raise ValueError("Creator source identity and alias are required")


@dataclass(frozen=True)
class EvidenceFact:
    field_name: str
    status: FieldStatus
    value: str | None
    source_ref: str | None
    observed_at: datetime
    supports_criterion: bool | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        if not self.field_name.strip():
            raise ValueError("Evidence field_name is required")
        if self.status == FieldStatus.KNOWN and (not self.value or not self.source_ref):
            raise ValueError("Known evidence requires a value and source_ref")
        if self.status == FieldStatus.KNOWN and self.supports_criterion is None:
            raise ValueError("Known criterion evidence requires an explicit support judgement")
        if self.status == FieldStatus.UNKNOWN and self.value is not None:
            raise ValueError("Unknown evidence cannot carry a value")
        if self.status == FieldStatus.CONFLICT and not self.source_ref:
            raise ValueError("Conflicting evidence requires a source_ref")


@dataclass(frozen=True)
class EvidencePackage:
    package_id: str
    stage: str
    facts: tuple[EvidenceFact, ...]

    def __post_init__(self) -> None:
        _identifier(self.package_id, "package_id")
        names = [fact.field_name for fact in self.facts]
        if len(names) != len(set(names)):
            raise ValueError("Evidence package field names must be unique")


@dataclass(frozen=True)
class CriterionAssessment:
    criterion: str
    outcome: CriterionOutcome
    evidence_refs: tuple[str, ...]
    detail: str
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationVersion:
    evaluation_id: str
    version_number: int
    package_id: str
    state: EvaluationState
    criteria: tuple[CriterionAssessment, ...]
    created_at: datetime
    policy_version: str

    def __post_init__(self) -> None:
        _identifier(self.evaluation_id, "evaluation_id")
        _aware(self.created_at, "created_at")
        if self.version_number < 1:
            raise ValueError("version_number must be positive")


@dataclass(frozen=True)
class PreviewField:
    target_field: str
    current_value: str | None
    proposed_value: str | None
    action: PreviewAction
    source_ref: str | None


@dataclass(frozen=True)
class LarkDataPreview:
    mapping_version: str
    target_base_ref: str
    state: HandoffState
    fields: tuple[PreviewField, ...]


@dataclass(frozen=True)
class CreatorEvaluationRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    campaign: CampaignRequirement
    creator: CreatorProfile
    candidate_id: str
    policy_version: str
    location_reference_store_id: str
    location_reference_version: str
    evaluations: tuple[EvaluationVersion, ...]
    preview: LarkDataPreview
    created_at: datetime
    decision: CandidateDecision | None = None
    decision_version_id: str | None = None
    reviewer_alias: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("run_id", "source_run_id", "candidate_id"):
            _identifier(getattr(self, name), name)
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        _aware(self.created_at, "created_at")
        if not self.evaluations:
            raise ValueError("At least one evaluation version is required")
        if self.location_reference_store_id != self.campaign.store_id:
            raise ValueError("Customer-location reference must match campaign store")

    @property
    def latest_evaluation(self) -> EvaluationVersion:
        return self.evaluations[-1]

    def decide(
        self,
        decision: CandidateDecision,
        evaluation_id: str,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
    ) -> CreatorEvaluationRun:
        _aware(decided_at, "decided_at")
        if self.decision is not None:
            raise ValueError("Candidate decision has already been recorded")
        if evaluation_id != self.latest_evaluation.evaluation_id:
            raise ValueError("Decision must pin the latest evaluation version")
        if (
            decision == CandidateDecision.SHORTLIST
            and self.preview.state != HandoffState.PREVIEW_READY
        ):
            raise ValueError("Conflicting Lark preview blocks shortlist decision")
        if (
            decision == CandidateDecision.SHORTLIST
            and self.latest_evaluation.state != EvaluationState.READY_FOR_REVIEW
        ):
            raise ValueError("Candidate still needs evidence and cannot be decided")
        if decision == CandidateDecision.CONTACT and any(
            item.outcome in {CriterionOutcome.NOT_SUPPORTED, CriterionOutcome.CONFLICT}
            for item in self.latest_evaluation.criteria
        ):
            raise ValueError("Conflicting or unsupported evidence blocks contact approval")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and decision reason are required")
        return replace(
            self,
            decision=decision,
            decision_version_id=evaluation_id,
            reviewer_alias=reviewer_alias,
            decision_reason=reason,
            decided_at=decided_at,
            audit_log=(*self.audit_log, f"decision:{decision.value}:{evaluation_id}"),
        )


__all__ = [
    "CampaignRequirement",
    "CandidateDecision",
    "CreatorEvaluationRun",
    "CreatorProfile",
    "CriterionAssessment",
    "CriterionOutcome",
    "EvaluationState",
    "EvaluationVersion",
    "EvidenceFact",
    "EvidencePackage",
    "FieldStatus",
    "HandoffState",
    "LarkDataPreview",
    "PreviewAction",
    "PreviewField",
]
