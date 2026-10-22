"""Exact-version projections between existing Marketing bounded contexts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from uuid import NAMESPACE_URL, uuid5

from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJob,
    CreativeJobStatus,
)
from ai_content.domains.marketing.creative_feedback.application.evaluation import (
    CreativeFeedbackRequest,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    AdPlacementMapping,
    CreativeReleaseSnapshot,
    EvidenceStatus,
    PerformanceCriterionFact,
    PerformanceOutcomeSnapshot,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    CriterionOutcome as FeedbackCriterionOutcome,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    EvaluationState as FeedbackEvaluationState,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    PerformanceClassification as FeedbackClassification,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    RecommendationAction as FeedbackRecommendation,
)
from ai_content.domains.marketing.creative_intake.application.contracts import (
    CreativeIntakeCase,
    CreativeIntakeFixture,
    case_for_trigger,
)
from ai_content.domains.marketing.creative_intake.application.resolution import (
    CreativeIntakeRequest,
)
from ai_content.domains.marketing.creative_intake.domain.models import (
    CreativeIntakeRun,
    CreativeTaskTrigger,
)
from ai_content.domains.marketing.performance_decisions.application.evaluation import (
    PerformanceDecisionRequest,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    MetricName,
    MetricObservation,
    PerformanceDecisionRun,
    PerformanceSnapshot,
    PerformanceSubject,
    SubjectType,
)

from ..ports.contracts import AdsOutcome, CreativeLoopInput


def _checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_intake_case(
    fixture: CreativeIntakeFixture,
    context_snapshot_id: str,
    trigger: CreativeTaskTrigger,
) -> CreativeIntakeCase:
    return case_for_trigger(fixture, context_snapshot_id, trigger)


def build_next_intake_case(
    fixture: CreativeIntakeFixture,
    context_snapshot_id: str,
    trigger: CreativeTaskTrigger,
) -> CreativeIntakeCase:
    base = case_for_trigger(fixture, context_snapshot_id, trigger)
    resolved = tuple(
        dict.fromkeys((*base.request.context.resolved_context_refs, *trigger.reusable_context_refs))
    )
    context = replace(base.request.context, resolved_context_refs=resolved)
    request = CreativeIntakeRequest(
        trigger=trigger,
        context=context,
        source_checksum_sha256=_checksum(
            {
                "trigger": asdict(trigger),
                "context": asdict(context),
                "template_source_run_id": base.work_item_template.source_run_id,
                "preparation_pack_hash": base.context_template.pack_hash,
            }
        ),
    )
    return CreativeIntakeCase(request, base.work_item_template, base.context_template)


def build_post_ads_request(
    source: CreativeLoopInput,
    outcome: AdsOutcome,
    *,
    creative_id: str,
    brand_id: str,
    sku_id: str,
) -> PerformanceDecisionRequest:
    source_ref = f"ads://{outcome.platform}/{outcome.account_id}/{outcome.event_id}"
    metrics = tuple(
        MetricObservation(
            name=name,
            window_id=outcome.window_id,
            status=outcome.evidence_status,
            value=value,
            unit=unit,
            source_ref=source_ref,
            observed_at=outcome.observed_at,
        )
        for name, value, unit in (
            (MetricName.PURCHASES, outcome.purchases, "count"),
            (MetricName.ROAS, outcome.roas, "ratio"),
            (MetricName.COST_PER_ATC, outcome.cost_per_atc, "USD"),
        )
    )
    snapshot = PerformanceSnapshot(
        snapshot_id=f"{source.input_snapshot_id}-post-ads-snapshot",
        subject=PerformanceSubject(
            subject_type=SubjectType.CREATIVE,
            subject_id=creative_id,
            brand_id=brand_id,
            store_id=f"{brand_id}-store",
            sku_id=sku_id,
            platform=outcome.platform,
            creative_id=creative_id,
        ),
        objective="Evaluate the approved Creative version after its Ads window",
        channel=outcome.platform,
        timezone=outcome.timezone,
        attribution=outcome.attribution,
        currency="USD",
        source_version="creative-loop-ads@1-draft",
        metrics=metrics,
        observed_at=outcome.observed_at,
    )
    return PerformanceDecisionRequest(
        source_run_id=f"{source.source_run_id}-post-ads-performance",
        source_checksum_sha256=_checksum(
            {
                "loop_checksum": source.source_checksum_sha256,
                "event": asdict(outcome),
                "creative_id": creative_id,
                "brand_id": brand_id,
                "sku_id": sku_id,
            }
        ),
        snapshot=snapshot,
        rule_set=source.initial_performance.rule_set,
    )


def project_creative_release(
    intake: CreativeIntakeRun,
    job: CreativeJob,
) -> CreativeReleaseSnapshot:
    if (
        intake.release is None
        or job.status != CreativeJobStatus.APPROVED
        or job.approval_decision != ApprovalDecision.APPROVE
        or job.card is None
        or job.card.decision != ApprovalDecision.APPROVE
        or job.approved_at is None
        or job.idea_id is None
    ):
        raise ValueError("Only an approved exact Creative job can be released to Ads feedback")
    selected = next(
        (item for item in job.versions if item.version_id.value == job.card.final_version_ref),
        None,
    )
    if selected is None or selected.qa_passed is not True:
        raise ValueError("Approved Creative card must pin a QA-passing version")
    current = job.latest_version
    if current is None:
        raise ValueError("Approved Creative job has no current version")
    return CreativeReleaseSnapshot(
        release_id=str(
            uuid5(NAMESPACE_URL, f"creative-release:{job.job_id}:{selected.version_id}")
        ),
        creative_job_id=job.job_id.value,
        creative_id=job.job_id.value,
        creative_version_id=selected.version_id.value,
        current_version_id=current.version_id.value,
        brand_id=intake.context.brand_id,
        sku_id=intake.context.sku_id,
        idea_id=job.idea_id,
        approval_ref=f"creative-approval:{job.job_id.value}:{selected.version_id.value}",
        approved_at=job.approved_at,
        creative_set_id=selected.creative_set_id,
        variation_id=selected.variation_id,
    )


def project_feedback_request(
    source_run_id: str,
    release: CreativeReleaseSnapshot,
    performance: PerformanceDecisionRun,
    outcome: AdsOutcome,
) -> CreativeFeedbackRequest:
    evaluation = performance.evaluation
    assessment = next(
        (
            item
            for item in evaluation.assessments
            if item.classification.value == evaluation.classification.value
        ),
        evaluation.assessments[0],
    )
    criteria = tuple(
        PerformanceCriterionFact(
            criterion_id=item.criterion_id,
            metric=item.metric.value,
            window_id=item.window_id,
            outcome=FeedbackCriterionOutcome(item.outcome.value),
            observed_value=str(item.observed_value) if item.observed_value is not None else None,
            operator=item.operator.value,
            threshold=str(item.threshold),
            detail=item.detail,
            source_ref=item.source_ref,
        )
        for item in assessment.criteria
    )
    mapping = AdPlacementMapping(
        mapping_id=str(uuid5(NAMESPACE_URL, f"creative-loop-mapping:{source_run_id}")),
        status=outcome.mapping_status,
        platform=outcome.platform,
        account_id=outcome.account_id,
        evidence_ref=f"synthetic://creative-loop/{source_run_id}/ad-mapping",
        observed_at=outcome.observed_at,
        mapped_version_id=(
            release.creative_version_id if outcome.mapping_status == EvidenceStatus.KNOWN else None
        ),
        candidate_version_ids=(
            (release.creative_version_id, f"{release.creative_version_id}-candidate")
            if outcome.mapping_status == EvidenceStatus.CONFLICT
            else ()
        ),
        campaign_id=outcome.campaign_id,
        adset_id=outcome.adset_id,
        ad_id=outcome.ad_id if outcome.mapping_status == EvidenceStatus.KNOWN else None,
        raw_creative_name=f"{release.sku_id}-{release.creative_version_id}",
    )
    snapshot = PerformanceOutcomeSnapshot(
        performance_run_id=performance.run_id,
        evaluation_id=evaluation.evaluation_id,
        state=FeedbackEvaluationState(evaluation.state.value),
        classification=FeedbackClassification(evaluation.classification.value),
        recommendation=FeedbackRecommendation(evaluation.recommendation.value),
        subject_creative_id=release.creative_id,
        subject_version_id=release.creative_version_id,
        brand_id=release.brand_id,
        sku_id=release.sku_id,
        platform=outcome.platform,
        grain="creative",
        window_id=outcome.window_id,
        timezone=outcome.timezone,
        attribution=outcome.attribution,
        rule_set_id=evaluation.rule_set_id,
        rule_version=evaluation.rule_version,
        rule_mode=evaluation.rule_mode.value,
        rule_status=evaluation.rule_status.value,
        criteria=criteria,
        evidence_refs=evaluation.evidence_refs,
        observed_at=outcome.observed_at,
    )
    checksum = _checksum(
        {"release": asdict(release), "mapping": asdict(mapping), "performance": asdict(snapshot)}
    )
    return CreativeFeedbackRequest(
        source_run_id=f"{source_run_id}-feedback",
        source_checksum_sha256=checksum,
        release=release,
        ad_mapping=mapping,
        performance=snapshot,
    )


__all__ = [
    "build_intake_case",
    "build_next_intake_case",
    "build_post_ads_request",
    "project_creative_release",
    "project_feedback_request",
]
