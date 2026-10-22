"""Serialization for persisted Media Lab final-video projects."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.video_projects import VideoProject, VideoProjectShot, VideoProjectState


def video_project_to_dict(project: VideoProject) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project.project_id,
        "source_run_id": project.source_run_id,
        "input_hash": project.input_hash,
        "shots": [
            {
                "shot_id": shot.shot_id,
                "source_run_id": shot.source_run_id,
                "trim_start_seconds": shot.trim_start_seconds,
                "trim_end_seconds": shot.trim_end_seconds,
            }
            for shot in project.shots
        ],
        "target_duration_seconds": project.target_duration_seconds,
        "state": project.state.value,
        "source_asset_ids": list(project.source_asset_ids),
        "output_asset_id": project.output_asset_id,
        "output_checksum_sha256": project.output_checksum_sha256,
        "actual_width": project.actual_width,
        "actual_height": project.actual_height,
        "actual_duration_milliseconds": project.actual_duration_milliseconds,
        "error_code": project.error_code,
        "created_at": project.created_at.isoformat(),
        "completed_at": project.completed_at.isoformat() if project.completed_at else None,
        "reviewed_at": project.reviewed_at.isoformat() if project.reviewed_at else None,
    }


def video_project_from_dict(payload: dict[str, Any]) -> VideoProject:
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported Media Lab video project schema version")
    return VideoProject(
        project_id=payload["project_id"],
        source_run_id=payload["source_run_id"],
        input_hash=payload["input_hash"],
        shots=tuple(
            VideoProjectShot(
                shot_id=item["shot_id"],
                source_run_id=item["source_run_id"],
                trim_start_seconds=item["trim_start_seconds"],
                trim_end_seconds=item["trim_end_seconds"],
            )
            for item in payload["shots"]
        ),
        target_duration_seconds=payload["target_duration_seconds"],
        state=VideoProjectState(payload["state"]),
        source_asset_ids=tuple(payload.get("source_asset_ids", [])),
        output_asset_id=payload.get("output_asset_id"),
        output_checksum_sha256=payload.get("output_checksum_sha256"),
        actual_width=payload.get("actual_width"),
        actual_height=payload.get("actual_height"),
        actual_duration_milliseconds=payload.get("actual_duration_milliseconds"),
        error_code=payload.get("error_code"),
        created_at=datetime.fromisoformat(payload["created_at"]),
        completed_at=_datetime_or_none(payload.get("completed_at")),
        reviewed_at=_datetime_or_none(payload.get("reviewed_at")),
    )


def _datetime_or_none(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


__all__ = ["video_project_from_dict", "video_project_to_dict"]
