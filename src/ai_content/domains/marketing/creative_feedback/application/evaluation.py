"""Deterministic exact-version feedback evaluation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ..domain.models import (
    AdPlacementMapping,
    AdsEvidencePack,
    CreativeFeedbackRun,
    CreativeReleaseSnapshot,
    CriterionOutcome,
    EvaluationState,
    EvidenceStatus,
    FeedbackLesson,
    FeedbackRunState,
    HumanFeedbackObservation,
    LessonOutcome,
    NextCreativeTaskPreview,
    PerformanceClassification,
    PerformanceOutcomeSnapshot,
    RecommendationAction,
    TaskPreviewState,
)
from ..ports.interfaces import (
    CreativeFeedbackInputDriftError,
    ICreativeFeedbackRepository,
    IPerformanceLearningAnalyzer,
    PerformanceLearningAnalysisError,
)


@dataclass(frozen=True)
class CreativeFeedbackRequest:
    source_run_id: str
    source_checksum_sha256: str
    release: CreativeReleaseSnapshot
    ad_mapping: AdPlacementMapping
    performance: PerformanceOutcomeSnapshot
    human_feedback: HumanFeedbackObservation | None = None


@dataclass(frozen=True)
class CreativeFeedbackResult:
    run: CreativeFeedbackRun
    duplicate: bool


def _blocked_state(request: CreativeFeedbackRequest) -> FeedbackRunState | None:
    mapping = request.ad_mapping
    release = request.release
    performance = request.performance
    feedback = request.human_feedback
    if mapping.status == EvidenceStatus.CONFLICT:
        return FeedbackRunState.BLOCKED_CONFLICT
    if mapping.status == EvidenceStatus.UNKNOWN:
        return FeedbackRunState.NEEDS_EVIDENCE
    if mapping.mapped_version_id != release.creative_version_id:
        return FeedbackRunState.BLOCKED_CONFLICT
    if (
        performance.subject_creative_id != release.creative_id
        or performance.brand_id != release.brand_id
        or performance.sku_id != release.sku_id
        or performance.platform != mapping.platform
    ):
        return FeedbackRunState.BLOCKED_CONFLICT
    if performance.subject_version_id is not None and (
        performance.subject_version_id != release.creative_version_id
    ):
        return FeedbackRunState.BLOCKED_CONFLICT
    if feedback is not None:
        if feedback.status == EvidenceStatus.CONFLICT:
            return FeedbackRunState.BLOCKED_CONFLICT
        if feedback.status == EvidenceStatus.KNOWN and (
            feedback.creative_version_id != release.creative_version_id
        ):
            return FeedbackRunState.BLOCKED_CONFLICT
    if (
        performance.state == EvaluationState.BLOCKED_CONFLICT
        or performance.classification == PerformanceClassification.CONFLICTING_EVIDENCE
        or any(item.outcome == CriterionOutcome.CONFLICT for item in performance.criteria)
    ):
        return FeedbackRunState.BLOCKED_CONFLICT
    if (
        performance.state == EvaluationState.NEEDS_EVIDENCE
        or performance.classification == PerformanceClassification.INSUFFICIENT_EVIDENCE
        or any(
            item.outcome in {CriterionOutcome.UNKNOWN, CriterionOutcome.NOT_APPLICABLE}
            for item in performance.criteria
        )
    ):
        return FeedbackRunState.NEEDS_EVIDENCE
    return None


def _lesson_outcome(classification: PerformanceClassification) -> LessonOutcome:
    if classification == PerformanceClassification.CREATIVE_WIN:
        return LessonOutcome.REUSE_SIGNAL
    if classification == PerformanceClassification.CREATIVE_POTENTIAL:
        return LessonOutcome.TEST_SIGNAL
    return LessonOutcome.NO_ACTION_SIGNAL


def _summary(request: CreativeFeedbackRequest, outcome: LessonOutcome) -> str:
    version_id = request.release.creative_version_id
    if outcome == LessonOutcome.REUSE_SIGNAL:
        return f"Performance evidence supports reusing signals from Creative version {version_id}."
    if outcome == LessonOutcome.TEST_SIGNAL:
        return f"Creative version {version_id} has a test signal but is not a confirmed winner."
    return f"Creative version {version_id} did not meet the selected DRAFT rule in this window."


def _evidence_refs(request: CreativeFeedbackRequest) -> tuple[str, ...]:
    refs = [request.release.approval_ref, *request.performance.evidence_refs]
    if request.ad_mapping.evidence_ref:
        refs.append(request.ad_mapping.evidence_ref)
    if request.human_feedback and request.human_feedback.source_ref:
        refs.append(request.human_feedback.source_ref)
    return tuple(dict.fromkeys(refs))


def _create_lesson(
    request: CreativeFeedbackRequest, run_id: str, created_at: datetime
) -> FeedbackLesson:
    performance = request.performance
    outcome = _lesson_outcome(performance.classification)
    facts = [
        f"classification={performance.classification.value}",
        f"recommendation={performance.recommendation.value}",
        f"window={performance.window_id}",
        f"attribution={performance.attribution}",
    ]
    facts.extend(
        f"criterion:{item.criterion_id}={item.outcome.value} "
        f"({item.metric}@{item.window_id}; observed={item.observed_value or 'UNKNOWN'}; "
        f"threshold={item.operator} {item.threshold})"
        for item in performance.criteria
        if item.outcome in {CriterionOutcome.PASS, CriterionOutcome.FAIL}
    )
    feedback = request.human_feedback
    if feedback and feedback.status == EvidenceStatus.KNOWN:
        if feedback.decision:
            facts.append(f"human_feedback_decision={feedback.decision}")
        facts.extend(f"human_feedback_issue={code}" for code in feedback.issue_codes)
    limits = [
        "Performance evidence alone does not isolate audience, offer, landing page, budget, or campaign setup.",
    ]
    if performance.classification == PerformanceClassification.NOT_QUALIFIED:
        limits.append("Not qualified is not proof that the Creative itself is poor.")
    return FeedbackLesson(
        lesson_id=str(uuid5(NAMESPACE_URL, f"creative-feedback-lesson:{run_id}:1")),
        version_number=1,
        creative_version_id=request.release.creative_version_id,
        outcome=outcome,
        summary=_summary(request, outcome),
        supported_facts=tuple(facts),
        non_conclusions=tuple(limits),
        evidence_refs=_evidence_refs(request),
        performance_evaluation_id=performance.evaluation_id,
        rule_set_id=performance.rule_set_id,
        rule_version=performance.rule_version,
        created_at=created_at,
    )


def _create_preview(
    request: CreativeFeedbackRequest,
    run_id: str,
    lesson: FeedbackLesson,
) -> NextCreativeTaskPreview | None:
    performance = request.performance
    if performance.recommendation not in {
        RecommendationAction.REQUEST_NEW_CREATIVE,
        RecommendationAction.RETEST_CREATIVE,
    }:
        return None
    release = request.release
    reusable = [f"idea:{release.idea_id}", f"creative_version:{release.creative_version_id}"]
    for prefix, value in (
        ("persona", release.persona_id),
        ("angle", release.angle_id),
        ("hook", release.hook_id),
        ("concept", release.concept_id),
        ("creative_set", release.creative_set_id),
        ("variation", release.variation_id),
    ):
        if value:
            reusable.append(f"{prefix}:{value}")
    return NextCreativeTaskPreview(
        preview_id=str(uuid5(NAMESPACE_URL, f"creative-feedback-preview:{run_id}")),
        state=TaskPreviewState.NOT_RELEASED,
        action=performance.recommendation,
        source_lesson_id=lesson.lesson_id,
        source_evaluation_id=performance.evaluation_id,
        source_creative_version_id=release.creative_version_id,
        brand_id=release.brand_id,
        sku_id=release.sku_id,
        reusable_context_refs=tuple(reusable),
        missing_context=(
            "product_assets",
            "brand_constraints",
            "approved_claims",
            "output_specification",
            "variation_scope",
        ),
        evidence_refs=lesson.evidence_refs,
    )


class RunCreativeFeedback:
    def __init__(
        self,
        repository: ICreativeFeedbackRepository,
        learning_analyzer: IPerformanceLearningAnalyzer | None = None,
    ) -> None:
        self._repository = repository
        self._learning_analyzer = learning_analyzer

    async def execute(self, request: CreativeFeedbackRequest) -> CreativeFeedbackResult:
        existing = await self._repository.get_by_source_run_id(request.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise CreativeFeedbackInputDriftError(
                    "source_run_id already exists with a different Creative feedback input"
                )
            return CreativeFeedbackResult(existing, True)
        run_id = str(uuid5(NAMESPACE_URL, f"creative-feedback:{request.source_run_id}"))
        created_at = datetime.now(UTC)
        blocked = _blocked_state(request)
        lesson = None
        preview = None
        warnings: list[str] = []
        if request.release.current_version_id != request.release.creative_version_id:
            warnings.append("Performance belongs to a historical Creative version.")
        if blocked is None:
            lesson = _create_lesson(request, run_id, created_at)
            preview = _create_preview(request, run_id, lesson)
            state = (
                FeedbackRunState.READY_FOR_REVIEW
                if preview is not None
                else FeedbackRunState.OBSERVATION_ONLY
            )
        else:
            state = blocked
        run = CreativeFeedbackRun(
            run_id=run_id,
            source_run_id=request.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            release=request.release,
            ad_mapping=request.ad_mapping,
            performance=request.performance,
            human_feedback=request.human_feedback,
            state=state,
            lesson=lesson,
            next_task_preview=preview,
            warnings=tuple(warnings),
            created_at=created_at,
            audit_log=(f"evaluated:{state.value}",),
        )
        if self._learning_analyzer is not None and blocked is None:
            evidence_pack = _ads_evidence_pack(request)
            try:
                analysis = await self._learning_analyzer.analyze(evidence_pack)
            except PerformanceLearningAnalysisError:
                run = replace(
                    run,
                    ads_evidence_pack=evidence_pack,
                    audit_log=(*run.audit_log, "learning:shadow_failed"),
                )
            else:
                proposal = analysis.proposal
                invalid = (
                    analysis.evidence_pack_id != evidence_pack.pack_id
                    or analysis.creative_version_id != evidence_pack.creative_version_id
                    or analysis.sku_id != evidence_pack.sku_id
                    or bool(
                        set(analysis.diagnosis.evidence_refs) - set(evidence_pack.evidence_refs)
                    )
                    or (
                        proposal is not None
                        and (
                            proposal.creative_version_id != evidence_pack.creative_version_id
                            or proposal.sku_id != evidence_pack.sku_id
                            or proposal.recommended_action != evidence_pack.recommendation
                            or bool(set(proposal.evidence_refs) - set(evidence_pack.evidence_refs))
                        )
                    )
                    or (preview is not None and proposal is None)
                    or (preview is None and proposal is not None)
                )
                if invalid:
                    run = replace(
                        run,
                        ads_evidence_pack=evidence_pack,
                        audit_log=(*run.audit_log, "learning:shadow_invalid_evidence"),
                    )
                else:
                    run = replace(
                        run,
                        ads_evidence_pack=evidence_pack,
                        learning_analysis=analysis,
                        audit_log=(*run.audit_log, f"learning:{analysis.analysis_id}"),
                    )
        await self._repository.save(run)
        return CreativeFeedbackResult(run, False)


def _ads_evidence_pack(request: CreativeFeedbackRequest) -> AdsEvidencePack:
    performance = request.performance
    pack_id = str(uuid5(NAMESPACE_URL, f"ads-learning-evidence:{performance.evaluation_id}"))
    return AdsEvidencePack(
        pack_id=pack_id,
        evaluation_id=performance.evaluation_id,
        creative_id=request.release.creative_id,
        creative_version_id=request.release.creative_version_id,
        brand_id=request.release.brand_id,
        sku_id=request.release.sku_id,
        platform=performance.platform,
        window_id=performance.window_id,
        attribution=performance.attribution,
        classification=performance.classification,
        recommendation=performance.recommendation,
        criteria=performance.criteria,
        human_feedback=request.human_feedback,
        evidence_refs=_evidence_refs(request),
        version="ads-learning-evidence@1",
    )


__all__ = ["CreativeFeedbackRequest", "CreativeFeedbackResult", "RunCreativeFeedback"]
