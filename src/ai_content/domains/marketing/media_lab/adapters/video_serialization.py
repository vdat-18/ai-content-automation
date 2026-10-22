"""Serialization for persisted Media Lab video runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.video_models import (
    VideoGenerationState,
    VideoIntent,
    VideoOrchestrationTrace,
    VideoOutputFormat,
    VideoOutputSpec,
    VideoQualityDecision,
    VideoQualityIssue,
    VideoQualityIssueSeverity,
    VideoQualityReview,
    VideoQualityReviewState,
    VideoRetryAttempt,
    VideoRetryMemory,
    VideoReviewFrame,
    VideoReviewState,
    VideoRun,
    VideoSource,
    VideoSourceOrigin,
    VideoSourceRole,
    VideoSourceUsage,
    VideoVerificationObservation,
    VideoVerificationReport,
    VideoVerificationStage,
    VideoVerificationStagePlan,
    VideoVerificationStageResult,
    VideoVerificationState,
    VideoVerificationStatus,
)


def video_run_to_dict(run: VideoRun) -> dict[str, Any]:
    return {
        "schema_version": 9,
        "run_id": run.run_id,
        "intent": run.intent.value,
        "prompt": run.prompt,
        "rendered_prompt": run.rendered_prompt,
        "sources": [
            {
                "source_id": item.source_id,
                "source_index": item.source_index,
                "role": item.role.value,
                "usage": item.usage.value,
                "priority": item.priority,
                "must_preserve": list(item.must_preserve),
                "allowed_changes": list(item.allowed_changes),
                "source_origin": item.source_origin.value,
                "source_checksum_sha256": item.source_checksum_sha256,
                "artifact_ref": item.artifact_ref,
                "content_type": item.content_type,
                "source_run_id": item.source_run_id,
                "identity_group": item.identity_group,
                "is_primary_identity": item.is_primary_identity,
                "asset_id": item.asset_id,
            }
            for item in run.sources
        ],
        "verification_plan": [
            {"stage": item.stage.value, "reason": item.reason} for item in run.verification_plan
        ],
        "verification_state": run.verification_state.value,
        "verification": _verification_report_to_dict(run.verification),
        "verification_frames": [
            {
                "label": frame.label,
                "timestamp_milliseconds": frame.timestamp_milliseconds,
                "artifact_ref": frame.artifact_ref,
                "checksum_sha256": frame.checksum_sha256,
            }
            for frame in run.verification_frames
        ],
        "verification_error_code": run.verification_error_code,
        "output_spec": {
            "duration_seconds": run.output_spec.duration_seconds,
            "candidate_count": run.output_spec.candidate_count,
            "preset_id": run.output_spec.preset_id,
            "aspect_ratio": run.output_spec.aspect_ratio,
            "megapixels": run.output_spec.megapixels,
            "output_format": run.output_spec.output_format.value,
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
        "orchestration": _orchestration_to_dict(run.orchestration),
        "output_ref": run.output_ref,
        "output_asset_id": run.output_asset_id,
        "output_checksum_sha256": run.output_checksum_sha256,
        "output_content_type": run.output_content_type,
        "manifest_ref": run.manifest_ref,
        "error_code": run.error_code,
        "quality_review_state": run.quality_review_state.value,
        "quality_review": _quality_review_to_dict(run.quality_review),
        "quality_review_error_code": run.quality_review_error_code,
        "regenerated_run_id": run.regenerated_run_id,
        "retry_of_run_id": run.retry_of_run_id,
        "regeneration_count": run.regeneration_count,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "reviewed_at": run.reviewed_at.isoformat() if run.reviewed_at else None,
        "actual_width": run.actual_width,
        "actual_height": run.actual_height,
        "actual_duration_milliseconds": run.actual_duration_milliseconds,
        "retry_memory": _retry_memory_to_dict(run.retry_memory),
    }


def video_run_from_dict(payload: dict[str, Any]) -> VideoRun:
    schema_version = payload.get("schema_version")
    if schema_version not in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
        raise ValueError("Unsupported Media Lab video run schema version")
    sources = (
        tuple(_source_from_dict(item) for item in payload.get("sources", []))
        if schema_version in {5, 6, 7, 8, 9}
        else _legacy_sources(payload)
    )
    verification_plan = tuple(
        VideoVerificationStagePlan(
            stage=VideoVerificationStage(item["stage"]),
            reason=item["reason"],
        )
        for item in payload.get("verification_plan", [])
    )
    if not verification_plan:
        verification_plan = (
            VideoVerificationStagePlan(
                stage=VideoVerificationStage.TEMPORAL_QUALITY,
                reason="Migrated legacy video quality verification.",
            ),
        )
    quality_review = _quality_review_or_none(payload.get("quality_review"))
    verification = _verification_report_from_dict(payload.get("verification"))
    if verification is None and quality_review is not None:
        verification = quality_review.verification
    verification_frames = _review_frames_from_dict(payload.get("verification_frames"))
    if not verification_frames and quality_review is not None:
        verification_frames = quality_review.sampled_frames
    verification_state = VideoVerificationState(
        payload.get(
            "verification_state",
            (
                VideoVerificationState.VERIFIED.value
                if verification is not None
                else VideoVerificationState.NOT_REQUESTED.value
            ),
        )
    )
    output_spec = payload["output_spec"]
    intent_value = payload["intent"]
    if intent_value == "animate_from_image":
        intent_value = VideoIntent.CREATE_FROM_IMAGES.value
    return VideoRun(
        run_id=payload["run_id"],
        intent=VideoIntent(intent_value),
        prompt=payload["prompt"],
        rendered_prompt=payload["rendered_prompt"],
        sources=sources,
        verification_plan=verification_plan,
        verification_state=verification_state,
        verification=verification,
        verification_frames=verification_frames,
        verification_error_code=payload.get("verification_error_code"),
        output_spec=VideoOutputSpec(
            duration_seconds=output_spec["duration_seconds"],
            candidate_count=output_spec["candidate_count"],
            preset_id=output_spec.get("preset_id"),
            aspect_ratio=output_spec.get("aspect_ratio"),
            megapixels=output_spec.get("megapixels"),
            output_format=VideoOutputFormat(
                output_spec.get("output_format", VideoOutputFormat.MP4.value)
            ),
        ),
        seed=payload.get("seed"),
        generation_state=VideoGenerationState(payload["generation_state"]),
        review_state=VideoReviewState(payload["review_state"]),
        model=payload.get("model"),
        checkpoint_observation=payload.get("checkpoint_observation"),
        graph_template_hash=payload.get("graph_template_hash"),
        backend_run_id=payload.get("backend_run_id"),
        provider_job_id=payload.get("provider_job_id"),
        orchestration=_orchestration_or_none(payload.get("orchestration")),
        output_ref=payload.get("output_ref"),
        output_checksum_sha256=payload.get("output_checksum_sha256"),
        output_content_type=payload.get("output_content_type"),
        manifest_ref=payload.get("manifest_ref"),
        error_code=payload.get("error_code"),
        quality_review_state=VideoQualityReviewState(
            payload.get("quality_review_state", VideoQualityReviewState.NOT_REQUESTED.value)
        ),
        quality_review=quality_review,
        quality_review_error_code=payload.get("quality_review_error_code"),
        regenerated_run_id=payload.get("regenerated_run_id"),
        retry_of_run_id=payload.get("retry_of_run_id"),
        regeneration_count=payload.get("regeneration_count", 0),
        created_at=datetime.fromisoformat(payload["created_at"]),
        started_at=_datetime_or_none(payload.get("started_at")),
        completed_at=_datetime_or_none(payload.get("completed_at")),
        reviewed_at=_datetime_or_none(payload.get("reviewed_at")),
        output_asset_id=payload.get("output_asset_id"),
        actual_width=payload.get("actual_width"),
        actual_height=payload.get("actual_height"),
        actual_duration_milliseconds=payload.get("actual_duration_milliseconds"),
        retry_memory=_retry_memory_or_none(payload.get("retry_memory")),
        queue_wait_milliseconds=payload.get("queue_wait_milliseconds"),
        provider_delay_milliseconds=payload.get("provider_delay_milliseconds"),
        provider_execution_milliseconds=payload.get("provider_execution_milliseconds"),
    )


def _retry_memory_to_dict(value: VideoRetryMemory | None) -> dict[str, Any] | None:
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
                "duration_seconds": item.duration_seconds,
                "output_preset_id": item.output_preset_id,
                "review_decision": (
                    item.review_decision.value if item.review_decision is not None else None
                ),
                "review_summary": item.review_summary,
                "repair_instructions": list(item.repair_instructions),
                "repair_prompt": item.repair_prompt,
                "verifier_status": (
                    item.verifier_status.value if item.verifier_status is not None else None
                ),
                "suspicious_timestamps_milliseconds": list(item.suspicious_timestamps_milliseconds),
            }
            for item in value.attempts
        ],
    }


def _retry_memory_or_none(value: object) -> VideoRetryMemory | None:
    if not isinstance(value, dict):
        return None
    root_run_id = value.get("root_run_id")
    attempts = value.get("attempts")
    if not isinstance(root_run_id, str) or not isinstance(attempts, list):
        return None
    return VideoRetryMemory(
        root_run_id=root_run_id,
        attempts=tuple(
            VideoRetryAttempt(
                run_id=item["run_id"],
                seed=item.get("seed"),
                production_prompt=item["production_prompt"],
                output_asset_id=item.get("output_asset_id"),
                output_checksum_sha256=item.get("output_checksum_sha256"),
                duration_seconds=item["duration_seconds"],
                output_preset_id=item.get("output_preset_id"),
                review_decision=(
                    VideoQualityDecision(item["review_decision"])
                    if item.get("review_decision") is not None
                    else None
                ),
                review_summary=item.get("review_summary"),
                repair_instructions=tuple(item.get("repair_instructions", [])),
                repair_prompt=item.get("repair_prompt"),
                verifier_status=(
                    VideoVerificationStatus(item["verifier_status"])
                    if item.get("verifier_status") is not None
                    else None
                ),
                suspicious_timestamps_milliseconds=tuple(
                    item.get("suspicious_timestamps_milliseconds", [])
                ),
            )
            for item in attempts
            if isinstance(item, dict)
        ),
    )


def _review_frames_from_dict(value: object) -> tuple[VideoReviewFrame, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        VideoReviewFrame(
            label=item["label"],
            timestamp_milliseconds=item["timestamp_milliseconds"],
            artifact_ref=item["artifact_ref"],
            checksum_sha256=item["checksum_sha256"],
        )
        for item in value
        if isinstance(item, dict)
    )


def _quality_review_to_dict(value: VideoQualityReview | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "decision": value.decision.value,
        "summary": value.summary,
        "issues": [
            {
                "category": issue.category,
                "severity": issue.severity.value,
                "description": issue.description,
            }
            for issue in value.issues
        ],
        "repair_instructions": list(value.repair_instructions),
        "uncertainties": list(value.uncertainties),
        "reviewer_model": value.reviewer_model,
        "reviewer_prompt_version": value.reviewer_prompt_version,
        "reviewer_prompt_hash": value.reviewer_prompt_hash,
        "reviewer_config_hash": value.reviewer_config_hash,
        "review_hash": value.review_hash,
        "sampled_frames": [
            {
                "label": frame.label,
                "timestamp_milliseconds": frame.timestamp_milliseconds,
                "artifact_ref": frame.artifact_ref,
                "checksum_sha256": frame.checksum_sha256,
            }
            for frame in value.sampled_frames
        ],
        "temporal_sampling_rate_fps": value.temporal_sampling_rate_fps,
        "temporal_duration_milliseconds": value.temporal_duration_milliseconds,
        "repair_prompt": value.repair_prompt,
        "repair_prompt_version": value.repair_prompt_version,
        "repair_prompt_hash": value.repair_prompt_hash,
        "verification": _verification_report_to_dict(value.verification),
    }


def _quality_review_or_none(value: object) -> VideoQualityReview | None:
    if not isinstance(value, dict):
        return None
    issues = tuple(
        VideoQualityIssue(
            category=item["category"],
            severity=VideoQualityIssueSeverity(item["severity"]),
            description=item["description"],
        )
        for item in value.get("issues", [])
    )
    frames = tuple(
        VideoReviewFrame(
            label=item["label"],
            timestamp_milliseconds=item["timestamp_milliseconds"],
            artifact_ref=item["artifact_ref"],
            checksum_sha256=item["checksum_sha256"],
        )
        for item in value.get("sampled_frames", [])
    )
    return VideoQualityReview(
        decision=VideoQualityDecision(value["decision"]),
        summary=value["summary"],
        issues=issues,
        repair_instructions=tuple(value.get("repair_instructions", [])),
        uncertainties=tuple(value.get("uncertainties", [])),
        reviewer_model=value["reviewer_model"],
        reviewer_prompt_version=value["reviewer_prompt_version"],
        reviewer_prompt_hash=value["reviewer_prompt_hash"],
        reviewer_config_hash=value["reviewer_config_hash"],
        review_hash=value["review_hash"],
        sampled_frames=frames,
        temporal_sampling_rate_fps=value.get("temporal_sampling_rate_fps"),
        temporal_duration_milliseconds=value.get("temporal_duration_milliseconds"),
        repair_prompt=value.get("repair_prompt"),
        repair_prompt_version=value.get("repair_prompt_version"),
        repair_prompt_hash=value.get("repair_prompt_hash"),
        verification=_verification_report_from_dict(value.get("verification")),
    )


def _verification_report_to_dict(value: VideoVerificationReport | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "status": value.status.value,
        "verifier_version": value.verifier_version,
        "config_hash": value.config_hash,
        "request_hash": value.request_hash,
        "stages": [
            {
                "stage": stage.stage.value,
                "status": stage.status.value,
                "model": stage.model,
                "model_version": stage.model_version,
                "metadata": dict(stage.metadata),
                "observations": [
                    {
                        "observation_id": observation.observation_id,
                        "stage": observation.stage.value,
                        "category": observation.category,
                        "status": observation.status.value,
                        "severity": observation.severity.value,
                        "description": observation.description,
                        "confidence": observation.confidence,
                        "start_timestamp_milliseconds": observation.start_timestamp_milliseconds,
                        "end_timestamp_milliseconds": observation.end_timestamp_milliseconds,
                        "evidence_refs": list(observation.evidence_refs),
                    }
                    for observation in stage.observations
                ],
            }
            for stage in value.stages
        ],
        "suspicious_timestamps_milliseconds": list(value.suspicious_timestamps_milliseconds),
        "uncertainties": list(value.uncertainties),
        "report_hash": value.report_hash,
    }


def _verification_report_from_dict(value: object) -> VideoVerificationReport | None:
    if not isinstance(value, dict):
        return None
    stages = tuple(
        VideoVerificationStageResult(
            stage=VideoVerificationStage(item["stage"]),
            status=VideoVerificationStatus(item["status"]),
            model=item["model"],
            model_version=item["model_version"],
            metadata=tuple(
                (str(key), str(item_value)) for key, item_value in item.get("metadata", {}).items()
            ),
            observations=tuple(
                VideoVerificationObservation(
                    observation_id=observation["observation_id"],
                    stage=VideoVerificationStage(observation["stage"]),
                    category=observation["category"],
                    status=VideoVerificationStatus(observation["status"]),
                    severity=VideoQualityIssueSeverity(observation["severity"]),
                    description=observation["description"],
                    confidence=observation.get("confidence"),
                    start_timestamp_milliseconds=observation.get("start_timestamp_milliseconds"),
                    end_timestamp_milliseconds=observation.get("end_timestamp_milliseconds"),
                    evidence_refs=tuple(observation.get("evidence_refs", [])),
                )
                for observation in item.get("observations", [])
            ),
        )
        for item in value.get("stages", [])
    )
    return VideoVerificationReport(
        status=VideoVerificationStatus(value["status"]),
        verifier_version=value["verifier_version"],
        config_hash=value["config_hash"],
        request_hash=value.get("request_hash", "0" * 64),
        stages=stages,
        suspicious_timestamps_milliseconds=tuple(
            value.get("suspicious_timestamps_milliseconds", [])
        ),
        uncertainties=tuple(value.get("uncertainties", [])),
        report_hash=value.get("report_hash", ""),
    )


def _orchestration_to_dict(value: VideoOrchestrationTrace | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "user_request": value.user_request,
        "capability_id": value.capability_id,
        "summary": value.summary,
        "planner_model": value.planner_model,
        "planner_prompt_version": value.planner_prompt_version,
        "planner_prompt_hash": value.planner_prompt_hash,
        "planner_config_hash": value.planner_config_hash,
        "plan_hash": value.plan_hash,
    }


def _orchestration_or_none(value: object) -> VideoOrchestrationTrace | None:
    if not isinstance(value, dict):
        return None
    return VideoOrchestrationTrace(
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


def _source_from_dict(payload: dict[str, Any]) -> VideoSource:
    return VideoSource(
        source_id=payload["source_id"],
        source_index=payload["source_index"],
        role=VideoSourceRole(payload["role"]),
        usage=VideoSourceUsage(payload["usage"]),
        priority=payload["priority"],
        must_preserve=tuple(payload["must_preserve"]),
        allowed_changes=tuple(payload.get("allowed_changes", [])),
        source_origin=VideoSourceOrigin(payload["source_origin"]),
        source_checksum_sha256=payload["source_checksum_sha256"],
        artifact_ref=payload["artifact_ref"],
        content_type=payload["content_type"],
        source_run_id=payload.get("source_run_id"),
        identity_group=payload.get("identity_group"),
        is_primary_identity=bool(payload.get("is_primary_identity", False)),
        asset_id=payload.get("asset_id"),
    )


def _legacy_sources(payload: dict[str, Any]) -> tuple[VideoSource, ...]:
    sources: list[VideoSource] = []
    for item in payload.get("references", []):
        sources.append(
            VideoSource(
                source_id=item["reference_id"],
                source_index=len(sources),
                role=VideoSourceRole.KEYFRAME,
                usage=VideoSourceUsage.GENERATION,
                priority=item["priority"],
                must_preserve=tuple(item["must_preserve"]),
                allowed_changes=tuple(item["allowed_changes"]),
                source_origin=VideoSourceOrigin(item["source_origin"]),
                source_checksum_sha256=item["source_checksum_sha256"],
                artifact_ref=item["artifact_ref"],
                content_type=item["content_type"],
                source_run_id=item.get("source_run_id"),
                identity_group=None,
                is_primary_identity=False,
            )
        )
    for item in payload.get("verification_sources", []):
        sources.append(
            VideoSource(
                source_id=item["source_id"],
                source_index=len(sources),
                role=VideoSourceRole.PRODUCT,
                usage=VideoSourceUsage.VERIFICATION,
                priority=item["priority"],
                must_preserve=tuple(item["must_preserve"]),
                allowed_changes=(),
                source_origin=VideoSourceOrigin(
                    item.get("source_origin", VideoSourceOrigin.UPLOAD.value)
                ),
                source_checksum_sha256=item["checksum_sha256"],
                artifact_ref=item["artifact_ref"],
                content_type=item["content_type"],
                source_run_id=item.get("source_run_id"),
                identity_group="legacy-product",
                is_primary_identity=True,
            )
        )
    return tuple(sources)


__all__ = ["video_run_from_dict", "video_run_to_dict"]
