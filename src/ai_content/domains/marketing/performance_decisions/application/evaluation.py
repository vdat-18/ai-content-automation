"""Deterministic Performance rule evaluation and decision-card creation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from ..domain.models import (
    ClassificationRule,
    ComparisonOperator,
    CreativeDemandPreview,
    CriterionAssessment,
    CriterionOutcome,
    EvaluationState,
    HandoffState,
    MetricObservation,
    MetricStatus,
    OpportunityCategory,
    PerformanceClassification,
    PerformanceDecisionRun,
    PerformanceEvaluation,
    PerformanceEvidenceMetric,
    PerformanceEvidencePack,
    PerformanceRuleSet,
    PerformanceSnapshot,
    RecommendationAction,
    RuleAssessment,
    RuleOutcome,
)
from ..ports.interfaces import (
    ICreativeOpportunityAnalyzer,
    IPerformanceDecisionRepository,
    OpportunityAnalysisError,
    PerformanceInputDriftError,
)

_CLASSIFICATION_PRIORITY = {
    PerformanceClassification.PRODUCT_STRONG_CANDIDATE: 20,
    PerformanceClassification.PRODUCT_POTENTIAL_CANDIDATE: 10,
    PerformanceClassification.CREATIVE_WIN: 20,
    PerformanceClassification.CREATIVE_POTENTIAL: 10,
    PerformanceClassification.ANGLE_WIN: 10,
    PerformanceClassification.CONCEPT_WIN: 10,
}


@dataclass(frozen=True)
class PerformanceDecisionRequest:
    source_run_id: str
    source_checksum_sha256: str
    snapshot: PerformanceSnapshot
    rule_set: PerformanceRuleSet


@dataclass(frozen=True)
class PerformanceDecisionResult:
    run: PerformanceDecisionRun
    duplicate: bool


def _compare(value: Decimal, operator: ComparisonOperator, threshold: Decimal) -> bool:
    if operator == ComparisonOperator.GREATER_THAN:
        return value > threshold
    if operator == ComparisonOperator.GREATER_THAN_OR_EQUAL:
        return value >= threshold
    if operator == ComparisonOperator.LESS_THAN:
        return value < threshold
    return value <= threshold


def _criterion(
    rule_criterion, metrics: dict[tuple[object, str], MetricObservation]
) -> CriterionAssessment:
    metric = metrics.get((rule_criterion.metric, rule_criterion.window_id))
    if metric is None or metric.status == MetricStatus.UNKNOWN:
        return CriterionAssessment(
            rule_criterion.criterion_id,
            rule_criterion.metric,
            rule_criterion.window_id,
            CriterionOutcome.UNKNOWN,
            None,
            rule_criterion.operator,
            rule_criterion.threshold,
            metric.source_ref if metric else None,
            "Required metric is unavailable.",
        )
    if metric.status == MetricStatus.CONFLICT:
        return CriterionAssessment(
            rule_criterion.criterion_id,
            rule_criterion.metric,
            rule_criterion.window_id,
            CriterionOutcome.CONFLICT,
            metric.value,
            rule_criterion.operator,
            rule_criterion.threshold,
            metric.source_ref,
            "Metric sources conflict.",
        )
    if metric.status == MetricStatus.NOT_APPLICABLE:
        return CriterionAssessment(
            rule_criterion.criterion_id,
            rule_criterion.metric,
            rule_criterion.window_id,
            CriterionOutcome.NOT_APPLICABLE,
            None,
            rule_criterion.operator,
            rule_criterion.threshold,
            metric.source_ref,
            "Metric is not applicable to this snapshot.",
        )
    assert metric.value is not None
    passed = _compare(metric.value, rule_criterion.operator, rule_criterion.threshold)
    return CriterionAssessment(
        rule_criterion.criterion_id,
        rule_criterion.metric,
        rule_criterion.window_id,
        CriterionOutcome.PASS if passed else CriterionOutcome.FAIL,
        metric.value,
        rule_criterion.operator,
        rule_criterion.threshold,
        metric.source_ref,
        "Criterion passed." if passed else "Criterion did not pass.",
    )


def _assess_rule(
    rule: ClassificationRule, metrics: dict[tuple[object, str], MetricObservation]
) -> RuleAssessment:
    criteria = tuple(_criterion(item, metrics) for item in rule.criteria)
    outcomes = {item.outcome for item in criteria}
    passed = sum(item.outcome == CriterionOutcome.PASS for item in criteria)
    if CriterionOutcome.CONFLICT in outcomes:
        outcome = RuleOutcome.CONFLICT
    elif outcomes.intersection({CriterionOutcome.UNKNOWN, CriterionOutcome.NOT_APPLICABLE}):
        outcome = RuleOutcome.UNKNOWN
    elif passed >= rule.required_passes:
        outcome = RuleOutcome.MATCHED
    else:
        outcome = RuleOutcome.NOT_MATCHED
    return RuleAssessment(
        rule.rule_id,
        rule.classification,
        outcome,
        passed,
        rule.required_passes,
        criteria,
    )


def _preview(
    run_id: str,
    snapshot: PerformanceSnapshot,
    evaluation: PerformanceEvaluation,
) -> CreativeDemandPreview | None:
    if evaluation.recommendation not in {
        RecommendationAction.REQUEST_NEW_CREATIVE,
        RecommendationAction.RETEST_CREATIVE,
    }:
        return None
    preview_id = str(uuid5(NAMESPACE_URL, f"performance-preview:{run_id}"))
    return CreativeDemandPreview(
        preview_id=preview_id,
        state=HandoffState.NOT_RELEASED,
        source_decision_run_id=run_id,
        source_evaluation_id=evaluation.evaluation_id,
        brand_id=snapshot.subject.brand_id,
        sku_id=snapshot.subject.sku_id,
        objective=snapshot.objective,
        channel=snapshot.channel,
        action=evaluation.recommendation,
        classification=evaluation.classification,
        evidence_refs=evaluation.evidence_refs,
        missing_context=(
            "product_assets",
            "brand_constraints",
            "approved_claims",
            "persona",
            "output_specification",
            "variation_scope",
        ),
    )


class RunPerformanceDecision:
    def __init__(
        self,
        repository: IPerformanceDecisionRepository,
        opportunity_analyzer: ICreativeOpportunityAnalyzer | None = None,
    ) -> None:
        self._repository = repository
        self._opportunity_analyzer = opportunity_analyzer

    async def execute(self, request: PerformanceDecisionRequest) -> PerformanceDecisionResult:
        existing = await self._repository.get_by_source_run_id(request.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise PerformanceInputDriftError(
                    f"source_run_id {request.source_run_id!r} was reused with changed input"
                )
            return PerformanceDecisionResult(existing, True)
        if request.snapshot.observed_at < request.rule_set.effective_at:
            raise ValueError("Rule set is not effective for the snapshot timestamp")
        rules = tuple(
            rule
            for rule in request.rule_set.rules
            if rule.subject_type == request.snapshot.subject.subject_type
        )
        if not rules:
            raise ValueError("Rule set does not support this analysis grain")
        metrics = {(item.name, item.window_id): item for item in request.snapshot.metrics}
        assessments = tuple(_assess_rule(rule, metrics) for rule in rules)
        matched = max(
            (item for item in assessments if item.outcome == RuleOutcome.MATCHED),
            key=lambda item: _CLASSIFICATION_PRIORITY[item.classification],
            default=None,
        )
        has_conflict = any(item.outcome == RuleOutcome.CONFLICT for item in assessments)
        has_unknown = any(item.outcome == RuleOutcome.UNKNOWN for item in assessments)
        if matched is not None:
            selected_rule = next(rule for rule in rules if rule.rule_id == matched.rule_id)
            state = EvaluationState.READY_FOR_REVIEW
            classification = selected_rule.classification
            recommendation = selected_rule.recommendation
        elif has_conflict:
            state = EvaluationState.BLOCKED_CONFLICT
            classification = PerformanceClassification.CONFLICTING_EVIDENCE
            recommendation = RecommendationAction.MANUAL_REVIEW
        elif has_unknown:
            state = EvaluationState.NEEDS_EVIDENCE
            classification = PerformanceClassification.INSUFFICIENT_EVIDENCE
            recommendation = RecommendationAction.WAIT_FOR_MORE_DATA
        else:
            state = EvaluationState.READY_FOR_REVIEW
            classification = PerformanceClassification.NOT_QUALIFIED
            recommendation = RecommendationAction.NO_ACTION
        evidence_refs = tuple(
            dict.fromkeys(item.source_ref for item in request.snapshot.metrics if item.source_ref)
        )
        evaluation_id = str(
            uuid5(
                NAMESPACE_URL,
                f"performance-evaluation:{request.source_run_id}:{request.rule_set.rule_set_id}:{request.rule_set.version}",
            )
        )
        created_at = datetime.now(UTC)
        evaluation = PerformanceEvaluation(
            evaluation_id=evaluation_id,
            version_number=1,
            state=state,
            classification=classification,
            recommendation=recommendation,
            rule_set_id=request.rule_set.rule_set_id,
            rule_version=request.rule_set.version,
            rule_mode=request.rule_set.mode,
            rule_status=request.rule_set.status,
            assessments=assessments,
            evidence_refs=evidence_refs,
            created_at=created_at,
        )
        run_id = str(uuid5(NAMESPACE_URL, f"performance-decision:{request.source_run_id}"))
        run = PerformanceDecisionRun(
            run_id=run_id,
            source_run_id=request.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            snapshot=request.snapshot,
            evaluation=evaluation,
            created_at=created_at,
            creative_demand_preview=_preview(run_id, request.snapshot, evaluation),
            audit_log=(f"evaluation:{evaluation_id}",),
        )
        if self._opportunity_analyzer is not None:
            evidence_pack = _evidence_pack(request.snapshot, evaluation)
            try:
                analysis = await self._opportunity_analyzer.analyze(evidence_pack)
            except OpportunityAnalysisError:
                run = replace(
                    run,
                    evidence_pack=evidence_pack,
                    audit_log=(*run.audit_log, "opportunity:shadow_failed"),
                )
            else:
                invalid = (
                    analysis.evidence_pack_id != evidence_pack.pack_id
                    or analysis.proposal.sku_id != evidence_pack.sku_id
                    or analysis.proposal.category != analysis.category
                    or analysis.proposal.priority != analysis.priority
                    or (
                        evidence_pack.data_quality_state == EvaluationState.NEEDS_EVIDENCE
                        and analysis.category != OpportunityCategory.DEFER_INSUFFICIENT_EVIDENCE
                    )
                    or (
                        evidence_pack.data_quality_state == EvaluationState.BLOCKED_CONFLICT
                        and analysis.category != OpportunityCategory.BLOCKED_CONFLICT
                    )
                    or bool(
                        {*analysis.evidence_refs, *analysis.proposal.evidence_refs}
                        - set(evidence_pack.evidence_refs)
                    )
                )
                if invalid:
                    run = replace(
                        run,
                        evidence_pack=evidence_pack,
                        audit_log=(*run.audit_log, "opportunity:shadow_invalid_evidence"),
                    )
                else:
                    run = replace(
                        run,
                        evidence_pack=evidence_pack,
                        opportunity_analysis=analysis,
                        audit_log=(*run.audit_log, f"opportunity:{analysis.analysis_id}"),
                    )
        await self._repository.save(run)
        return PerformanceDecisionResult(run, False)


def _evidence_pack(
    snapshot: PerformanceSnapshot,
    evaluation: PerformanceEvaluation,
) -> PerformanceEvidencePack:
    pack_id = str(uuid5(NAMESPACE_URL, f"performance-evidence:{evaluation.evaluation_id}"))
    return PerformanceEvidencePack(
        pack_id=pack_id,
        snapshot_id=snapshot.snapshot_id,
        evaluation_id=evaluation.evaluation_id,
        subject_id=snapshot.subject.subject_id,
        sku_id=snapshot.subject.sku_id,
        objective=snapshot.objective,
        channel=snapshot.channel,
        metrics=tuple(
            PerformanceEvidenceMetric(
                name=item.name,
                window_id=item.window_id,
                status=item.status,
                value=str(item.value) if item.value is not None else None,
                unit=item.unit,
                source_ref=item.source_ref,
            )
            for item in snapshot.metrics
        ),
        rule_assessments=tuple(
            f"{item.rule_id}:{item.outcome.value}:{item.passed_criteria}/{item.required_passes}"
            for item in evaluation.assessments
        ),
        evidence_refs=evaluation.evidence_refs,
        data_quality_state=evaluation.state,
        version="performance-evidence-pack@1",
    )


__all__ = [
    "PerformanceDecisionRequest",
    "PerformanceDecisionResult",
    "RunPerformanceDecision",
]
