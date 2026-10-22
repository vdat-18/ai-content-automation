"""JSON serialization for Creative feedback records."""

from __future__ import annotations

from datetime import datetime

from ..domain.models import (
    AdPlacementMapping,
    AdsDiagnosis,
    AdsEvidencePack,
    CreativeFeedbackRun,
    CreativeReleaseSnapshot,
    CriterionOutcome,
    EvaluationState,
    EvidenceStatus,
    FeedbackDecision,
    FeedbackLesson,
    FeedbackRunState,
    HumanFeedbackObservation,
    LearningProposal,
    LessonOutcome,
    NextCreativeTaskPreview,
    PerformanceClassification,
    PerformanceCriterionFact,
    PerformanceLearningAnalysis,
    PerformanceOutcomeSnapshot,
    RecommendationAction,
    TaskPreviewState,
)


def run_to_dict(run: CreativeFeedbackRun) -> dict[str, object]:
    release = run.release
    mapping = run.ad_mapping
    performance = run.performance
    feedback = run.human_feedback
    lesson = run.lesson
    preview = run.next_task_preview
    return {
        "run_id": run.run_id,
        "source_run_id": run.source_run_id,
        "source_checksum_sha256": run.source_checksum_sha256,
        "release": {
            "release_id": release.release_id,
            "creative_job_id": release.creative_job_id,
            "creative_id": release.creative_id,
            "creative_version_id": release.creative_version_id,
            "current_version_id": release.current_version_id,
            "brand_id": release.brand_id,
            "sku_id": release.sku_id,
            "idea_id": release.idea_id,
            "approval_ref": release.approval_ref,
            "approved_at": release.approved_at.isoformat(),
            "persona_id": release.persona_id,
            "angle_id": release.angle_id,
            "hook_id": release.hook_id,
            "concept_id": release.concept_id,
            "creative_set_id": release.creative_set_id,
            "variation_id": release.variation_id,
        },
        "ad_mapping": {
            "mapping_id": mapping.mapping_id,
            "status": mapping.status.value,
            "platform": mapping.platform,
            "account_id": mapping.account_id,
            "evidence_ref": mapping.evidence_ref,
            "observed_at": mapping.observed_at.isoformat(),
            "mapped_version_id": mapping.mapped_version_id,
            "candidate_version_ids": list(mapping.candidate_version_ids),
            "campaign_id": mapping.campaign_id,
            "adset_id": mapping.adset_id,
            "ad_id": mapping.ad_id,
            "raw_creative_name": mapping.raw_creative_name,
        },
        "performance": {
            "performance_run_id": performance.performance_run_id,
            "evaluation_id": performance.evaluation_id,
            "state": performance.state.value,
            "classification": performance.classification.value,
            "recommendation": performance.recommendation.value,
            "subject_creative_id": performance.subject_creative_id,
            "subject_version_id": performance.subject_version_id,
            "brand_id": performance.brand_id,
            "sku_id": performance.sku_id,
            "platform": performance.platform,
            "grain": performance.grain,
            "window_id": performance.window_id,
            "timezone": performance.timezone,
            "attribution": performance.attribution,
            "rule_set_id": performance.rule_set_id,
            "rule_version": performance.rule_version,
            "rule_mode": performance.rule_mode,
            "rule_status": performance.rule_status,
            "criteria": [
                {
                    "criterion_id": item.criterion_id,
                    "metric": item.metric,
                    "window_id": item.window_id,
                    "outcome": item.outcome.value,
                    "observed_value": item.observed_value,
                    "operator": item.operator,
                    "threshold": item.threshold,
                    "detail": item.detail,
                    "source_ref": item.source_ref,
                }
                for item in performance.criteria
            ],
            "evidence_refs": list(performance.evidence_refs),
            "observed_at": performance.observed_at.isoformat(),
        },
        "human_feedback": (
            {
                "feedback_id": feedback.feedback_id,
                "status": feedback.status.value,
                "creative_version_id": feedback.creative_version_id,
                "decision": feedback.decision,
                "issue_codes": list(feedback.issue_codes),
                "summary": feedback.summary,
                "source_ref": feedback.source_ref,
                "observed_at": feedback.observed_at.isoformat(),
            }
            if feedback
            else None
        ),
        "state": run.state.value,
        "lesson": (
            {
                "lesson_id": lesson.lesson_id,
                "version_number": lesson.version_number,
                "creative_version_id": lesson.creative_version_id,
                "outcome": lesson.outcome.value,
                "summary": lesson.summary,
                "supported_facts": list(lesson.supported_facts),
                "non_conclusions": list(lesson.non_conclusions),
                "evidence_refs": list(lesson.evidence_refs),
                "performance_evaluation_id": lesson.performance_evaluation_id,
                "rule_set_id": lesson.rule_set_id,
                "rule_version": lesson.rule_version,
                "created_at": lesson.created_at.isoformat(),
            }
            if lesson
            else None
        ),
        "next_task_preview": (
            {
                "preview_id": preview.preview_id,
                "state": preview.state.value,
                "action": preview.action.value,
                "source_lesson_id": preview.source_lesson_id,
                "source_evaluation_id": preview.source_evaluation_id,
                "source_creative_version_id": preview.source_creative_version_id,
                "brand_id": preview.brand_id,
                "sku_id": preview.sku_id,
                "reusable_context_refs": list(preview.reusable_context_refs),
                "missing_context": list(preview.missing_context),
                "evidence_refs": list(preview.evidence_refs),
            }
            if preview
            else None
        ),
        "warnings": list(run.warnings),
        "created_at": run.created_at.isoformat(),
        "ads_evidence_pack": _evidence_pack_to_dict(run.ads_evidence_pack),
        "learning_analysis": _learning_analysis_to_dict(run.learning_analysis),
        "decision": run.decision.value if run.decision else None,
        "decision_lesson_id": run.decision_lesson_id,
        "decision_learning_proposal_id": run.decision_learning_proposal_id,
        "approved_learning_proposal": _learning_proposal_to_dict(run.approved_learning_proposal),
        "reviewer_alias": run.reviewer_alias,
        "decision_reason": run.decision_reason,
        "decided_at": run.decided_at.isoformat() if run.decided_at else None,
        "audit_log": list(run.audit_log),
    }


