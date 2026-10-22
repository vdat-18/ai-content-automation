"""Business records for evidence-based Performance decisions."""

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


class SubjectType(StrEnum):
    PRODUCT = "product"
    CREATIVE = "creative"
    ANGLE = "angle"
    CONCEPT = "concept"


class MetricName(StrEnum):
    SPEND = "spend"
    REVENUE = "revenue"
    PURCHASES = "purchases"
    ATC = "atc"
    ROAS = "roas"
    COST_PER_ATC = "cost_per_atc"
    AOV = "aov"
    ACTIVE_DAYS = "active_days"
    CPC = "cpc"
    CPM = "cpm"
    CTR = "ctr"


class MetricStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class ComparisonOperator(StrEnum):
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"


class RuleMode(StrEnum):
    STRICT = "strict"
    RELAXED = "relaxed"


class RuleStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class CriterionOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class RuleOutcome(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class EvaluationState(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_EVIDENCE = "needs_evidence"
    BLOCKED_CONFLICT = "blocked_conflict"


class PerformanceClassification(StrEnum):
    PRODUCT_STRONG_CANDIDATE = "product_strong_candidate"
    PRODUCT_POTENTIAL_CANDIDATE = "product_potential_candidate"
    CREATIVE_WIN = "creative_win"
    CREATIVE_POTENTIAL = "creative_potential"
    ANGLE_WIN = "angle_win"
    CONCEPT_WIN = "concept_win"
    NOT_QUALIFIED = "not_qualified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class RecommendationAction(StrEnum):
    REQUEST_NEW_CREATIVE = "request_new_creative"
    RETEST_CREATIVE = "retest_creative"
    WAIT_FOR_MORE_DATA = "wait_for_more_data"
    NO_ACTION = "no_action"
    MANUAL_REVIEW = "manual_review"


class PerformanceDecision(StrEnum):
    APPROVE = "approve"
    EDIT_AND_APPROVE = "edit_and_approve"
    REJECT = "reject"
    DEFER = "defer"


class HandoffState(StrEnum):
    NOT_RELEASED = "not_released"
    PREVIEW_READY = "preview_ready"
    NOT_APPLICABLE = "not_applicable"


class OpportunityCategory(StrEnum):
    SCALE_WINNER = "scale_winner"
    REFRESH_FATIGUE = "refresh_fatigue"
    TEST_NEW_ANGLE = "test_new_angle"
    FILL_CREATIVE_GAP = "fill_creative_gap"
    INVESTIGATE_ANOMALY = "investigate_anomaly"
    DEFER_INSUFFICIENT_EVIDENCE = "defer_insufficient_evidence"
    STOP_OR_DEPRIORITIZE = "stop_or_deprioritize"
    BLOCKED_CONFLICT = "blocked_conflict"


@dataclass(frozen=True)
class PerformanceEvidenceMetric:
    name: MetricName
    window_id: str
    status: MetricStatus
    value: str | None
    unit: str
    source_ref: str | None


@dataclass(frozen=True)
class PerformanceEvidencePack:
    pack_id: str
    snapshot_id: str
    evaluation_id: str
    subject_id: str
    sku_id: str
    objective: str
    channel: str
    metrics: tuple[PerformanceEvidenceMetric, ...]
    rule_assessments: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    data_quality_state: EvaluationState
    version: str


@dataclass(frozen=True)
class ExperimentProposal:
    proposal_id: str
    version_number: int
    sku_id: str
    priority: int
    category: OpportunityCategory
    hypothesis: str
    experiment: str
    success_signal: str
    evidence_refs: tuple[str, ...]
    uncertainty: str

    def __post_init__(self) -> None:
        _identifier(self.proposal_id, "proposal_id")
        _identifier(self.sku_id, "sku_id")
        if self.version_number < 1:
            raise ValueError("Experiment proposal version must be positive")
        if not 1 <= self.priority <= 5:
            raise ValueError("Experiment proposal priority must be between 1 and 5")


@dataclass(frozen=True)
class CreativeOpportunityAnalysis:
    analysis_id: str
    evidence_pack_id: str
    category: OpportunityCategory
    priority: int
    rationale: str
    evidence_refs: tuple[str, ...]
    uncertainty: str
    counterargument: str
    proposal: ExperimentProposal
    prompt_version: str
    model: str
    rubric_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.analysis_id, "analysis_id")
        _identifier(self.evidence_pack_id, "evidence_pack_id")
        if not 1 <= self.priority <= 5:
            raise ValueError("Opportunity priority must be between 1 and 5")
        _aware(self.created_at, "created_at")


@dataclass(frozen=True)
class PerformanceSubject:
    subject_type: SubjectType
    subject_id: str
    brand_id: str
    store_id: str
    sku_id: str
    platform: str
    creative_id: str | None = None
    angle_id: str | None = None
    concept_id: str | None = None
    persona_id: str | None = None
    raw_source_name: str | None = None

    def __post_init__(self) -> None:
        for name in ("subject_id", "brand_id", "store_id", "sku_id"):
            _identifier(getattr(self, name), name)
        for name in ("creative_id", "angle_id", "concept_id", "persona_id"):
            value = getattr(self, name)
            if value is not None:
                _identifier(value, name)
        if not self.platform.strip():
            raise ValueError("platform is required")


@dataclass(frozen=True)
class MetricObservation:
    name: MetricName
    window_id: str
    status: MetricStatus
    value: Decimal | None
    unit: str
    source_ref: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.window_id, "window_id")
        _aware(self.observed_at, "observed_at")
        if not self.unit.strip():
            raise ValueError("Metric unit is required")
        if self.status == MetricStatus.KNOWN and (self.value is None or not self.source_ref):
            raise ValueError("Known metric requires value and source_ref")
        if self.status == MetricStatus.KNOWN and self.value is not None and self.value < 0:
            raise ValueError("Known metric value cannot be negative")
        if (
            self.status in {MetricStatus.UNKNOWN, MetricStatus.NOT_APPLICABLE}
            and self.value is not None
        ):
            raise ValueError("Unknown or not-applicable metric cannot carry a value")
        if self.status == MetricStatus.CONFLICT and not self.source_ref:
            raise ValueError("Conflicting metric requires source_ref")


