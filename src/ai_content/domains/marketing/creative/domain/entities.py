"""Domain entities for Creative subdomain.

Key entities:
- CreativeJob: The logical creative request (stable identity, one SKU cycle)
- AssetVersion: Each generation attempt (versioned, immutable)
- ApprovalCard: Human review card pointing at the QA-passing version
- LineageEntry: Immutable lineage relation (context/idea/version/qa/approval)
- AuditEntry: Immutable audit record
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .reviews import (
    CriterionReview,
    RepairAction,
    ReviewEvidence,
    ReviewOutcome,
    SemanticIssue,
)


class CreativeJobStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    COLLECTING_CONTEXT = "collecting_context"
    IDEA_GENERATING = "idea_generating"
    IDEA_REVIEW = "idea_review"
    BRIEF_READY = "brief_ready"
    GENERATING = "generating"
    QA_CHECKING = "qa_checking"
    REVISE_PENDING = "revise_pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXCEPTION_OPERATIONAL = "exception_operational"
    EXCEPTION_POLICY = "exception_policy"
    ARCHIVED = "archived"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class CreativeJobId:
    """Stable identifier for a creative job across all versions."""

    def __init__(self, value: str | None = None) -> None:
        self._value = value or f"job_{uuid4().hex[:12]}"

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def generate(cls) -> CreativeJobId:
        return cls()

    @classmethod
    def from_string(cls, value: str) -> CreativeJobId:
        return cls(value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CreativeJobId):
            return self._value == other._value
        return False

    def __hash__(self) -> int:
        return hash(self._value)

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"CreativeJobId({self._value!r})"


class VersionId:
    """Stable identifier for a specific asset version."""

    def __init__(self, job_id: CreativeJobId, version_number: int) -> None:
        if version_number < 1:
            raise ValueError("version_number must be >= 1")
        self._job_id = job_id
        self._version_number = version_number
        self._value = f"{job_id.value}_v{version_number}"

    @property
    def value(self) -> str:
        return self._value

    @property
    def job_id(self) -> CreativeJobId:
        return self._job_id

    @property
    def version_number(self) -> int:
        return self._version_number

    @classmethod
    def from_string(cls, value: str) -> VersionId:
        if "_v" not in value:
            raise ValueError(f"Invalid VersionId format: {value}")
        job_part, version_part = value.rsplit("_v", 1)
        job_id = CreativeJobId.from_string(job_part)
        version_number = int(version_part)
        return cls(job_id, version_number)

    def next_version(self) -> VersionId:
        return VersionId(self._job_id, self._version_number + 1)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VersionId):
            return self._value == other._value
        return False

    def __hash__(self) -> int:
        return hash(self._value)

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"VersionId({self._value!r})"


@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit trail entry.

    Uses timezone-aware UTC timestamps.
    """

    timestamp: datetime
    action: str
    actor: str
    details: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        action: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        return cls(
            timestamp=datetime.now(UTC),
            action=action,
            actor=actor,
            details=tuple((k, v) for k, v in (details or {}).items()),
        )


@dataclass(frozen=True)
class LineageEntry:
    """Immutable lineage relation between workflow artifacts.

    entry_type is one of: context, idea_selected, version, qa, approval.
    ref/parent_ref hold stable IDs (context_id, idea_id, version_id, job_id).
    """

    entry_type: str
    ref: str
    parent_ref: str | None = None
    details: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        entry_type: str,
        ref: str,
        parent_ref: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> LineageEntry:
        if not entry_type:
            raise ValueError("entry_type is required")
        if not ref:
            raise ValueError("ref is required")
        return cls(
            entry_type=entry_type,
            ref=ref,
            parent_ref=parent_ref,
            details=tuple((k, v) for k, v in (details or {}).items()),
        )


