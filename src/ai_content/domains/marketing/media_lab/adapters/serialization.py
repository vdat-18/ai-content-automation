"""Serialization for persisted Media Lab image runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.models import (
    ImageGenerationState,
    ImageIntent,
    ImageOrchestrationTrace,
    ImageOutputFormat,
    ImageOutputSpec,
    ImageQualityDecision,
    ImageQualityIssue,
    ImageQualityIssueSeverity,
    ImageQualityReview,
    ImageQualityReviewState,
    ImageReference,
    ImageReferenceRole,
    ImageRetryAttempt,
    ImageRetryMemory,
    ImageReviewState,
    ImageRun,
    ImageSourceOrigin,
)


def run_to_dict(run: ImageRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "intent": run.intent.value,
        "prompt": run.prompt,
        "rendered_prompt": run.rendered_prompt,
        "references": [
            {
                "reference_id": item.reference_id,
                "role": item.role.value,
                "priority": item.priority,
                "must_preserve": list(item.must_preserve),
                "allowed_changes": list(item.allowed_changes),
                "source_origin": item.source_origin.value,
                "source_checksum_sha256": item.source_checksum_sha256,
                "artifact_ref": item.artifact_ref,
                "content_type": item.content_type,
                "source_run_id": item.source_run_id,
                "asset_id": item.asset_id,
                "identity_group": item.identity_group,
            }
            for item in run.references
        ],
        "output_spec": {
            "width": run.output_spec.width,
            "height": run.output_spec.height,
            "candidate_count": run.output_spec.candidate_count,
            "preset_id": run.output_spec.preset_id,
            "aspect_ratio": run.output_spec.aspect_ratio,
            "delivery_format": run.output_spec.delivery_format.value,
        },
        "seed": run.seed,
        "generation_state": run.generation_state.value,
        "review_state": run.review_state.value,
        "model": run.model,
        "checkpoint_observation": run.checkpoint_observation,
        "graph_template_hash": run.graph_template_hash,
        "backend_run_id": run.backend_run_id,
        "provider_job_id": run.provider_job_id,
        "queue_wait_milliseconds": run.queue_wait_milliseconds,
        "provider_delay_milliseconds": run.provider_delay_milliseconds,
        "provider_execution_milliseconds": run.provider_execution_milliseconds,
        "parent_run_id": run.parent_run_id,
        "orchestration": (
            {
                "user_request": run.orchestration.user_request,
                "capability_id": run.orchestration.capability_id,
                "summary": run.orchestration.summary,
                "planner_model": run.orchestration.planner_model,
                "planner_prompt_version": run.orchestration.planner_prompt_version,
                "planner_prompt_hash": run.orchestration.planner_prompt_hash,
                "planner_config_hash": run.orchestration.planner_config_hash,
                "plan_hash": run.orchestration.plan_hash,
            }
            if run.orchestration is not None
            else None
        ),
        "output_ref": run.output_ref,
        "output_asset_id": run.output_asset_id,
        "output_checksum_sha256": run.output_checksum_sha256,
        "output_content_type": run.output_content_type,
        "delivery_ref": run.delivery_ref,
        "delivery_checksum_sha256": run.delivery_checksum_sha256,
        "delivery_content_type": run.delivery_content_type,
        "retry_memory": _retry_memory_to_dict(run.retry_memory),
        "manifest_ref": run.manifest_ref,
        "error_code": run.error_code,
        "quality_review_state": run.quality_review_state.value,
        "quality_review": (
            {
                "decision": run.quality_review.decision.value,
                "summary": run.quality_review.summary,
                "issues": [
                    {
                        "category": issue.category,
                        "severity": issue.severity.value,
                        "description": issue.description,
                    }
                    for issue in run.quality_review.issues
                ],
                "repair_instructions": list(run.quality_review.repair_instructions),
                "uncertainties": list(run.quality_review.uncertainties),
                "reviewer_model": run.quality_review.reviewer_model,
                "reviewer_prompt_version": run.quality_review.reviewer_prompt_version,
                "reviewer_prompt_hash": run.quality_review.reviewer_prompt_hash,
                "reviewer_config_hash": run.quality_review.reviewer_config_hash,
                "review_hash": run.quality_review.review_hash,
                "repair_prompt": run.quality_review.repair_prompt,
                "repair_prompt_version": run.quality_review.repair_prompt_version,
                "repair_prompt_hash": run.quality_review.repair_prompt_hash,
            }
            if run.quality_review is not None
            else None
        ),
        "quality_review_error_code": run.quality_review_error_code,
        "regenerated_run_id": run.regenerated_run_id,
        "retry_of_run_id": run.retry_of_run_id,
        "regeneration_count": run.regeneration_count,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "reviewed_at": run.reviewed_at.isoformat() if run.reviewed_at else None,
    }


def run_from_dict(payload: dict[str, Any]) -> ImageRun:
    references = tuple(
        ImageReference(
            reference_id=item["reference_id"],
            role=ImageReferenceRole(item["role"]),
            priority=item["priority"],
            must_preserve=tuple(item["must_preserve"]),
            allowed_changes=tuple(item["allowed_changes"]),
            source_origin=ImageSourceOrigin(item["source_origin"]),
            source_checksum_sha256=item["source_checksum_sha256"],
            artifact_ref=item["artifact_ref"],
            content_type=item["content_type"],
            source_run_id=item.get("source_run_id"),
            asset_id=item.get("asset_id"),
            identity_group=item.get("identity_group"),
        )
        for item in payload["references"]
    )
    output_spec = payload["output_spec"]
    return ImageRun(
        run_id=payload["run_id"],
        intent=ImageIntent(payload["intent"]),
        prompt=payload["prompt"],
        rendered_prompt=payload["rendered_prompt"],
        references=references,
        output_spec=ImageOutputSpec(
            width=output_spec["width"],
            height=output_spec["height"],
            candidate_count=output_spec["candidate_count"],
            preset_id=output_spec.get("preset_id"),
            aspect_ratio=output_spec.get("aspect_ratio"),
            delivery_format=ImageOutputFormat(
                output_spec.get("delivery_format", ImageOutputFormat.PNG.value)
            ),
        ),
        seed=payload.get("seed"),
        generation_state=ImageGenerationState(payload["generation_state"]),
        review_state=ImageReviewState(payload["review_state"]),
        model=payload.get("model"),
        checkpoint_observation=payload.get("checkpoint_observation"),
        graph_template_hash=payload.get("graph_template_hash"),
        backend_run_id=payload.get("backend_run_id"),
        provider_job_id=payload.get("provider_job_id"),
        parent_run_id=payload.get("parent_run_id"),
        orchestration=_orchestration_or_none(payload.get("orchestration")),
        output_ref=payload.get("output_ref"),
        output_checksum_sha256=payload.get("output_checksum_sha256"),
        output_content_type=payload.get("output_content_type"),
        delivery_ref=payload.get("delivery_ref"),
        delivery_checksum_sha256=payload.get("delivery_checksum_sha256"),
        delivery_content_type=payload.get("delivery_content_type"),
        retry_memory=_retry_memory_or_none(payload.get("retry_memory")),
        manifest_ref=payload.get("manifest_ref"),
        error_code=payload.get("error_code"),
        quality_review_state=ImageQualityReviewState(
            payload.get("quality_review_state", ImageQualityReviewState.NOT_REQUESTED.value)
        ),
        quality_review=_quality_review_or_none(payload.get("quality_review")),
        quality_review_error_code=payload.get("quality_review_error_code"),
        regenerated_run_id=payload.get("regenerated_run_id"),
        retry_of_run_id=payload.get("retry_of_run_id"),
        regeneration_count=payload.get("regeneration_count", 0),
        created_at=datetime.fromisoformat(payload["created_at"]),
        started_at=_datetime_or_none(payload.get("started_at")),
        completed_at=_datetime_or_none(payload.get("completed_at")),
        reviewed_at=_datetime_or_none(payload.get("reviewed_at")),
        output_asset_id=payload.get("output_asset_id"),
        queue_wait_milliseconds=payload.get("queue_wait_milliseconds"),
        provider_delay_milliseconds=payload.get("provider_delay_milliseconds"),
        provider_execution_milliseconds=payload.get("provider_execution_milliseconds"),
    )


def _retry_memory_to_dict(value: ImageRetryMemory | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "root_run_id": value.root_run_id,
        "attempts": [
            {
                "run_id": item.run_id,
                "seed": item.seed,
                "production_prompt": item.production_prompt,
                "output_asset_id": item.output_asset_id,
                "output_checksum_sha256": item.output_checksum_sha256,
                "review_decision": (
                    item.review_decision.value if item.review_decision is not None else None
                ),
                "review_summary": item.review_summary,
                "repair_instructions": list(item.repair_instructions),
                "repair_prompt": item.repair_prompt,
            }
            for item in value.attempts
        ],
    }


def _retry_memory_or_none(value: object) -> ImageRetryMemory | None:
    if not isinstance(value, dict):
        return None
    root_run_id = value.get("root_run_id")
    attempts = value.get("attempts")
    if not isinstance(root_run_id, str) or not isinstance(attempts, list):
        return None
    return ImageRetryMemory(
        root_run_id=root_run_id,
        attempts=tuple(
            ImageRetryAttempt(
                run_id=item["run_id"],
                seed=item.get("seed"),
                production_prompt=item["production_prompt"],
                output_asset_id=item.get("output_asset_id"),
                output_checksum_sha256=item.get("output_checksum_sha256"),
                review_decision=(
                    ImageQualityDecision(item["review_decision"])
                    if item.get("review_decision") is not None
                    else None
                ),
                review_summary=item.get("review_summary"),
                repair_instructions=tuple(item.get("repair_instructions", [])),
                repair_prompt=item.get("repair_prompt"),
            )
            for item in attempts
            if isinstance(item, dict)
        ),
    )


def _quality_review_or_none(value: object) -> ImageQualityReview | None:
    if not isinstance(value, dict):
        return None
    issues = tuple(
        ImageQualityIssue(
            category=item["category"],
            severity=ImageQualityIssueSeverity(item["severity"]),
            description=item["description"],
        )
        for item in value.get("issues", [])
    )
    return ImageQualityReview(
        decision=ImageQualityDecision(value["decision"]),
        summary=value["summary"],
        issues=issues,
        repair_instructions=tuple(value.get("repair_instructions", [])),
        uncertainties=tuple(value.get("uncertainties", [])),
        reviewer_model=value["reviewer_model"],
        reviewer_prompt_version=value["reviewer_prompt_version"],
        reviewer_prompt_hash=value["reviewer_prompt_hash"],
        reviewer_config_hash=value["reviewer_config_hash"],
        review_hash=value["review_hash"],
        repair_prompt=value.get("repair_prompt"),
        repair_prompt_version=value.get("repair_prompt_version"),
        repair_prompt_hash=value.get("repair_prompt_hash"),
    )


def _orchestration_or_none(value: object) -> ImageOrchestrationTrace | None:
    if not isinstance(value, dict):
        return None
    return ImageOrchestrationTrace(
        user_request=value["user_request"],
        capability_id=value["capability_id"],
        summary=value["summary"],
        planner_model=value["planner_model"],
        planner_prompt_version=value["planner_prompt_version"],
        planner_prompt_hash=value["planner_prompt_hash"],
        planner_config_hash=value["planner_config_hash"],
        plan_hash=value["plan_hash"],
    )


def _datetime_or_none(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


__all__ = ["run_from_dict", "run_to_dict"]