@dataclass(frozen=True)
class PerformanceSnapshot:
    snapshot_id: str
    subject: PerformanceSubject
    objective: str
    channel: str
    timezone: str
    attribution: str
    currency: str
    source_version: str
    metrics: tuple[MetricObservation, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        _aware(self.observed_at, "observed_at")
        if not all(
            value.strip()
            for value in (
                self.objective,
                self.channel,
                self.timezone,
                self.attribution,
                self.source_version,
            )
        ):
            raise ValueError("Snapshot scope and provenance are required")
        if len(self.currency) != 3:
            raise ValueError("currency must be a 3-letter code")
        keys = [(metric.name, metric.window_id) for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("Metric name/window pairs must be unique")
        money_metrics = {
            MetricName.SPEND,
            MetricName.REVENUE,
            MetricName.COST_PER_ATC,
            MetricName.AOV,
            MetricName.CPC,
            MetricName.CPM,
        }
        if any(
            metric.name in money_metrics
            and metric.status == MetricStatus.KNOWN
            and metric.unit != self.currency
            for metric in self.metrics
        ):
            raise ValueError("Monetary metric units must match snapshot currency")


@dataclass(frozen=True)
class RuleCriterion:
    criterion_id: str
    metric: MetricName
    window_id: str
    operator: ComparisonOperator
    threshold: Decimal

    def __post_init__(self) -> None:
        _identifier(self.criterion_id, "criterion_id")
        _identifier(self.window_id, "window_id")


@dataclass(frozen=True)
class ClassificationRule:
    rule_id: str
    subject_type: SubjectType
    classification: PerformanceClassification
    recommendation: RecommendationAction
    criteria: tuple[RuleCriterion, ...]
    required_passes: int

    def __post_init__(self) -> None:
        _identifier(self.rule_id, "rule_id")
        if not self.criteria:
            raise ValueError("Classification rule requires criteria")
        if not 1 <= self.required_passes <= len(self.criteria):
            raise ValueError("required_passes must fit the criterion count")


@dataclass(frozen=True)
class PerformanceRuleSet:
    rule_set_id: str
    version: str
    status: RuleStatus
    mode: RuleMode
    effective_at: datetime
    rules: tuple[ClassificationRule, ...]

    def __post_init__(self) -> None:
        _identifier(self.rule_set_id, "rule_set_id")
        _aware(self.effective_at, "effective_at")
        if not self.version.strip() or not self.rules:
            raise ValueError("Rule set version and rules are required")
        identifiers = [rule.rule_id for rule in self.rules]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Rule IDs must be unique")
        for rule in self.rules:
            if self.mode == RuleMode.STRICT and rule.required_passes != len(rule.criteria):
                raise ValueError("Strict rule sets require every criterion to pass")
            if (
                rule.required_passes != len(rule.criteria)
                and rule.subject_type != SubjectType.CREATIVE
            ):
                raise ValueError("Only Creative rules may use a relaxed pass count")


@dataclass(frozen=True)
class CriterionAssessment:
    criterion_id: str
    metric: MetricName
    window_id: str
    outcome: CriterionOutcome
    observed_value: Decimal | None
    operator: ComparisonOperator
    threshold: Decimal
    source_ref: str | None
    detail: str


@dataclass(frozen=True)
class RuleAssessment:
    rule_id: str
    classification: PerformanceClassification
    outcome: RuleOutcome
    passed_criteria: int
    required_passes: int
    criteria: tuple[CriterionAssessment, ...]


@dataclass(frozen=True)
class PerformanceEvaluation:
    evaluation_id: str
    version_number: int
    state: EvaluationState
    classification: PerformanceClassification
    recommendation: RecommendationAction
    rule_set_id: str
    rule_version: str
    rule_mode: RuleMode
    rule_status: RuleStatus
    assessments: tuple[RuleAssessment, ...]
    evidence_refs: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.evaluation_id, "evaluation_id")
        _aware(self.created_at, "created_at")
        if self.version_number < 1:
            raise ValueError("version_number must be positive")


@dataclass(frozen=True)
class CreativeDemandPreview:
    preview_id: str
    state: HandoffState
    source_decision_run_id: str
    source_evaluation_id: str
    brand_id: str
    sku_id: str
    objective: str
    channel: str
    action: RecommendationAction
    classification: PerformanceClassification
    evidence_refs: tuple[str, ...]
    missing_context: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "preview_id",
            "source_decision_run_id",
            "source_evaluation_id",
            "brand_id",
            "sku_id",
        ):
            _identifier(getattr(self, name), name)


