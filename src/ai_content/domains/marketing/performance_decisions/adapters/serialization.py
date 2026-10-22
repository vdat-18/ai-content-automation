"""JSON serialization for Performance decision records."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ..domain.models import (
    ComparisonOperator,
    CreativeDemandPreview,
    CreativeOpportunityAnalysis,
    CriterionAssessment,
    CriterionOutcome,
    EvaluationState,
    ExperimentProposal,
    HandoffState,
    MetricName,
    MetricObservation,
    MetricStatus,
    OpportunityCategory,
    PerformanceClassification,
    PerformanceDecision,
    PerformanceDecisionRun,
    PerformanceEvaluation,
    PerformanceEvidenceMetric,
    PerformanceEvidencePack,
    PerformanceSnapshot,
    PerformanceSubject,
    RecommendationAction,
    RuleAssessment,
    RuleMode,
    RuleOutcome,
    RuleStatus,
    SubjectType,
)


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def run_to_dict(run: PerformanceDecisionRun) -> dict[str, object]:
    snapshot = run.snapshot
    evaluation = run.evaluation
    preview = run.creative_demand_preview
    return {
        "run_id": run.run_id,
        "source_run_id": run.source_run_id,
        "source_checksum_sha256": run.source_checksum_sha256,
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "subject": {
                "subject_type": snapshot.subject.subject_type.value,
                "subject_id": snapshot.subject.subject_id,
                "brand_id": snapshot.subject.brand_id,
                "store_id": snapshot.subject.store_id,
                "sku_id": snapshot.subject.sku_id,
                "platform": snapshot.subject.platform,
                "creative_id": snapshot.subject.creative_id,
                "angle_id": snapshot.subject.angle_id,
                "concept_id": snapshot.subject.concept_id,
                "persona_id": snapshot.subject.persona_id,
                "raw_source_name": snapshot.subject.raw_source_name,
            },
            "objective": snapshot.objective,
            "channel": snapshot.channel,
            "timezone": snapshot.timezone,
            "attribution": snapshot.attribution,
            "currency": snapshot.currency,
            "source_version": snapshot.source_version,
            "observed_at": snapshot.observed_at.isoformat(),
            "metrics": [
                {
                    "name": metric.name.value,
                    "window_id": metric.window_id,
                    "status": metric.status.value,
                    "value": str(metric.value) if metric.value is not None else None,
                    "unit": metric.unit,
                    "source_ref": metric.source_ref,
                    "observed_at": metric.observed_at.isoformat(),
                }
                for metric in snapshot.metrics
            ],
        },
        "evaluation": {
            "evaluation_id": evaluation.evaluation_id,
            "version_number": evaluation.version_number,
            "state": evaluation.state.value,
            "classification": evaluation.classification.value,
            "recommendation": evaluation.recommendation.value,
            "rule_set_id": evaluation.rule_set_id,
            "rule_version": evaluation.rule_version,
            "rule_mode": evaluation.rule_mode.value,
            "rule_status": evaluation.rule_status.value,
            "evidence_refs": list(evaluation.evidence_refs),
            "created_at": evaluation.created_at.isoformat(),
            "assessments": [
                {
                    "rule_id": assessment.rule_id,
                    "classification": assessment.classification.value,
                    "outcome": assessment.outcome.value,
                    "passed_criteria": assessment.passed_criteria,
                    "required_passes": assessment.required_passes,
                    "criteria": [
                        {
                            "criterion_id": criterion.criterion_id,
                            "metric": criterion.metric.value,
                            "window_id": criterion.window_id,
                            "outcome": criterion.outcome.value,
                            "observed_value": str(criterion.observed_value)
                            if criterion.observed_value is not None
                            else None,
                            "operator": criterion.operator.value,
                            "threshold": str(criterion.threshold),
                            "source_ref": criterion.source_ref,
                            "detail": criterion.detail,
                        }
                        for criterion in assessment.criteria
                    ],
                }
                for assessment in evaluation.assessments
            ],
        },
        "created_at": run.created_at.isoformat(),
        "decision": run.decision.value if run.decision else None,
        "decision_evaluation_id": run.decision_evaluation_id,
        "reviewer_alias": run.reviewer_alias,
        "decision_reason": run.decision_reason,
        "decided_at": run.decided_at.isoformat() if run.decided_at else None,
        "creative_demand_preview": (
            {
                "preview_id": preview.preview_id,
                "state": preview.state.value,
                "source_decision_run_id": preview.source_decision_run_id,
                "source_evaluation_id": preview.source_evaluation_id,
                "brand_id": preview.brand_id,
                "sku_id": preview.sku_id,
                "objective": preview.objective,
                "channel": preview.channel,
                "action": preview.action.value,
                "classification": preview.classification.value,
                "evidence_refs": list(preview.evidence_refs),
                "missing_context": list(preview.missing_context),
            }
            if preview
            else None
        ),
        "evidence_pack": _evidence_pack_to_dict(run.evidence_pack),
        "opportunity_analysis": _analysis_to_dict(run.opportunity_analysis),
        "decision_proposal_id": run.decision_proposal_id,
        "approved_proposal": _proposal_to_dict(run.approved_proposal),
        "audit_log": list(run.audit_log),
    }


def _proposal_to_dict(proposal: ExperimentProposal | None) -> dict[str, object] | None:
    if proposal is None:
        return None
    return {
        "proposal_id": proposal.proposal_id,
        "version_number": proposal.version_number,
        "sku_id": proposal.sku_id,
        "priority": proposal.priority,
        "category": proposal.category.value,
        "hypothesis": proposal.hypothesis,
        "experiment": proposal.experiment,
        "success_signal": proposal.success_signal,
        "evidence_refs": list(proposal.evidence_refs),
        "uncertainty": proposal.uncertainty,
    }


def _proposal_from_dict(data: object) -> ExperimentProposal | None:
    if not isinstance(data, dict):
        return None
    return ExperimentProposal(
        proposal_id=str(data["proposal_id"]),
        version_number=int(data["version_number"]),
        sku_id=str(data["sku_id"]),
        priority=int(data["priority"]),
        category=OpportunityCategory(data["category"]),
        hypothesis=str(data["hypothesis"]),
        experiment=str(data["experiment"]),
        success_signal=str(data["success_signal"]),
        evidence_refs=tuple(data["evidence_refs"]),
        uncertainty=str(data["uncertainty"]),
    )


def _evidence_pack_to_dict(pack: PerformanceEvidencePack | None) -> dict[str, object] | None:
    if pack is None:
        return None
    return {
        "pack_id": pack.pack_id,
        "snapshot_id": pack.snapshot_id,
        "evaluation_id": pack.evaluation_id,
        "subject_id": pack.subject_id,
        "sku_id": pack.sku_id,
        "objective": pack.objective,
        "channel": pack.channel,
        "metrics": [
            {
                "name": item.name.value,
                "window_id": item.window_id,
                "status": item.status.value,
                "value": item.value,
                "unit": item.unit,
                "source_ref": item.source_ref,
            }
            for item in pack.metrics
        ],
        "rule_assessments": list(pack.rule_assessments),
        "evidence_refs": list(pack.evidence_refs),
        "data_quality_state": pack.data_quality_state.value,
        "version": pack.version,
    }


def _evidence_pack_from_dict(data: object) -> PerformanceEvidencePack | None:
    if not isinstance(data, dict):
        return None
    return PerformanceEvidencePack(
        pack_id=str(data["pack_id"]),
        snapshot_id=str(data["snapshot_id"]),
        evaluation_id=str(data["evaluation_id"]),
        subject_id=str(data["subject_id"]),
        sku_id=str(data["sku_id"]),
        objective=str(data["objective"]),
        channel=str(data["channel"]),
        metrics=tuple(
            PerformanceEvidenceMetric(
                name=MetricName(item["name"]),
                window_id=str(item["window_id"]),
                status=MetricStatus(item["status"]),
                value=item.get("value"),
                unit=str(item["unit"]),
                source_ref=item.get("source_ref"),
            )
            for item in data["metrics"]
        ),
        rule_assessments=tuple(data["rule_assessments"]),
        evidence_refs=tuple(data["evidence_refs"]),
        data_quality_state=EvaluationState(data["data_quality_state"]),
        version=str(data["version"]),
    )


def _analysis_to_dict(
    analysis: CreativeOpportunityAnalysis | None,
) -> dict[str, object] | None:
    if analysis is None:
        return None
    return {
        "analysis_id": analysis.analysis_id,
        "evidence_pack_id": analysis.evidence_pack_id,
        "category": analysis.category.value,
        "priority": analysis.priority,
        "rationale": analysis.rationale,
        "evidence_refs": list(analysis.evidence_refs),
        "uncertainty": analysis.uncertainty,
        "counterargument": analysis.counterargument,
        "proposal": _proposal_to_dict(analysis.proposal),
        "prompt_version": analysis.prompt_version,
        "model": analysis.model,
        "rubric_version": analysis.rubric_version,
        "created_at": analysis.created_at.isoformat(),
    }


def _analysis_from_dict(data: object) -> CreativeOpportunityAnalysis | None:
    if not isinstance(data, dict):
        return None
    proposal = _proposal_from_dict(data["proposal"])
    assert proposal is not None
    return CreativeOpportunityAnalysis(
        analysis_id=str(data["analysis_id"]),
        evidence_pack_id=str(data["evidence_pack_id"]),
        category=OpportunityCategory(data["category"]),
        priority=int(data["priority"]),
        rationale=str(data["rationale"]),
        evidence_refs=tuple(data["evidence_refs"]),
        uncertainty=str(data["uncertainty"]),
        counterargument=str(data["counterargument"]),
        proposal=proposal,
        prompt_version=str(data["prompt_version"]),
        model=str(data["model"]),
        rubric_version=str(data["rubric_version"]),
        created_at=datetime.fromisoformat(str(data["created_at"])),
    )


def run_from_dict(data: dict[str, object]) -> PerformanceDecisionRun:
    snapshot_data = data["snapshot"]
    assert isinstance(snapshot_data, dict)
    subject_data = snapshot_data["subject"]
    assert isinstance(subject_data, dict)
    subject = PerformanceSubject(
        subject_type=SubjectType(subject_data["subject_type"]),
        subject_id=str(subject_data["subject_id"]),
        brand_id=str(subject_data["brand_id"]),
        store_id=str(subject_data["store_id"]),
        sku_id=str(subject_data["sku_id"]),
        platform=str(subject_data["platform"]),
        creative_id=subject_data.get("creative_id"),
        angle_id=subject_data.get("angle_id"),
        concept_id=subject_data.get("concept_id"),
        persona_id=subject_data.get("persona_id"),
        raw_source_name=subject_data.get("raw_source_name"),
    )
    metrics_data = snapshot_data["metrics"]
    assert isinstance(metrics_data, list)
    snapshot = PerformanceSnapshot(
        snapshot_id=str(snapshot_data["snapshot_id"]),
        subject=subject,
        objective=str(snapshot_data["objective"]),
        channel=str(snapshot_data["channel"]),
        timezone=str(snapshot_data["timezone"]),
        attribution=str(snapshot_data["attribution"]),
        currency=str(snapshot_data["currency"]),
        source_version=str(snapshot_data["source_version"]),
        metrics=tuple(
            MetricObservation(
                name=MetricName(item["name"]),
                window_id=str(item["window_id"]),
                status=MetricStatus(item["status"]),
                value=_decimal(item.get("value")),
                unit=str(item["unit"]),
                source_ref=item.get("source_ref"),
                observed_at=datetime.fromisoformat(str(item["observed_at"])),
            )
            for item in metrics_data
        ),
        observed_at=datetime.fromisoformat(str(snapshot_data["observed_at"])),
    )
    evaluation_data = data["evaluation"]
    assert isinstance(evaluation_data, dict)
    assessments_data = evaluation_data["assessments"]
    assert isinstance(assessments_data, list)
    evaluation = PerformanceEvaluation(
        evaluation_id=str(evaluation_data["evaluation_id"]),
        version_number=int(evaluation_data["version_number"]),
        state=EvaluationState(evaluation_data["state"]),
        classification=PerformanceClassification(evaluation_data["classification"]),
        recommendation=RecommendationAction(evaluation_data["recommendation"]),
        rule_set_id=str(evaluation_data["rule_set_id"]),
        rule_version=str(evaluation_data["rule_version"]),
        rule_mode=RuleMode(evaluation_data["rule_mode"]),
        rule_status=RuleStatus(evaluation_data["rule_status"]),
        assessments=tuple(
            RuleAssessment(
                rule_id=str(item["rule_id"]),
                classification=PerformanceClassification(item["classification"]),
                outcome=RuleOutcome(item["outcome"]),
                passed_criteria=int(item["passed_criteria"]),
                required_passes=int(item["required_passes"]),
                criteria=tuple(
                    CriterionAssessment(
                        criterion_id=str(criterion["criterion_id"]),
                        metric=MetricName(criterion["metric"]),
                        window_id=str(criterion["window_id"]),
                        outcome=CriterionOutcome(criterion["outcome"]),
                        observed_value=_decimal(criterion.get("observed_value")),
                        operator=ComparisonOperator(criterion["operator"]),
                        threshold=Decimal(str(criterion["threshold"])),
                        source_ref=criterion.get("source_ref"),
                        detail=str(criterion["detail"]),
                    )
                    for criterion in item["criteria"]
                ),
            )
            for item in assessments_data
        ),
        evidence_refs=tuple(evaluation_data["evidence_refs"]),
        created_at=datetime.fromisoformat(str(evaluation_data["created_at"])),
    )
    preview_data = data.get("creative_demand_preview")
    preview = None
    if isinstance(preview_data, dict):
        preview = CreativeDemandPreview(
            preview_id=str(preview_data["preview_id"]),
            state=HandoffState(preview_data["state"]),
            source_decision_run_id=str(preview_data["source_decision_run_id"]),
            source_evaluation_id=str(preview_data["source_evaluation_id"]),
            brand_id=str(preview_data["brand_id"]),
            sku_id=str(preview_data["sku_id"]),
            objective=str(preview_data["objective"]),
            channel=str(preview_data["channel"]),
            action=RecommendationAction(preview_data["action"]),
            classification=PerformanceClassification(preview_data["classification"]),
            evidence_refs=tuple(preview_data["evidence_refs"]),
            missing_context=tuple(preview_data["missing_context"]),
        )
    decision_value = data.get("decision")
    return PerformanceDecisionRun(
        run_id=str(data["run_id"]),
        source_run_id=str(data["source_run_id"]),
        source_checksum_sha256=str(data["source_checksum_sha256"]),
        snapshot=snapshot,
        evaluation=evaluation,
        created_at=datetime.fromisoformat(str(data["created_at"])),
        decision=PerformanceDecision(decision_value) if decision_value else None,
        decision_evaluation_id=data.get("decision_evaluation_id"),
        reviewer_alias=data.get("reviewer_alias"),
        decision_reason=data.get("decision_reason"),
        decided_at=datetime.fromisoformat(str(data["decided_at"]))
        if data.get("decided_at")
        else None,
        creative_demand_preview=preview,
        evidence_pack=_evidence_pack_from_dict(data.get("evidence_pack")),
        opportunity_analysis=_analysis_from_dict(data.get("opportunity_analysis")),
        decision_proposal_id=data.get("decision_proposal_id"),
        approved_proposal=_proposal_from_dict(data.get("approved_proposal")),
        audit_log=tuple(data.get("audit_log", [])),
    )


__all__ = ["run_from_dict", "run_to_dict"]
