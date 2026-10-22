"""Anti-corruption projections from H2 and X1 into Creative intake triggers."""

from __future__ import annotations

from ai_content.domains.marketing.creative_feedback.domain.models import (
    CreativeFeedbackRun,
    FeedbackDecision,
    TaskPreviewState,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    HandoffState as PerformanceHandoffState,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    PerformanceDecision,
    PerformanceDecisionRun,
)

from ..domain.models import CreativeTaskTrigger, ExperimentDirective, TriggerSource


def project_performance_trigger(run: PerformanceDecisionRun) -> CreativeTaskTrigger:
    preview = run.creative_demand_preview
    proposal = run.approved_proposal
    released = bool(
        run.decision in {PerformanceDecision.APPROVE, PerformanceDecision.EDIT_AND_APPROVE}
        and preview is not None
        and preview.state == PerformanceHandoffState.PREVIEW_READY
    )
    return CreativeTaskTrigger(
        trigger_id=f"h2:{run.run_id}",
        source=TriggerSource.PERFORMANCE_DEMAND,
        source_preview_id=preview.preview_id if preview else f"unreleased-{run.run_id}",
        source_decision_ref=(
            f"{proposal.proposal_id}:v{proposal.version_number}"
            if proposal
            else run.evaluation.evaluation_id
        ),
        source_released=released,
        brand_id=run.snapshot.subject.brand_id,
        sku_id=run.snapshot.subject.sku_id,
        action=(preview.action.value if preview else run.evaluation.recommendation.value),
        objective=run.snapshot.objective,
        channel=run.snapshot.channel,
        evidence_refs=(proposal.evidence_refs if proposal else run.evaluation.evidence_refs),
        requested_at=run.decided_at or run.created_at,
        experiment_directive=(
            ExperimentDirective(
                category=proposal.category.value,
                priority=proposal.priority,
                hypothesis=proposal.hypothesis,
                experiment=proposal.experiment,
                success_signal=proposal.success_signal,
                evidence_refs=proposal.evidence_refs,
                uncertainty=proposal.uncertainty,
            )
            if proposal
            else None
        ),
    )


def project_feedback_trigger(run: CreativeFeedbackRun) -> CreativeTaskTrigger:
    preview = run.next_task_preview
    released = bool(
        run.decision == FeedbackDecision.APPROVE
        and preview is not None
        and preview.state == TaskPreviewState.PREVIEW_READY
    )
    proposal = run.approved_learning_proposal
    evidence = (
        proposal.evidence_refs
        if proposal
        else run.lesson.evidence_refs
        if run.lesson
        else run.performance.evidence_refs
    )
    return CreativeTaskTrigger(
        trigger_id=f"x1:{run.run_id}",
        source=TriggerSource.FEEDBACK_LESSON,
        source_preview_id=preview.preview_id if preview else f"unreleased-{run.run_id}",
        source_decision_ref=(
            f"{proposal.proposal_id}:v{proposal.version_number}"
            if proposal
            else run.lesson.lesson_id
            if run.lesson
            else run.performance.evaluation_id
        ),
        source_released=released,
        brand_id=run.release.brand_id,
        sku_id=run.release.sku_id,
        action=(preview.action.value if preview else run.performance.recommendation.value),
        objective=None,
        channel=run.performance.platform,
        evidence_refs=evidence,
        requested_at=run.decided_at or run.created_at,
        source_creative_version_id=run.release.creative_version_id,
        reusable_context_refs=(preview.reusable_context_refs if preview else ()),
        experiment_directive=(
            ExperimentDirective(
                category=proposal.recommended_action.value,
                priority=proposal.priority,
                hypothesis=proposal.hypothesis,
                experiment=proposal.experiment,
                success_signal=proposal.success_signal,
                evidence_refs=proposal.evidence_refs,
                uncertainty=proposal.uncertainty,
            )
            if proposal
            else None
        ),
    )


__all__ = ["project_feedback_trigger", "project_performance_trigger"]