@dataclass(frozen=True)
class PerformanceDecisionRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    snapshot: PerformanceSnapshot
    evaluation: PerformanceEvaluation
    created_at: datetime
    decision: PerformanceDecision | None = None
    decision_evaluation_id: str | None = None
    reviewer_alias: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    creative_demand_preview: CreativeDemandPreview | None = None
    evidence_pack: PerformanceEvidencePack | None = None
    opportunity_analysis: CreativeOpportunityAnalysis | None = None
    decision_proposal_id: str | None = None
    approved_proposal: ExperimentProposal | None = None
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("run_id", "source_run_id"):
            _identifier(getattr(self, name), name)
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        _aware(self.created_at, "created_at")
        preview = self.creative_demand_preview
        if preview is not None and (
            preview.source_decision_run_id != self.run_id
            or preview.source_evaluation_id != self.evaluation.evaluation_id
            or preview.brand_id != self.snapshot.subject.brand_id
            or preview.sku_id != self.snapshot.subject.sku_id
        ):
            raise ValueError("Creative demand preview must match its decision run")

    def decide(
        self,
        decision: PerformanceDecision,
        evaluation_id: str,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
        proposal_id: str | None = None,
        edited_proposal: ExperimentProposal | None = None,
    ) -> PerformanceDecisionRun:
        _aware(decided_at, "decided_at")
        if self.decision is not None:
            raise ValueError("Performance decision has already been recorded")
        if evaluation_id != self.evaluation.evaluation_id:
            raise ValueError("Decision must pin the current evaluation version")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and decision reason are required")
        approval_decisions = {
            PerformanceDecision.APPROVE,
            PerformanceDecision.EDIT_AND_APPROVE,
        }
        if (
            decision in approval_decisions
            and self.evaluation.state != EvaluationState.READY_FOR_REVIEW
        ):
            raise ValueError("Incomplete or conflicting evidence blocks approval")
        analysis = self.opportunity_analysis
        selected_proposal = edited_proposal or (analysis.proposal if analysis is not None else None)
        if decision == PerformanceDecision.EDIT_AND_APPROVE and analysis is None:
            raise ValueError("Edit-and-approve requires a current Experiment proposal")
        if decision != PerformanceDecision.EDIT_AND_APPROVE and edited_proposal is not None:
            raise ValueError("Edited Experiment proposal requires edit-and-approve")
        if decision not in approval_decisions and proposal_id is not None:
            raise ValueError("Only approval decisions may pin an Experiment proposal")
        if analysis is not None and decision in approval_decisions:
            if proposal_id != analysis.proposal.proposal_id:
                raise ValueError("Decision must pin the current Experiment proposal")
            if decision == PerformanceDecision.EDIT_AND_APPROVE and edited_proposal is None:
                raise ValueError("Edit-and-approve requires an edited Experiment proposal")
            if edited_proposal is not None and edited_proposal.proposal_id != proposal_id:
                raise ValueError("Edited Experiment proposal must preserve proposal identity")
            if (
                edited_proposal is not None
                and edited_proposal.version_number <= analysis.proposal.version_number
            ):
                raise ValueError("Edited Experiment proposal must create a newer version")
            if (
                edited_proposal is not None
                and edited_proposal.sku_id != self.snapshot.subject.sku_id
            ):
                raise ValueError("Edited Experiment proposal must preserve SKU identity")
            if (
                edited_proposal is not None
                and self.evidence_pack is not None
                and not set(edited_proposal.evidence_refs).issubset(
                    self.evidence_pack.evidence_refs
                )
            ):
                raise ValueError("Edited Experiment proposal contains unknown evidence")
        preview = self.creative_demand_preview
        if decision in approval_decisions and self.evaluation.recommendation in {
            RecommendationAction.REQUEST_NEW_CREATIVE,
            RecommendationAction.RETEST_CREATIVE,
        }:
            if preview is None:
                raise ValueError("Actionable recommendation requires a Creative demand preview")
            preview = replace(preview, state=HandoffState.PREVIEW_READY)
        return replace(
            self,
            decision=decision,
            decision_evaluation_id=evaluation_id,
            reviewer_alias=reviewer_alias,
            decision_reason=reason,
            decided_at=decided_at,
            creative_demand_preview=preview,
            decision_proposal_id=proposal_id,
            approved_proposal=selected_proposal if decision in approval_decisions else None,
            audit_log=(*self.audit_log, f"decision:{decision.value}:{evaluation_id}"),
        )


__all__ = [
    "ClassificationRule",
    "ComparisonOperator",
    "CreativeDemandPreview",
    "CriterionAssessment",
    "CriterionOutcome",
    "EvaluationState",
    "HandoffState",
    "MetricName",
    "MetricObservation",
    "MetricStatus",
    "CreativeOpportunityAnalysis",
    "ExperimentProposal",
    "OpportunityCategory",
    "PerformanceEvidencePack",
    "PerformanceEvidenceMetric",
    "PerformanceClassification",
    "PerformanceDecision",
    "PerformanceDecisionRun",
    "PerformanceEvaluation",
    "PerformanceRuleSet",
    "PerformanceSnapshot",
    "PerformanceSubject",
    "RecommendationAction",
    "RuleAssessment",
    "RuleCriterion",
    "RuleMode",
    "RuleOutcome",
    "RuleStatus",
    "SubjectType",
]
