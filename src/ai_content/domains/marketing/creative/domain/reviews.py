"""Model-agnostic semantic review results for Creative assets."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class ReviewOutcome(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    REJECT = "reject"
    UNKNOWN = "unknown"


class CriterionStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RubricCriterion:
    """One executable criterion from a versioned review rubric."""

    criterion_id: str
    weight: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.criterion_id:
            raise ValueError("Rubric criterion requires an id")


@dataclass(frozen=True)
class ReviewRubric:
    """Minimal executable view of a Static Creative review rubric."""

    rubric_id: str
    version: str
    hard_gates: tuple[RubricCriterion, ...]
    scored_criteria: tuple[RubricCriterion, ...]
    set_gates: tuple[RubricCriterion, ...]
    approval_ready_score: Decimal
    revise_min_score: Decimal
    revise_max_score: Decimal
    reject_max_score: Decimal

    def __post_init__(self) -> None:
        criteria = (*self.hard_gates, *self.scored_criteria, *self.set_gates)
        criterion_ids = [item.criterion_id for item in criteria]
        if not self.rubric_id or not self.version:
            raise ValueError("Review rubric requires id and version")
        if not self.hard_gates or not self.scored_criteria:
            raise ValueError("Review rubric requires hard gates and scored criteria")
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("Review rubric criterion IDs must be unique")
        if any(item.weight is not None for item in (*self.hard_gates, *self.set_gates)):
            raise ValueError("Only scored rubric criteria may have weights")
        if any(item.weight is None or item.weight <= 0 for item in self.scored_criteria):
            raise ValueError("Scored rubric criteria require positive weights")
        if sum(item.weight or Decimal() for item in self.scored_criteria) != Decimal(100):
            raise ValueError("Scored rubric criterion weights must total 100")
        if not (
            Decimal()
            <= self.reject_max_score
            < self.revise_min_score
            <= self.revise_max_score
            < self.approval_ready_score
            <= Decimal(100)
        ):
            raise ValueError("Review rubric decision thresholds overlap or are out of range")

    @property
    def ref(self) -> str:
        return f"{self.rubric_id}@{self.version}"


@dataclass(frozen=True)
class RubricAssessment:
    """Deterministic recommendation derived from one complete rubric review."""

    outcome: ReviewOutcome
    weighted_score: Decimal | None
    hard_gates_passed: bool | None
    set_gates_passed: bool | None
    missing_criteria: tuple[str, ...] = ()


def assess_rubric_review(
    rubric: ReviewRubric,
    criteria: tuple[CriterionReview, ...],
    *,
    include_set_gates: bool = False,
) -> RubricAssessment:
    """Score a human review without allowing missing or UNKNOWN evidence to pass."""
    by_id = {item.criterion_id: item for item in criteria}
    if len(by_id) != len(criteria):
        raise ValueError("Review criterion IDs must be unique")
    allowed = {
        item.criterion_id
        for item in (*rubric.hard_gates, *rubric.scored_criteria, *rubric.set_gates)
    }
    unknown_ids = sorted(set(by_id) - allowed)
    if unknown_ids:
        raise ValueError(f"Review contains unknown rubric criteria: {', '.join(unknown_ids)}")

    required = [*rubric.hard_gates, *rubric.scored_criteria]
    if include_set_gates:
        required.extend(rubric.set_gates)
    missing = tuple(item.criterion_id for item in required if item.criterion_id not in by_id)
    if missing:
        return RubricAssessment(ReviewOutcome.UNKNOWN, None, None, None, missing)

    hard_reviews = [by_id[item.criterion_id] for item in rubric.hard_gates]
    set_reviews = (
        [by_id[item.criterion_id] for item in rubric.set_gates] if include_set_gates else []
    )
    if any(item.status == CriterionStatus.UNKNOWN for item in (*hard_reviews, *set_reviews)):
        return RubricAssessment(ReviewOutcome.UNKNOWN, None, None, None)

    scored_reviews = [by_id[item.criterion_id] for item in rubric.scored_criteria]
    if any(item.status == CriterionStatus.UNKNOWN or item.score is None for item in scored_reviews):
        return RubricAssessment(ReviewOutcome.UNKNOWN, None, None, None)

    score = sum(
        (by_id[item.criterion_id].score or Decimal()) / Decimal(4) * (item.weight or Decimal())
        for item in rubric.scored_criteria
    )
    hard_passed = all(item.status == CriterionStatus.PASS for item in hard_reviews)
    set_passed = (
        all(item.status == CriterionStatus.PASS for item in set_reviews)
        if include_set_gates
        else None
    )
    if not hard_passed or set_passed is False:
        outcome = ReviewOutcome.REVISE
    elif score >= rubric.approval_ready_score:
        outcome = ReviewOutcome.PASS
    elif rubric.revise_min_score <= score <= rubric.revise_max_score:
        outcome = ReviewOutcome.REVISE
    elif score <= rubric.reject_max_score:
        outcome = ReviewOutcome.REJECT
    else:
        outcome = ReviewOutcome.UNKNOWN
    return RubricAssessment(outcome, score, hard_passed, set_passed)


class IssueSeverity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class RepairAction(StrEnum):
    REGENERATE_FULL = "regenerate_full"
    REGENERATE_WITH_CONSTRAINTS = "regenerate_with_constraints"
    EDIT_REGION = "edit_region"
    MANUAL_REVIEW = "manual_review"
    REJECT_POLICY = "reject_policy"


@dataclass(frozen=True)
class ReviewEvidence:
    """Evidence supporting one semantic review conclusion."""

    evidence_id: str
    description: str
    source_ref: str
    region: tuple[Decimal, Decimal, Decimal, Decimal] | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.description or not self.source_ref:
            raise ValueError("Review evidence requires id, description and source_ref")
        if self.region is not None and (
            len(self.region) != 4 or any(value < 0 or value > 1 for value in self.region)
        ):
            raise ValueError(
                "Review evidence region must contain four normalized values from 0 to 1"
            )


@dataclass(frozen=True)
class CriterionReview:
    """One rubric criterion assessed by a semantic reviewer."""

    criterion_id: str
    status: CriterionStatus
    reason: str
    score: Decimal | None = None
    confidence: Decimal | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.criterion_id or not self.reason:
            raise ValueError("Criterion review requires criterion_id and reason")
        if self.score is not None and (self.score < 0 or self.score > 4):
            raise ValueError("Criterion score must be between 0 and 4")
        if self.confidence is not None and (self.confidence < 0 or self.confidence > 1):
            raise ValueError("Criterion confidence must be between 0 and 1")


@dataclass(frozen=True)
class SemanticIssue:
    """A stable issue code and the bounded action permitted to address it."""

    code: str
    criterion_id: str
    severity: IssueSeverity
    repair_action: RepairAction
    description: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.code or not self.criterion_id or not self.description:
            raise ValueError("Semantic issue requires code, criterion_id and description")


@dataclass(frozen=True)
class SemanticReviewResult:
    """Structured output returned by any future local or remote VLM adapter."""

    outcome: ReviewOutcome
    score: Decimal
    criteria: tuple[CriterionReview, ...]
    reviewer_version: str
    issues: tuple[SemanticIssue, ...] = ()
    evidence: tuple[ReviewEvidence, ...] = ()
    policy_violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    summary: str | None = None
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.score < 0 or self.score > 100:
            raise ValueError("Semantic review score must be between 0 and 100")
        if not self.criteria:
            raise ValueError("Semantic review requires at least one criterion")
        if not self.reviewer_version:
            raise ValueError("reviewer_version is required")
        if len({item.criterion_id for item in self.criteria}) != len(self.criteria):
            raise ValueError("Semantic review criterion_id values must be unique")
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("Semantic review evidence_id values must be unique")
        if len({item.code for item in self.issues}) != len(self.issues):
            raise ValueError("Semantic review issue codes must be unique")
        evidence_ids = {item.evidence_id for item in self.evidence}
        referenced = {ref for item in (*self.criteria, *self.issues) for ref in item.evidence_refs}
        if not referenced.issubset(evidence_ids):
            raise ValueError("Semantic review references unknown evidence")
        if self.outcome == ReviewOutcome.PASS and (
            self.issues
            or self.policy_violations
            or any(item.status != CriterionStatus.PASS for item in self.criteria)
        ):
            raise ValueError("PASS requires all criteria to pass without issues")
        if self.outcome == ReviewOutcome.REVISE and not self.issues:
            raise ValueError("REVISE requires at least one issue")
        if self.outcome == ReviewOutcome.REJECT and not (self.issues or self.policy_violations):
            raise ValueError("REJECT requires an issue or policy violation")


__all__ = [
    "CriterionReview",
    "CriterionStatus",
    "IssueSeverity",
    "RepairAction",
    "ReviewEvidence",
    "ReviewOutcome",
    "ReviewRubric",
    "RubricAssessment",
    "RubricCriterion",
    "SemanticIssue",
    "SemanticReviewResult",
    "assess_rubric_review",
]
