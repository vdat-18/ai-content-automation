"""JSON serialization for durable Media Lab planning jobs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from ..domain.models import (
    ImageOrchestrationPlan,
    ImageOrchestrationTrace,
    ImagePlanningState,
    ImageReferencePlan,
    ImageReferenceRole,
)
from ..domain.planning_jobs import PlanningJob, PlanningJobKind, PlanningJobState
from ..domain.video_models import (
    VideoOrchestrationPlan,
    VideoOrchestrationTrace,
    VideoPlanningState,
    VideoSourcePlan,
    VideoSourceRole,
    VideoSourceUsage,
    VideoVerificationStage,
    VideoVerificationStagePlan,
)


def planning_job_to_dict(job: PlanningJob) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "job_id": job.job_id,
        "source_run_id": job.source_run_id,
        "input_hash": job.input_hash,
        "kind": job.kind.value,
        "user_request": job.user_request,
        "source_asset_ids": list(job.source_asset_ids),
        "state": job.state.value,
        "plan": _json_value(asdict(job.plan)) if job.plan is not None else None,
        "error_code": job.error_code,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def planning_job_from_dict(payload: dict[str, Any]) -> PlanningJob:
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported Media Lab planning job schema version")
    kind = PlanningJobKind(payload["kind"])
    raw_plan = payload.get("plan")
    return PlanningJob(
        job_id=payload["job_id"],
        source_run_id=payload["source_run_id"],
        input_hash=payload["input_hash"],
        kind=kind,
        user_request=payload["user_request"],
        source_asset_ids=tuple(payload.get("source_asset_ids", [])),
        state=PlanningJobState(payload["state"]),
        plan=_image_plan(raw_plan)
        if kind == PlanningJobKind.IMAGE and raw_plan
        else (_video_plan(raw_plan) if raw_plan else None),
        error_code=payload.get("error_code"),
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _image_plan(value: dict[str, Any]) -> ImageOrchestrationPlan:
    trace = value["trace"]
    return ImageOrchestrationPlan(
        state=ImagePlanningState(value["state"]),
        summary=value["summary"],
        questions=tuple(value["questions"]),
        uncertainties=tuple(value["uncertainties"]),
        capability_id=value.get("capability_id"),
        production_prompt=value.get("production_prompt"),
        references=tuple(
            ImageReferencePlan(
                source_index=item["source_index"],
                role=ImageReferenceRole(item["role"]),
                priority=item["priority"],
                must_preserve=tuple(item["must_preserve"]),
                allowed_changes=tuple(item["allowed_changes"]),
                identity_group=item.get("identity_group"),
            )
            for item in value["references"]
        ),
        trace=ImageOrchestrationTrace(**trace),
    )


def _video_plan(value: dict[str, Any]) -> VideoOrchestrationPlan:
    trace = value["trace"]
    return VideoOrchestrationPlan(
        state=VideoPlanningState(value["state"]),
        summary=value["summary"],
        questions=tuple(value["questions"]),
        uncertainties=tuple(value["uncertainties"]),
        capability_id=value.get("capability_id"),
        production_prompt=value.get("production_prompt"),
        sources=tuple(
            VideoSourcePlan(
                source_index=item["source_index"],
                role=VideoSourceRole(item["role"]),
                usage=VideoSourceUsage(item["usage"]),
                priority=item["priority"],
                must_preserve=tuple(item["must_preserve"]),
                allowed_changes=tuple(item["allowed_changes"]),
                identity_group=item.get("identity_group"),
                is_primary_identity=item.get("is_primary_identity", False),
            )
            for item in value["sources"]
        ),
        verification_plan=tuple(
            VideoVerificationStagePlan(
                stage=VideoVerificationStage(item["stage"]), reason=item["reason"]
            )
            for item in value["verification_plan"]
        ),
        trace=VideoOrchestrationTrace(**trace),
    )


__all__ = ["planning_job_from_dict", "planning_job_to_dict"]