def run_from_dict(data: dict[str, object]) -> CreativeFeedbackRun:
    release_data = data["release"]
    mapping_data = data["ad_mapping"]
    performance_data = data["performance"]
    assert isinstance(release_data, dict)
    assert isinstance(mapping_data, dict)
    assert isinstance(performance_data, dict)
    release = CreativeReleaseSnapshot(
        release_id=str(release_data["release_id"]),
        creative_job_id=str(release_data["creative_job_id"]),
        creative_id=str(release_data["creative_id"]),
        creative_version_id=str(release_data["creative_version_id"]),
        current_version_id=str(release_data["current_version_id"]),
        brand_id=str(release_data["brand_id"]),
        sku_id=str(release_data["sku_id"]),
        idea_id=str(release_data["idea_id"]),
        approval_ref=str(release_data["approval_ref"]),
        approved_at=datetime.fromisoformat(str(release_data["approved_at"])),
        persona_id=release_data.get("persona_id"),
        angle_id=release_data.get("angle_id"),
        hook_id=release_data.get("hook_id"),
        concept_id=release_data.get("concept_id"),
        creative_set_id=release_data.get("creative_set_id"),
        variation_id=release_data.get("variation_id"),
    )
    mapping = AdPlacementMapping(
        mapping_id=str(mapping_data["mapping_id"]),
        status=EvidenceStatus(mapping_data["status"]),
        platform=str(mapping_data["platform"]),
        account_id=str(mapping_data["account_id"]),
        evidence_ref=mapping_data.get("evidence_ref"),
        observed_at=datetime.fromisoformat(str(mapping_data["observed_at"])),
        mapped_version_id=mapping_data.get("mapped_version_id"),
        candidate_version_ids=tuple(mapping_data.get("candidate_version_ids", [])),
        campaign_id=mapping_data.get("campaign_id"),
        adset_id=mapping_data.get("adset_id"),
        ad_id=mapping_data.get("ad_id"),
        raw_creative_name=mapping_data.get("raw_creative_name"),
    )
    criteria_data = performance_data["criteria"]
    assert isinstance(criteria_data, list)
    performance = PerformanceOutcomeSnapshot(
        performance_run_id=str(performance_data["performance_run_id"]),
        evaluation_id=str(performance_data["evaluation_id"]),
        state=EvaluationState(performance_data["state"]),
        classification=PerformanceClassification(performance_data["classification"]),
        recommendation=RecommendationAction(performance_data["recommendation"]),
        subject_creative_id=str(performance_data["subject_creative_id"]),
        subject_version_id=performance_data.get("subject_version_id"),
        brand_id=str(performance_data["brand_id"]),
        sku_id=str(performance_data["sku_id"]),
        platform=str(performance_data["platform"]),
        grain=str(performance_data["grain"]),
        window_id=str(performance_data["window_id"]),
        timezone=str(performance_data["timezone"]),
        attribution=str(performance_data["attribution"]),
        rule_set_id=str(performance_data["rule_set_id"]),
        rule_version=str(performance_data["rule_version"]),
        rule_mode=str(performance_data["rule_mode"]),
        rule_status=str(performance_data["rule_status"]),
        criteria=tuple(
            PerformanceCriterionFact(
                criterion_id=str(item["criterion_id"]),
                metric=str(item["metric"]),
                window_id=str(item["window_id"]),
                outcome=CriterionOutcome(item["outcome"]),
                observed_value=item.get("observed_value"),
                operator=str(item["operator"]),
                threshold=str(item["threshold"]),
                detail=str(item["detail"]),
                source_ref=item.get("source_ref"),
            )
            for item in criteria_data
        ),
        evidence_refs=tuple(performance_data["evidence_refs"]),
        observed_at=datetime.fromisoformat(str(performance_data["observed_at"])),
    )
    feedback_data = data.get("human_feedback")
    feedback = None
    if isinstance(feedback_data, dict):
        feedback = HumanFeedbackObservation(
            feedback_id=str(feedback_data["feedback_id"]),
            status=EvidenceStatus(feedback_data["status"]),
            creative_version_id=feedback_data.get("creative_version_id"),
            decision=feedback_data.get("decision"),
            issue_codes=tuple(feedback_data.get("issue_codes", [])),
            summary=feedback_data.get("summary"),
            source_ref=feedback_data.get("source_ref"),
            observed_at=datetime.fromisoformat(str(feedback_data["observed_at"])),
        )
    lesson_data = data.get("lesson")
    lesson = None
    if isinstance(lesson_data, dict):
        lesson = FeedbackLesson(
            lesson_id=str(lesson_data["lesson_id"]),
            version_number=int(lesson_data["version_number"]),
            creative_version_id=str(lesson_data["creative_version_id"]),
            outcome=LessonOutcome(lesson_data["outcome"]),
            summary=str(lesson_data["summary"]),
            supported_facts=tuple(lesson_data["supported_facts"]),
            non_conclusions=tuple(lesson_data["non_conclusions"]),
            evidence_refs=tuple(lesson_data["evidence_refs"]),
            performance_evaluation_id=str(lesson_data["performance_evaluation_id"]),
            rule_set_id=str(lesson_data["rule_set_id"]),
            rule_version=str(lesson_data["rule_version"]),
            created_at=datetime.fromisoformat(str(lesson_data["created_at"])),
        )
    preview_data = data.get("next_task_preview")
    preview = None
    if isinstance(preview_data, dict):
        preview = NextCreativeTaskPreview(
            preview_id=str(preview_data["preview_id"]),
            state=TaskPreviewState(preview_data["state"]),
            action=RecommendationAction(preview_data["action"]),
            source_lesson_id=str(preview_data["source_lesson_id"]),
            source_evaluation_id=str(preview_data["source_evaluation_id"]),
            source_creative_version_id=str(preview_data["source_creative_version_id"]),
            brand_id=str(preview_data["brand_id"]),
            sku_id=str(preview_data["sku_id"]),
            reusable_context_refs=tuple(preview_data["reusable_context_refs"]),
            missing_context=tuple(preview_data["missing_context"]),
            evidence_refs=tuple(preview_data["evidence_refs"]),
        )
    decision_value = data.get("decision")
    return CreativeFeedbackRun(
        run_id=str(data["run_id"]),
        source_run_id=str(data["source_run_id"]),
        source_checksum_sha256=str(data["source_checksum_sha256"]),
        release=release,
        ad_mapping=mapping,
        performance=performance,
        human_feedback=feedback,
        state=FeedbackRunState(data["state"]),
        lesson=lesson,
        next_task_preview=preview,
        warnings=tuple(data.get("warnings", [])),
        created_at=datetime.fromisoformat(str(data["created_at"])),
        ads_evidence_pack=_evidence_pack_from_dict(data.get("ads_evidence_pack")),
        learning_analysis=_learning_analysis_from_dict(data.get("learning_analysis")),
        decision=FeedbackDecision(decision_value) if decision_value else None,
        decision_lesson_id=data.get("decision_lesson_id"),
        decision_learning_proposal_id=data.get("decision_learning_proposal_id"),
        approved_learning_proposal=_learning_proposal_from_dict(
            data.get("approved_learning_proposal")
        ),
        reviewer_alias=data.get("reviewer_alias"),
        decision_reason=data.get("decision_reason"),
        decided_at=(
            datetime.fromisoformat(str(data["decided_at"])) if data.get("decided_at") else None
        ),
        audit_log=tuple(data.get("audit_log", [])),
    )


