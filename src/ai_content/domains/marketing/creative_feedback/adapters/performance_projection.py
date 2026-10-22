"""Translate an H2 decision into the immutable X1 Performance snapshot."""

from __future__ import annotations

from ai_content.domains.marketing.performance_decisions.domain.models import (
    PerformanceDecisionRun,
    SubjectType,
)

from ..domain.models import (
    CriterionOutcome,
    EvaluationState,
    PerformanceClassification,
    PerformanceCriterionFact,
    PerformanceOutcomeSnapshot,
    RecommendationAction,
)


def project_performance_outcome(run: PerformanceDecisionRun) -> PerformanceOutcomeSnapshot:
    """Copy H2 facts without recalculating metrics or changing its decision."""
    subject = run.snapshot.subject
    if subject.subject_type != SubjectType.CREATIVE or subject.creative_id is None:
        raise ValueError("X1 requires an H2 creative-grain run with a stable creative_id")
    criteria = tuple(
        PerformanceCriterionFact(
            criterion_id=f"{assessment.rule_id}:{criterion.criterion_id}",
            metric=criterion.metric.value,
            window_id=criterion.window_id,
            outcome=CriterionOutcome(criterion.outcome.value),
            observed_value=(
                str(criterion.observed_value) if criterion.observed_value is not None else None
            ),
            operator=criterion.operator.value,
            threshold=str(criterion.threshold),
            detail=criterion.detail,
            source_ref=criterion.source_ref,
        )
        for assessment in run.evaluation.assessments
        for criterion in assessment.criteria
    )
    windows = tuple(dict.fromkeys(item.window_id for item in criteria))
    return PerformanceOutcomeSnapshot(
        performance_run_id=run.run_id,
        evaluation_id=run.evaluation.evaluation_id,
        state=EvaluationState(run.evaluation.state.value),
        classification=PerformanceClassification(run.evaluation.classification.value),
        recommendation=RecommendationAction(run.evaluation.recommendation.value),
        subject_creative_id=subject.creative_id,
        subject_version_id=None,
        brand_id=subject.brand_id,
        sku_id=subject.sku_id,
        platform=subject.platform,
        grain=subject.subject_type.value,
        window_id=windows[0] if len(windows) == 1 else "mixed-windows",
        timezone=run.snapshot.timezone,
        attribution=run.snapshot.attribution,
        rule_set_id=run.evaluation.rule_set_id,
        rule_version=run.evaluation.rule_version,
        rule_mode=run.evaluation.rule_mode.value,
        rule_status=run.evaluation.rule_status.value,
        criteria=criteria,
        evidence_refs=run.evaluation.evidence_refs,
        observed_at=run.snapshot.observed_at,
    )


__all__ = ["project_performance_outcome"]
