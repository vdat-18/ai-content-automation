"""Projection from an approved Creator evaluation into an outreach trigger."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from ai_content.domains.marketing.creator_operations.domain.models import (
    CandidateDecision,
    CreatorEvaluationRun,
)

from ..domain.models import CreatorContactTrigger


def project_creator_contact(run: CreatorEvaluationRun) -> CreatorContactTrigger:
    if run.decision not in {CandidateDecision.CONTACT, CandidateDecision.SHORTLIST}:
        raise ValueError("Creator evaluation has not released contact")
    if run.decision_version_id != run.latest_evaluation.evaluation_id:
        raise ValueError("Creator contact decision does not pin the latest evaluation")
    missing = tuple(
        dict.fromkeys(
            field
            for criterion in run.latest_evaluation.criteria
            for field in criterion.missing_fields
        )
    )
    evidence = tuple(
        dict.fromkeys(
            ref for criterion in run.latest_evaluation.criteria for ref in criterion.evidence_refs
        )
    )
    return CreatorContactTrigger(
        trigger_id=str(
            uuid5(NAMESPACE_URL, f"creator-contact:{run.run_id}:{run.decision_version_id}")
        ),
        source_run_id=f"outreach-{run.source_run_id}-{run.decision_version_id}",
        creator_run_id=run.run_id,
        evaluation_id=run.latest_evaluation.evaluation_id,
        candidate_id=run.candidate_id,
        campaign_id=run.campaign.campaign_id,
        brand_id=run.campaign.brand_id,
        creator_id=run.creator.creator_id,
        creator_alias=run.creator.display_alias,
        source_decision=run.decision.value,
        missing_fields=missing,
        evidence_refs=tuple(dict.fromkeys((*evidence, run.run_id, run.decision_version_id))),
    )


__all__ = ["project_creator_contact"]