def _criterion_to_dict(item: PerformanceCriterionFact) -> dict[str, object]:
    return {
        "criterion_id": item.criterion_id,
        "metric": item.metric,
        "window_id": item.window_id,
        "outcome": item.outcome.value,
        "observed_value": item.observed_value,
        "operator": item.operator,
        "threshold": item.threshold,
        "detail": item.detail,
        "source_ref": item.source_ref,
    }


def _criterion_from_dict(item: dict[str, object]) -> PerformanceCriterionFact:
    return PerformanceCriterionFact(
        criterion_id=str(item["criterion_id"]),
        metric=str(item["metric"]),
        window_id=str(item["window_id"]),
        outcome=CriterionOutcome(item["outcome"]),
        observed_value=item.get("observed_value"),
        operator=str(item["operator"]),
        threshold=str(item["threshold"]),
        detail=str(item["detail"]),
        source_ref=item.get("source_ref"),
    )


def _evidence_pack_to_dict(pack: AdsEvidencePack | None) -> dict[str, object] | None:
    if pack is None:
        return None
    return {
        "pack_id": pack.pack_id,
        "evaluation_id": pack.evaluation_id,
        "creative_id": pack.creative_id,
        "creative_version_id": pack.creative_version_id,
        "brand_id": pack.brand_id,
        "sku_id": pack.sku_id,
        "platform": pack.platform,
        "window_id": pack.window_id,
        "attribution": pack.attribution,
        "classification": pack.classification.value,
        "recommendation": pack.recommendation.value,
        "criteria": [_criterion_to_dict(item) for item in pack.criteria],
        "human_feedback": _human_feedback_to_dict(pack.human_feedback),
        "evidence_refs": list(pack.evidence_refs),
        "version": pack.version,
    }