@dataclass(frozen=True)
class Cost:
    """Monetary cost with currency.

    Uses Decimal for precision. Never use float for money.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("Cost cannot be negative")
        if len(self.currency) != 3:
            raise ValueError("Currency must be 3-letter ISO code")

    @classmethod
    def from_float(cls, amount: float, currency: str) -> Cost:
        return cls(Decimal(str(amount)), currency)

    def __add__(self, other: Cost) -> Cost:
        if self.currency != other.currency:
            raise ValueError("Cannot add costs with different currencies")
        return Cost(self.amount + other.amount, self.currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


@dataclass(frozen=True)
class QASession:
    """QA check session submitted to checker.

    Contains all context needed for QA.
    """

    asset: AssetVersion
    input_contract: Any  # StaticCreativeInput - avoid circular import
    rubric_version: str
    policy_version: str


@dataclass(frozen=True)
class QACheckResult:
    """Structured QA result returned from checker.

    policy_violations route the job to EXCEPTION_POLICY instead of retry.
    """

    passed: bool
    score: Decimal
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    feedback: str | None = None
    policy_violations: tuple[str, ...] = ()
    outcome: ReviewOutcome | None = None
    retryable: bool = True
    requires_human_review: bool = False
    repair_actions: tuple[RepairAction, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reviewer_version: str | None = None
    criteria: tuple[CriterionReview, ...] = ()
    semantic_issues: tuple[SemanticIssue, ...] = ()
    evidence: tuple[ReviewEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.score < 0 or self.score > 100:
            raise ValueError("QA score must be between 0 and 100")
        if self.passed and (self.policy_violations or self.requires_human_review):
            raise ValueError("Passing QA cannot require policy or human intervention")
        if self.outcome == ReviewOutcome.PASS and not self.passed:
            raise ValueError("PASS outcome must have passed=True")


@dataclass(frozen=True)
class AssetVersion:
    """A single generation attempt (immutable).

    Each version is frozen and keeps its own:
    - Stable version ID and input lineage ref
    - Output artifact and cost
    - Version metadata (input hash, prompt/rubric/policy/workflow versions,
      generator version, seed)
    - QA result

    Use with_artifact/with_version_metadata/with_qa_result to derive new copies.
    """

    version_id: VersionId
    attempt_number: int
    input_ref: str
    artifact_url: str | None = None
    artifact_path: str | None = None
    cost: Cost | None = None
    input_hash: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None
    policy_version: str | None = None
    workflow_version: str | None = None
    generator_version: str | None = None
    seed: int | None = None
    qa_passed: bool | None = None
    qa_score: Decimal | None = None
    qa_issues: tuple[str, ...] = ()
    qa_warnings: tuple[str, ...] = ()
    qa_feedback: str | None = None
    qa_outcome: ReviewOutcome | None = None
    qa_retryable: bool = True
    qa_requires_human_review: bool = False
    qa_repair_actions: tuple[RepairAction, ...] = ()
    qa_evidence_refs: tuple[str, ...] = ()
    qa_reviewer_version: str | None = None
    qa_criteria: tuple[CriterionReview, ...] = ()
    qa_semantic_issues: tuple[SemanticIssue, ...] = ()
    qa_evidence: tuple[ReviewEvidence, ...] = ()
    creative_set_id: str | None = None
    variation_id: str | None = None
    variation_attempt_number: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_artifact(self, url: str, path: str, cost: Cost) -> AssetVersion:
        """Return new version with artifact attached."""
        return replace(self, artifact_url=url, artifact_path=path, cost=cost)

    def with_version_metadata(
        self,
        input_hash: str,
        prompt_version: str,
        rubric_version: str,
        policy_version: str,
        workflow_version: str,
    ) -> AssetVersion:
        """Return new version with provenance metadata attached."""
        return replace(
            self,
            input_hash=input_hash,
            prompt_version=prompt_version,
            rubric_version=rubric_version,
            policy_version=policy_version,
            workflow_version=workflow_version,
        )

    def with_qa_result(
        self,
        passed: bool,
        score: Decimal,
        issues: tuple[str, ...],
        feedback: str | None = None,
        warnings: tuple[str, ...] = (),
        outcome: ReviewOutcome | None = None,
        retryable: bool = True,
        requires_human_review: bool = False,
        repair_actions: tuple[RepairAction, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        reviewer_version: str | None = None,
        criteria: tuple[CriterionReview, ...] = (),
        semantic_issues: tuple[SemanticIssue, ...] = (),
        evidence: tuple[ReviewEvidence, ...] = (),
    ) -> AssetVersion:
        """Return new version with QA result attached."""
        return replace(
            self,
            qa_passed=passed,
            qa_score=score,
            qa_issues=issues,
            qa_warnings=warnings,
            qa_feedback=feedback,
            qa_outcome=outcome,
            qa_retryable=retryable,
            qa_requires_human_review=requires_human_review,
            qa_repair_actions=repair_actions,
            qa_evidence_refs=evidence_refs,
            qa_reviewer_version=reviewer_version,
            qa_criteria=criteria,
            qa_semantic_issues=semantic_issues,
            qa_evidence=evidence,
        )


@dataclass(frozen=True)
class ApprovalCard:
    """Human approval card containing every QA-passing set variation."""

    work_item_id: str
    candidate_summary: str
    final_version_ref: str
    final_version_refs: tuple[str, ...] = ()
    creative_set_id: str | None = None
    thumbnail_ref: str | None = None
    warnings: tuple[str, ...] = ()
    score: Decimal | None = None
    evidence_refs: tuple[str, ...] = ()
    decision: ApprovalDecision | None = None
    reviewer_id: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None

    def with_decision(
        self,
        decision: ApprovalDecision,
        reviewer_id: str,
        reason: str | None = None,
    ) -> ApprovalCard:
        """Return new card with the recorded decision."""
        return replace(
            self,
            decision=decision,
            reviewer_id=reviewer_id,
            reason=reason,
            decided_at=datetime.now(UTC),
        )


@dataclass
class CreativeJob:
    """The logical creative request with stable identity.

    Contains:
    - Stable job ID and idempotency key (source_run_id)
    - Current status and full version history
    - Lineage entries: work_item -> context -> idea -> version -> QA -> approval
    - Total cost across attempts, audit log, approval decision and card

    State changes MUST go through domain methods (approve, reject,
    transition_to) to ensure proper audit trail.
    """

    job_id: CreativeJobId
    status: CreativeJobStatus
    source_run_id: str | None = None
    context_ref: str | None = None
    idea_id: str | None = None
    versions: list[AssetVersion] = field(default_factory=list)
    total_cost: Cost | None = None
    audit_log: list[AuditEntry] = field(default_factory=list)
    lineage: list[LineageEntry] = field(default_factory=list)
    card: ApprovalCard | None = None
    approval_decision: ApprovalDecision | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    brief_ref: str | None = None
    preparation_hash: str | None = None
    creative_set_id: str | None = None

    @property
    def latest_version(self) -> AssetVersion | None:
        """Get the most recent version."""
        if not self.versions:
            return None
        return self.versions[-1]

    @property
    def retry_count(self) -> int:
        """Count of revision attempts (0 when no versions)."""
        if not self.versions:
            return 0
        if any(version.variation_id is not None for version in self.versions):
            return sum(max(version.variation_attempt_number - 1, 0) for version in self.versions)
        return len(self.versions) - 1

    @property
    def successful_version(self) -> AssetVersion | None:
        """Get the first QA-passing version."""
        for version in reversed(self.versions):
            if version.qa_passed is True:
                return version
        return None

    @property
    def successful_versions(self) -> tuple[AssetVersion, ...]:
        """Return the latest QA-passing version for each variation."""
        latest_by_variation: dict[str, AssetVersion] = {}
        for version in self.versions:
            key = version.variation_id or "default"
            latest_by_variation[key] = version
        return tuple(
            version for version in latest_by_variation.values() if version.qa_passed is True
        )

    def replace_version(self, version: AssetVersion) -> None:
        """Replace one immutable version after QA enriches it."""
        for index, current in enumerate(self.versions):
            if current.version_id == version.version_id:
                self.versions[index] = version
                return
        raise ValueError(f"Version not found: {version.version_id}")

    def add_audit(self, action: str, actor: str, details: dict[str, Any] | None = None) -> None:
        """Add immutable audit entry."""
        self.audit_log.append(AuditEntry.create(action, actor, details))

    def record_lineage(
        self,
        entry_type: str,
        ref: str,
        parent_ref: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append an immutable lineage entry."""
        self.lineage.append(LineageEntry.create(entry_type, ref, parent_ref, details))

    def attach_card(self, card: ApprovalCard) -> None:
        """Attach or replace the approval card."""
        self.card = card

    def add_version(self, version: AssetVersion) -> None:
        """Add a new version and accumulate cost."""
        self.versions.append(version)
        if version.cost:
            if self.total_cost:
                self.total_cost = self.total_cost + version.cost
            else:
                self.total_cost = version.cost

    def transition_to(self, new_status: CreativeJobStatus) -> None:
        """Transition to new status with validation."""
        valid_transitions = {
            CreativeJobStatus.PENDING: {
                CreativeJobStatus.VALIDATING,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.VALIDATING: {
                CreativeJobStatus.COLLECTING_CONTEXT,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.COLLECTING_CONTEXT: {
                CreativeJobStatus.IDEA_GENERATING,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.IDEA_GENERATING: {
                CreativeJobStatus.IDEA_REVIEW,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.IDEA_REVIEW: {
                CreativeJobStatus.GENERATING,
                CreativeJobStatus.BRIEF_READY,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.BRIEF_READY: {
                CreativeJobStatus.GENERATING,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.GENERATING: {
                CreativeJobStatus.QA_CHECKING,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.QA_CHECKING: {
                CreativeJobStatus.REVISE_PENDING,
                CreativeJobStatus.AWAITING_APPROVAL,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
                CreativeJobStatus.EXCEPTION_POLICY,
            },
            CreativeJobStatus.REVISE_PENDING: {
                CreativeJobStatus.GENERATING,
                CreativeJobStatus.EXCEPTION_OPERATIONAL,
            },
            CreativeJobStatus.AWAITING_APPROVAL: {
                CreativeJobStatus.APPROVED,
                CreativeJobStatus.REJECTED,
            },
            CreativeJobStatus.APPROVED: {CreativeJobStatus.ARCHIVED},
            CreativeJobStatus.REJECTED: {CreativeJobStatus.ARCHIVED},
            CreativeJobStatus.EXCEPTION_OPERATIONAL: set(),
            CreativeJobStatus.EXCEPTION_POLICY: set(),
            CreativeJobStatus.ARCHIVED: set(),
        }

        if new_status not in valid_transitions.get(self.status, set()):
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")

        self.status = new_status
        self.add_audit("status_change", "system", {"new_status": str(new_status)})

    def restart_preparation(self) -> None:
        """Restart an interrupted pre-generation preparation on the same job."""
        resumable_states = {
            CreativeJobStatus.PENDING,
            CreativeJobStatus.VALIDATING,
            CreativeJobStatus.COLLECTING_CONTEXT,
            CreativeJobStatus.IDEA_GENERATING,
            CreativeJobStatus.IDEA_REVIEW,
        }
        if self.status not in resumable_states:
            raise ValueError(f"Cannot restart preparation from {self.status}")
        if self.versions or self.card is not None or self.creative_set_id is not None:
            raise ValueError("Cannot restart preparation after Creative generation has started")

        previous_status = self.status
        preparation_entries = {
            "context",
            "idea_selected",
            "strategy",
            "composition",
            "brief",
        }
        self.lineage = [
            entry for entry in self.lineage if entry.entry_type not in preparation_entries
        ]
        self.context_ref = None
        self.idea_id = None
        self.brief_ref = None
        self.status = CreativeJobStatus.PENDING
        self.add_audit(
            "preparation_restarted",
            "system",
            {"previous_status": previous_status.value},
        )

    def approve(self, approver: str) -> None:
        """Mark as approved."""
        if self.status != CreativeJobStatus.AWAITING_APPROVAL:
            raise ValueError(f"Cannot approve job in {self.status} status")
        self.approval_decision = ApprovalDecision.APPROVE
        self.approved_by = approver
        self.approved_at = datetime.now(UTC)
        self.transition_to(CreativeJobStatus.APPROVED)

    def reject(self, reviewer: str, reason: str) -> None:
        """Mark as rejected."""
        if self.status != CreativeJobStatus.AWAITING_APPROVAL:
            raise ValueError(f"Cannot reject job in {self.status} status")
        self.approval_decision = ApprovalDecision.REJECT
        self.approved_by = reviewer
        self.approved_at = datetime.now(UTC)
        self.rejection_reason = reason
        self.transition_to(CreativeJobStatus.REJECTED)


__all__ = [
    "CreativeJobStatus",
    "ApprovalDecision",
    "CreativeJobId",
    "VersionId",
    "AuditEntry",
    "LineageEntry",
    "Cost",
    "QASession",
    "QACheckResult",
    "AssetVersion",
    "ApprovalCard",
    "CreativeJob",
]
