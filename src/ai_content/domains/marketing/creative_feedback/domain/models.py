"""Evidence-backed records for the Creative performance feedback loop."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _identifier(value: str, name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _optional_identifier(value: str | None, name: str) -> None:
    if value is not None:
        _identifier(value, name)


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


class EvidenceStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class EvaluationState(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_EVIDENCE = "needs_evidence"
    BLOCKED_CONFLICT = "blocked_conflict"


class PerformanceClassification(StrEnum):
    CREATIVE_WIN = "creative_win"
    CREATIVE_POTENTIAL = "creative_potential"
    NOT_QUALIFIED = "not_qualified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class RecommendationAction(StrEnum):
    REQUEST_NEW_CREATIVE = "request_new_creative"
    RETEST_CREATIVE = "retest_creative"
    WAIT_FOR_MORE_DATA = "wait_for_more_data"
    NO_ACTION = "no_action"
    MANUAL_REVIEW = "manual_review"


class CriterionOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class FeedbackRunState(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    OBSERVATION_ONLY = "observation_only"
    NEEDS_EVIDENCE = "needs_evidence"
    BLOCKED_CONFLICT = "blocked_conflict"


class LessonOutcome(StrEnum):
    REUSE_SIGNAL = "reuse_signal"
    TEST_SIGNAL = "test_signal"
    NO_ACTION_SIGNAL = "no_action_signal"


class TaskPreviewState(StrEnum):
    NOT_RELEASED = "not_released"
    PREVIEW_READY = "preview_ready"


class FeedbackDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(frozen=True)
class AdsEvidencePack:
    pack_id: str
    evaluation_id: str
    creative_id: str
    creative_version_id: str
    brand_id: str
    sku_id: str
    platform: str
    window_id: str
    attribution: str
    classification: PerformanceClassification
    recommendation: RecommendationAction
    criteria: tuple[PerformanceCriterionFact, ...]
    human_feedback: HumanFeedbackObservation | None
    evidence_refs: tuple[str, ...]
    version: str

    def __post_init__(self) -> None:
        for name in (
            "pack_id",
            "evaluation_id",
            "creative_id",
            "creative_version_id",
            "brand_id",
            "sku_id",
        ):
            _identifier(getattr(self, name), name)
        if not all(value.strip() for value in (self.platform, self.window_id, self.attribution)):
            raise ValueError("Ads evidence scope is required")
        if not self.criteria or not self.evidence_refs or not self.version.strip():
            raise ValueError("Ads evidence requires criteria, references and a version")


@dataclass(frozen=True)
class AdsDiagnosis:
    observations: tuple[str, ...]
    hypotheses: tuple[str, ...]
    confounders: tuple[str, ...]
    uncertainty: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.observations or not self.hypotheses or not self.confounders:
            raise ValueError("Ads diagnosis must separate observations, hypotheses and confounders")
        if not self.uncertainty.strip() or not self.evidence_refs:
            raise ValueError("Ads diagnosis requires uncertainty and evidence")


@dataclass(frozen=True)
class LearningProposal:
    proposal_id: str
    version_number: int
    creative_version_id: str
    sku_id: str
    priority: int
    recommended_action: RecommendationAction
    hypothesis: str
    experiment: str
    success_signal: str
    evidence_refs: tuple[str, ...]
    uncertainty: str

    def __post_init__(self) -> None:
        for name in ("proposal_id", "creative_version_id", "sku_id"):
            _identifier(getattr(self, name), name)
        if self.version_number < 1:
            raise ValueError("Learning proposal version must be positive")
        if not 1 <= self.priority <= 5:
            raise ValueError("Learning proposal priority must be between 1 and 5")
        if not all(
            value.strip()
            for value in (self.hypothesis, self.experiment, self.success_signal, self.uncertainty)
        ):
            raise ValueError("Learning proposal fields are required")
        if not self.evidence_refs:
            raise ValueError("Learning proposal requires evidence")


@dataclass(frozen=True)
class PerformanceLearningAnalysis:
    analysis_id: str
    evidence_pack_id: str
    creative_version_id: str
    sku_id: str
    diagnosis: AdsDiagnosis
    proposal: LearningProposal | None
    prompt_version: str
    model: str
    rubric_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("analysis_id", "evidence_pack_id", "creative_version_id", "sku_id"):
            _identifier(getattr(self, name), name)
        if not all(
            value.strip() for value in (self.prompt_version, self.model, self.rubric_version)
        ):
            raise ValueError("Learning analysis provenance is required")
        _aware(self.created_at, "created_at")


@dataclass(frozen=True)
class CreativeReleaseSnapshot:
    release_id: str
    creative_job_id: str
    creative_id: str
    creative_version_id: str
    current_version_id: str
    brand_id: str
    sku_id: str
    idea_id: str
    approval_ref: str
    approved_at: datetime
    persona_id: str | None = None
    angle_id: str | None = None
    hook_id: str | None = None
    concept_id: str | None = None
    creative_set_id: str | None = None
    variation_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "release_id",
            "creative_job_id",
            "creative_id",
            "creative_version_id",
            "current_version_id",
            "brand_id",
            "sku_id",
            "idea_id",
        ):
            _identifier(getattr(self, name), name)
        for name in (
            "persona_id",
            "angle_id",
            "hook_id",
            "concept_id",
            "creative_set_id",
            "variation_id",
        ):
            _optional_identifier(getattr(self, name), name)
        if not self.approval_ref.strip():
            raise ValueError("approval_ref is required")
        _aware(self.approved_at, "approved_at")


@dataclass(frozen=True)
class AdPlacementMapping:
    mapping_id: str
    status: EvidenceStatus
    platform: str
    account_id: str
    evidence_ref: str | None
    observed_at: datetime
    mapped_version_id: str | None = None
    candidate_version_ids: tuple[str, ...] = ()
    campaign_id: str | None = None
    adset_id: str | None = None
    ad_id: str | None = None
    raw_creative_name: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.mapping_id, "mapping_id")
        _identifier(self.account_id, "account_id")
        for name in ("mapped_version_id", "campaign_id", "adset_id", "ad_id"):
            _optional_identifier(getattr(self, name), name)
        for value in self.candidate_version_ids:
            _identifier(value, "candidate_version_id")
        if not self.platform.strip():
            raise ValueError("platform is required")
        _aware(self.observed_at, "observed_at")
        if self.status == EvidenceStatus.KNOWN and (
            self.mapped_version_id is None or self.evidence_ref is None or self.ad_id is None
        ):
            raise ValueError("Known Ad mapping requires version, ad_id and evidence")
        if self.status == EvidenceStatus.UNKNOWN and (
            self.mapped_version_id is not None or self.candidate_version_ids
        ):
            raise ValueError("Unknown Ad mapping cannot select candidate versions")
        if self.status == EvidenceStatus.CONFLICT and (
            len(set(self.candidate_version_ids)) < 2 or self.evidence_ref is None
        ):
            raise ValueError("Conflicting Ad mapping requires at least two candidates and evidence")


@dataclass(frozen=True)
class PerformanceCriterionFact:
    criterion_id: str
    metric: str
    window_id: str
    outcome: CriterionOutcome
    observed_value: str | None
    operator: str
    threshold: str
    detail: str
    source_ref: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.criterion_id, "criterion_id")
        _identifier(self.window_id, "window_id")
        if not all(
            value.strip() for value in (self.metric, self.operator, self.threshold, self.detail)
        ):
            raise ValueError("criterion metric, operator, threshold and detail are required")


@dataclass(frozen=True)
class PerformanceOutcomeSnapshot:
    performance_run_id: str
    evaluation_id: str
    state: EvaluationState
    classification: PerformanceClassification
    recommendation: RecommendationAction
    subject_creative_id: str
    brand_id: str
    sku_id: str
    platform: str
    grain: str
    window_id: str
    timezone: str
    attribution: str
    rule_set_id: str
    rule_version: str
    rule_mode: str
    rule_status: str
    criteria: tuple[PerformanceCriterionFact, ...]
    evidence_refs: tuple[str, ...]
    observed_at: datetime
    subject_version_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "performance_run_id",
            "evaluation_id",
            "subject_creative_id",
            "brand_id",
            "sku_id",
            "window_id",
            "rule_set_id",
        ):
            _identifier(getattr(self, name), name)
        _optional_identifier(self.subject_version_id, "subject_version_id")
        if not all(
            value.strip()
            for value in (
                self.platform,
                self.grain,
                self.timezone,
                self.attribution,
                self.rule_version,
                self.rule_mode,
                self.rule_status,
            )
        ):
            raise ValueError("Performance scope and rule provenance are required")
        if self.grain != "creative":
            raise ValueError("Creative feedback requires creative-grain Performance evidence")
        if not self.criteria:
            raise ValueError("Performance outcome requires criterion facts")
        criterion_ids = [item.criterion_id for item in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Performance criterion IDs must be unique")
        _aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class HumanFeedbackObservation:
    feedback_id: str
    status: EvidenceStatus
    creative_version_id: str | None
    decision: str | None
    issue_codes: tuple[str, ...]
    summary: str | None
    source_ref: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.feedback_id, "feedback_id")
        _optional_identifier(self.creative_version_id, "creative_version_id")
        _aware(self.observed_at, "observed_at")
        if self.status == EvidenceStatus.KNOWN and (
            self.creative_version_id is None or self.source_ref is None
        ):
            raise ValueError("Known human feedback requires an exact version and source")
        if self.status == EvidenceStatus.CONFLICT and self.source_ref is None:
            raise ValueError("Conflicting human feedback requires evidence")
        if self.status == EvidenceStatus.UNKNOWN and any(
            (self.creative_version_id, self.decision, self.issue_codes, self.summary)
        ):
            raise ValueError("Unknown human feedback cannot carry inferred content")
        for code in self.issue_codes:
            _identifier(code, "human_feedback_issue_code")


@dataclass(frozen=True)
class FeedbackLesson:
    lesson_id: str
    version_number: int
    creative_version_id: str
    outcome: LessonOutcome
    summary: str
    supported_facts: tuple[str, ...]
    non_conclusions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    performance_evaluation_id: str
    rule_set_id: str
    rule_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "lesson_id",
            "creative_version_id",
            "performance_evaluation_id",
            "rule_set_id",
        ):
            _identifier(getattr(self, name), name)
        if self.version_number < 1:
            raise ValueError("lesson version_number must be positive")
        if not self.summary.strip() or not self.supported_facts or not self.non_conclusions:
            raise ValueError("Lesson requires a summary, supported facts and limits")
        _aware(self.created_at, "created_at")


@dataclass(frozen=True)
class NextCreativeTaskPreview:
    preview_id: str
    state: TaskPreviewState
    action: RecommendationAction
    source_lesson_id: str
    source_evaluation_id: str
    source_creative_version_id: str
    brand_id: str
    sku_id: str
    reusable_context_refs: tuple[str, ...]
    missing_context: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "preview_id",
            "source_lesson_id",
            "source_evaluation_id",
            "source_creative_version_id",
            "brand_id",
            "sku_id",
        ):
            _identifier(getattr(self, name), name)
        if self.action not in {
            RecommendationAction.REQUEST_NEW_CREATIVE,
            RecommendationAction.RETEST_CREATIVE,
        }:
            raise ValueError("Task preview requires an actionable recommendation")
        if not self.missing_context:
            raise ValueError("Task preview must expose context still required by M1")


@dataclass(frozen=True)
class CreativeFeedbackRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    release: CreativeReleaseSnapshot
    ad_mapping: AdPlacementMapping
    performance: PerformanceOutcomeSnapshot
    human_feedback: HumanFeedbackObservation | None
    state: FeedbackRunState
    lesson: FeedbackLesson | None
    next_task_preview: NextCreativeTaskPreview | None
    warnings: tuple[str, ...]
    created_at: datetime
    ads_evidence_pack: AdsEvidencePack | None = None
    learning_analysis: PerformanceLearningAnalysis | None = None
    decision: FeedbackDecision | None = None
    decision_lesson_id: str | None = None
    decision_learning_proposal_id: str | None = None
    approved_learning_proposal: LearningProposal | None = None
    reviewer_alias: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("run_id", "source_run_id"):
            _identifier(getattr(self, name), name)
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        _aware(self.created_at, "created_at")
        if self.state in {FeedbackRunState.READY_FOR_REVIEW, FeedbackRunState.OBSERVATION_ONLY}:
            if self.lesson is None:
                raise ValueError("Evidence-ready feedback run requires a lesson")
        elif self.lesson is not None or self.next_task_preview is not None:
            raise ValueError("Blocked feedback run cannot create a lesson or task preview")
        if self.state == FeedbackRunState.READY_FOR_REVIEW and self.next_task_preview is None:
            raise ValueError("Review-ready feedback run requires a task preview")
        if self.state == FeedbackRunState.OBSERVATION_ONLY and self.next_task_preview is not None:
            raise ValueError("Observation-only feedback run cannot release a task")
        if self.learning_analysis is not None and self.ads_evidence_pack is None:
            raise ValueError("Learning analysis requires its persisted Ads evidence pack")
        if self.decision is None:
            if any(
                (
                    self.decision_lesson_id,
                    self.decision_learning_proposal_id,
                    self.approved_learning_proposal,
                    self.reviewer_alias,
                    self.decision_reason,
                    self.decided_at,
                )
            ):
                raise ValueError("Undecided feedback run cannot carry decision metadata")
            if (
                self.next_task_preview is not None
                and self.next_task_preview.state == TaskPreviewState.PREVIEW_READY
            ):
                raise ValueError("An undecided task preview cannot be released")
        else:
            if not all(
                (
                    self.decision_lesson_id,
                    self.reviewer_alias,
                    self.decision_reason,
                    self.decided_at,
                )
            ):
                raise ValueError("Decision metadata must be complete")
            if self.decision == FeedbackDecision.APPROVE and (
                self.next_task_preview is None
                or self.next_task_preview.state != TaskPreviewState.PREVIEW_READY
            ):
                raise ValueError("Approved feedback must release its pinned task preview")
            proposal = self.learning_analysis.proposal if self.learning_analysis else None
            if self.decision == FeedbackDecision.APPROVE and proposal is not None:
                if (
                    self.decision_learning_proposal_id != proposal.proposal_id
                    or self.approved_learning_proposal != proposal
                ):
                    raise ValueError("Approved feedback must pin the current Learning proposal")
            elif self.decision_learning_proposal_id or self.approved_learning_proposal:
                raise ValueError("Only approval may persist a Learning proposal")
            if self.decision != FeedbackDecision.APPROVE and (
                self.next_task_preview is not None
                and self.next_task_preview.state != TaskPreviewState.NOT_RELEASED
            ):
                raise ValueError("Rejected or deferred feedback cannot release a task preview")

    def decide(
        self,
        decision: FeedbackDecision,
        lesson_id: str,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
        learning_proposal_id: str | None = None,
    ) -> CreativeFeedbackRun:
        _aware(decided_at, "decided_at")
        if self.decision is not None:
            raise ValueError("Creative feedback decision has already been recorded")
        if self.state != FeedbackRunState.READY_FOR_REVIEW or self.lesson is None:
            raise ValueError("Only an actionable evidence-ready lesson can be decided")
        if lesson_id != self.lesson.lesson_id:
            raise ValueError("Decision must pin the current lesson version")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and decision reason are required")
        preview = self.next_task_preview
        if preview is None:
            raise ValueError("Actionable feedback requires a next-task preview")
        if decision == FeedbackDecision.APPROVE:
            preview = replace(preview, state=TaskPreviewState.PREVIEW_READY)
        proposal = self.learning_analysis.proposal if self.learning_analysis else None
        if decision == FeedbackDecision.APPROVE and proposal is not None:
            if learning_proposal_id != proposal.proposal_id:
                raise ValueError("Decision must pin the current Learning proposal")
        elif learning_proposal_id is not None:
            raise ValueError("Only approval may pin a Learning proposal")
        return replace(
            self,
            decision=decision,
            decision_lesson_id=lesson_id,
            decision_learning_proposal_id=learning_proposal_id,
            approved_learning_proposal=(proposal if decision == FeedbackDecision.APPROVE else None),
            reviewer_alias=reviewer_alias,
            decision_reason=reason,
            decided_at=decided_at,
            next_task_preview=preview,
            audit_log=(*self.audit_log, f"decision:{decision.value}:{lesson_id}"),
        )


__all__ = [
    "AdPlacementMapping",
    "AdsDiagnosis",
    "AdsEvidencePack",
    "CreativeFeedbackRun",
    "CreativeReleaseSnapshot",
    "CriterionOutcome",
    "EvaluationState",
    "EvidenceStatus",
    "FeedbackDecision",
    "FeedbackLesson",
    "FeedbackRunState",
    "HumanFeedbackObservation",
    "LessonOutcome",
    "LearningProposal",
    "NextCreativeTaskPreview",
    "PerformanceClassification",
    "PerformanceCriterionFact",
    "PerformanceOutcomeSnapshot",
    "PerformanceLearningAnalysis",
    "RecommendationAction",
    "TaskPreviewState",
]