def _evidence_pack_from_dict(data: object) -> AdsEvidencePack | None:
    if not isinstance(data, dict):
        return None
    return AdsEvidencePack(
        pack_id=str(data["pack_id"]),
        evaluation_id=str(data["evaluation_id"]),
        creative_id=str(data["creative_id"]),
        creative_version_id=str(data["creative_version_id"]),
        brand_id=str(data["brand_id"]),
        sku_id=str(data["sku_id"]),
        platform=str(data["platform"]),
        window_id=str(data["window_id"]),
        attribution=str(data["attribution"]),
        classification=PerformanceClassification(data["classification"]),
        recommendation=RecommendationAction(data["recommendation"]),
        criteria=tuple(_criterion_from_dict(item) for item in data["criteria"]),
        human_feedback=_human_feedback_from_dict(data.get("human_feedback")),
        evidence_refs=tuple(data["evidence_refs"]),
        version=str(data["version"]),
    )


def _human_feedback_to_dict(
    feedback: HumanFeedbackObservation | None,
) -> dict[str, object] | None:
    if feedback is None:
        return None
    return {
        "feedback_id": feedback.feedback_id,
        "status": feedback.status.value,
        "creative_version_id": feedback.creative_version_id,
        "decision": feedback.decision,
        "issue_codes": list(feedback.issue_codes),
        "summary": feedback.summary,
        "source_ref": feedback.source_ref,
        "observed_at": feedback.observed_at.isoformat(),
    }


