"""Serialization for autonomous final Video Ad jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.video_ads import (
    VideoAdBrief,
    VideoAdCandidate,
    VideoAdJob,
    VideoAdJobState,
    VideoAdShotPlan,
    VideoAdTimelinePlan,
    VideoUsableSegment,
)
from ..domain.video_models import (
    VideoIntent,
    VideoSourcePlan,
    VideoSourceRole,
    VideoSourceUsage,
)


def video_ad_job_to_dict(job: VideoAdJob) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "job_id": job.job_id,
        "source_run_id": job.source_run_id,
        "input_hash": job.input_hash,
        "brief": {
            "user_request": job.brief.user_request,
            "brand": job.brief.brand,
            "sku": job.brief.sku,
            "angle": job.brief.angle,
            "source_asset_ids": list(job.brief.source_asset_ids),
            "target_duration_seconds": job.brief.target_duration_seconds,
            "aspect_ratio": job.brief.aspect_ratio,
            "candidate_count": job.brief.candidate_count,
            "cta_text": job.brief.cta_text,
            "logo_asset_id": job.brief.logo_asset_id,
        },
        "state": job.state.value,
        "plan": _plan_to_dict(job.plan) if job.plan else None,
        "candidates": [
            {
                "shot_id": item.shot_id,
                "candidate_index": item.candidate_index,
                "run_id": item.run_id,
                "seed": item.seed,
            }
            for item in job.candidates
        ],
        "selected_segments": [
            {
                "shot_id": item.shot_id,
                "candidate_index": item.candidate_index,
                "run_id": item.run_id,
                "trim_start_seconds": item.trim_start_seconds,
                "trim_end_seconds": item.trim_end_seconds,
                "score": item.score,
                "observations": list(item.observations),
            }
            for item in job.selected_segments
        ],
        "output_asset_id": job.output_asset_id,
        "output_checksum_sha256": job.output_checksum_sha256,
        "actual_width": job.actual_width,
        "actual_height": job.actual_height,
        "actual_duration_milliseconds": job.actual_duration_milliseconds,
        "error_code": job.error_code,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def video_ad_job_from_dict(payload: dict[str, Any]) -> VideoAdJob:
    schema_version = payload.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError("Unsupported Media Lab video Ad schema version")
    brief = payload["brief"]
    return VideoAdJob(
        job_id=payload["job_id"],
        source_run_id=payload["source_run_id"],
        input_hash=payload["input_hash"],
        brief=VideoAdBrief(
            user_request=brief["user_request"],
            brand=brief["brand"],
            sku=brief["sku"],
            angle=brief["angle"],
            source_asset_ids=tuple(brief.get("source_asset_ids", [])),
            target_duration_seconds=brief["target_duration_seconds"],
            aspect_ratio=brief["aspect_ratio"],
            candidate_count=brief["candidate_count"],
            cta_text=brief.get("cta_text"),
            logo_asset_id=brief.get("logo_asset_id"),
        ),
        state=VideoAdJobState(payload["state"]),
        plan=(
            _plan_from_dict(
                payload["plan"],
                legacy_source_count=(
                    len(brief.get("source_asset_ids", [])) if schema_version == 1 else None
                ),
            )
            if payload.get("plan")
            else None
        ),
        candidates=tuple(VideoAdCandidate(**item) for item in payload.get("candidates", [])),
        selected_segments=tuple(
            VideoUsableSegment(
                shot_id=item["shot_id"],
                candidate_index=item["candidate_index"],
                run_id=item["run_id"],
                trim_start_seconds=item["trim_start_seconds"],
                trim_end_seconds=item["trim_end_seconds"],
                score=item["score"],
                observations=tuple(item.get("observations", [])),
            )
            for item in payload.get("selected_segments", [])
        ),
        output_asset_id=payload.get("output_asset_id"),
        output_checksum_sha256=payload.get("output_checksum_sha256"),
        actual_width=payload.get("actual_width"),
        actual_height=payload.get("actual_height"),
        actual_duration_milliseconds=payload.get("actual_duration_milliseconds"),
        error_code=payload.get("error_code"),
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        completed_at=(
            datetime.fromisoformat(payload["completed_at"]) if payload.get("completed_at") else None
        ),
    )


def _plan_to_dict(plan: VideoAdTimelinePlan) -> dict[str, Any]:
    return {
        "summary": plan.summary,
        "questions": list(plan.questions),
        "uncertainties": list(plan.uncertainties),
        "target_duration_seconds": plan.target_duration_seconds,
        "aspect_ratio": plan.aspect_ratio,
        "sources": [
            {
                "source_index": source.source_index,
                "role": source.role.value,
                "usage": source.usage.value,
                "priority": source.priority,
                "must_preserve": list(source.must_preserve),
                "allowed_changes": list(source.allowed_changes),
                "identity_group": source.identity_group,
                "is_primary_identity": source.is_primary_identity,
            }
            for source in plan.sources
        ],
        "shots": [
            {
                "shot_id": shot.shot_id,
                "purpose": shot.purpose,
                "prompt": shot.prompt,
                "intent": shot.intent.value,
                "source_indexes": list(shot.source_indexes),
                "generation_duration_seconds": shot.generation_duration_seconds,
                "usable_duration_seconds": shot.usable_duration_seconds,
                "on_screen_text": shot.on_screen_text,
            }
            for shot in plan.shots
        ],
        "planner_model": plan.planner_model,
        "planner_prompt_version": plan.planner_prompt_version,
        "planner_prompt_hash": plan.planner_prompt_hash,
        "planner_config_hash": plan.planner_config_hash,
        "plan_hash": plan.plan_hash,
    }


def _plan_from_dict(
    payload: dict[str, Any], *, legacy_source_count: int | None = None
) -> VideoAdTimelinePlan:
    sources = tuple(
        VideoSourcePlan(
            source_index=item["source_index"],
            role=VideoSourceRole(item["role"]),
            usage=VideoSourceUsage(item["usage"]),
            priority=item["priority"],
            must_preserve=tuple(item.get("must_preserve", [])),
            allowed_changes=tuple(item.get("allowed_changes", [])),
            identity_group=item.get("identity_group"),
            is_primary_identity=item.get("is_primary_identity", False),
        )
        for item in payload.get("sources", [])
    )
    if legacy_source_count is not None and not sources:
        sources = tuple(
            VideoSourcePlan(
                source_index=index,
                role=VideoSourceRole.PRODUCT,
                usage=VideoSourceUsage.GENERATION,
                priority=max(1, 100 - index),
                must_preserve=("visible product identity and geometry",),
                allowed_changes=("camera motion", "lighting", "background"),
                identity_group=f"product-{index}",
            )
            for index in range(legacy_source_count)
        )
    return VideoAdTimelinePlan(
        summary=payload["summary"],
        questions=tuple(payload.get("questions", [])),
        uncertainties=tuple(payload.get("uncertainties", [])),
        target_duration_seconds=payload["target_duration_seconds"],
        aspect_ratio=payload["aspect_ratio"],
        sources=sources,
        shots=tuple(
            VideoAdShotPlan(
                shot_id=item["shot_id"],
                purpose=item["purpose"],
                prompt=item["prompt"],
                intent=VideoIntent(item["intent"]),
                source_indexes=tuple(item.get("source_indexes", [])),
                generation_duration_seconds=item["generation_duration_seconds"],
                usable_duration_seconds=item["usable_duration_seconds"],
                on_screen_text=item.get("on_screen_text"),
            )
            for item in payload["shots"]
        ),
        planner_model=payload["planner_model"],
        planner_prompt_version=payload["planner_prompt_version"],
        planner_prompt_hash=payload["planner_prompt_hash"],
        planner_config_hash=payload["planner_config_hash"],
        plan_hash=payload["plan_hash"],
    )


__all__ = ["video_ad_job_from_dict", "video_ad_job_to_dict"]