def _human_feedback_from_dict(data: object) -> HumanFeedbackObservation | None:
    if not isinstance(data, dict):
        return None
    return HumanFeedbackObservation(
        feedback_id=str(data["feedback_id"]),
        status=EvidenceStatus(data["status"]),
        creative_version_id=data.get("creative_version_id"),
        decision=data.get("decision"),
        issue_codes=tuple(data.get("issue_codes", [])),
        summary=data.get("summary"),
        source_ref=data.get("source_ref"),
        observed_at=datetime.fromisoformat(str(data["observed_at"])),
    )


def _learning_proposal_to_dict(proposal: LearningProposal | None) -> dict[str, object] | None:
    if proposal is None:
        return None
    return {
        "proposal_id": proposal.proposal_id,
        "version_number": proposal.version_number,
        "creative_version_id": proposal.creative_version_id,
        "sku_id": proposal.sku_id,
        "priority": proposal.priority,
        "recommended_action": proposal.recommended_action.value,
        "hypothesis": proposal.hypothesis,
        "experiment": proposal.experiment,
        "success_signal": proposal.success_signal,
        "evidence_refs": list(proposal.evidence_refs),
        "uncertainty": proposal.uncertainty,
    }


def _learning_proposal_from_dict(data: object) -> LearningProposal | None:
    if not isinstance(data, dict):
        return None
    return LearningProposal(
        proposal_id=str(data["proposal_id"]),
        version_number=int(data["version_number"]),
        creative_version_id=str(data["creative_version_id"]),
        sku_id=str(data["sku_id"]),
        priority=int(data["priority"]),
        recommended_action=RecommendationAction(data["recommended_action"]),
        hypothesis=str(data["hypothesis"]),
        experiment=str(data["experiment"]),
        success_signal=str(data["success_signal"]),
        evidence_refs=tuple(data["evidence_refs"]),
        uncertainty=str(data["uncertainty"]),
    )


def _learning_analysis_to_dict(
    analysis: PerformanceLearningAnalysis | None,
) -> dict[str, object] | None:
    if analysis is None:
        return None
    return {
        "analysis_id": analysis.analysis_id,
        "evidence_pack_id": analysis.evidence_pack_id,
        "creative_version_id": analysis.creative_version_id,
        "sku_id": analysis.sku_id,
        "diagnosis": {
            "observations": list(analysis.diagnosis.observations),
            "hypotheses": list(analysis.diagnosis.hypotheses),
            "confounders": list(analysis.diagnosis.confounders),
            "uncertainty": analysis.diagnosis.uncertainty,
            "evidence_refs": list(analysis.diagnosis.evidence_refs),
        },
        "proposal": _learning_proposal_to_dict(analysis.proposal),
        "prompt_version": analysis.prompt_version,
        "model": analysis.model,
        "rubric_version": analysis.rubric_version,
        "created_at": analysis.created_at.isoformat(),
    }


def _learning_analysis_from_dict(data: object) -> PerformanceLearningAnalysis | None:
    if not isinstance(data, dict):
        return None
    diagnosis = data["diagnosis"]
    assert isinstance(diagnosis, dict)
    return PerformanceLearningAnalysis(
        analysis_id=str(data["analysis_id"]),
        evidence_pack_id=str(data["evidence_pack_id"]),
        creative_version_id=str(data["creative_version_id"]),
        sku_id=str(data["sku_id"]),
        diagnosis=AdsDiagnosis(
            observations=tuple(diagnosis["observations"]),
            hypotheses=tuple(diagnosis["hypotheses"]),
            confounders=tuple(diagnosis["confounders"]),
            uncertainty=str(diagnosis["uncertainty"]),
            evidence_refs=tuple(diagnosis["evidence_refs"]),
        ),
        proposal=_learning_proposal_from_dict(data.get("proposal")),
        prompt_version=str(data["prompt_version"]),
        model=str(data["model"]),
        rubric_version=str(data["rubric_version"]),
        created_at=datetime.fromisoformat(str(data["created_at"])),
    )


__all__ = ["run_from_dict", "run_to_dict"]
