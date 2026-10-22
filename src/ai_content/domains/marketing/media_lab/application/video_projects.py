"""Assemble completed MiniMax H3 runs into one final Ads Media Asset."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from ..domain.video_models import VideoGenerationState
from ..domain.video_projects import (
    CreateVideoProjectCommand,
    VideoProject,
    VideoProjectState,
)
from ..ports.assets import IGeneratedMediaAssetWriter, MediaAssetError
from ..ports.video_interfaces import MediaLabVideoError
from ..ports.video_projects import (
    IVideoCompositor,
    IVideoProjectRepository,
    IVideoRunSource,
    MediaLabVideoProjectError,
    VideoCompositionError,
    VideoCompositionRequest,
    VideoCompositionShot,
)

_MIN_PROJECT_SECONDS = 20.0
_MAX_PROJECT_SECONDS = 25.0
_MAX_PROJECT_SHOTS = 8
_DURATION_TOLERANCE_SECONDS = 0.01
_SOURCE_END_TOLERANCE_SECONDS = 0.1


class MediaLabVideoProjectService:
    def __init__(
        self,
        repository: IVideoProjectRepository,
        video_runs: IVideoRunSource,
        compositor: IVideoCompositor,
        media_assets: IGeneratedMediaAssetWriter,
    ) -> None:
        self._repository = repository
        self._video_runs = video_runs
        self._compositor = compositor
        self._media_assets = media_assets

    def close(self) -> None:
        self._repository.close()

    async def create(self, command: CreateVideoProjectCommand) -> VideoProject:
        input_hash = _command_hash(command)
        existing = await self._repository.get_by_source_run_id(command.source_run_id)
        if existing is not None:
            if existing.input_hash != input_hash:
                raise MediaLabVideoProjectError(
                    "Video project source_run_id was already used with different input",
                    status_code=409,
                    code="input_drift",
                )
            return existing

        _validate_command(command)
        composition_shots: list[VideoCompositionShot] = []
        source_asset_ids: list[str] = []
        dimensions: tuple[int, int] | None = None
        for shot in command.shots:
            try:
                run = await self._video_runs.get(shot.source_run_id)
            except MediaLabVideoError as error:
                raise MediaLabVideoProjectError(
                    "A source Media Lab video run is unavailable",
                    status_code=error.status_code,
                    code=error.code,
                ) from error
            if (
                run.generation_state != VideoGenerationState.SUCCEEDED
                or run.output_asset_id is None
                or run.output_checksum_sha256 is None
                or run.actual_width is None
                or run.actual_height is None
                or run.actual_duration_milliseconds is None
            ):
                raise MediaLabVideoProjectError(
                    "Every project shot must reference a completed Media Lab video output",
                    status_code=409,
                    code="source_run_not_ready",
                )
            source_duration = run.actual_duration_milliseconds / 1000
            if shot.trim_end_seconds > source_duration + _SOURCE_END_TOLERANCE_SECONDS:
                raise MediaLabVideoProjectError(
                    "A shot trim window exceeds its source video duration",
                    code="invalid_trim_window",
                )
            run_dimensions = (run.actual_width, run.actual_height)
            if dimensions is None:
                dimensions = run_dimensions
            elif dimensions != run_dimensions:
                raise MediaLabVideoProjectError(
                    "All source videos must use the same output dimensions",
                    code="source_dimensions_mismatch",
                )
            try:
                path, content_type = await self._video_runs.output_file(shot.source_run_id)
            except MediaLabVideoError as error:
                raise MediaLabVideoProjectError(
                    "A source Media Lab video output is unavailable",
                    status_code=error.status_code,
                    code=error.code,
                ) from error
            if content_type != "video/mp4":
                raise MediaLabVideoProjectError(
                    "Final video assembly currently requires MP4 source runs",
                    code="unsupported_source_format",
                )
            composition_shots.append(
                VideoCompositionShot(
                    shot_id=shot.shot_id,
                    source_path=path,
                    trim_start_seconds=shot.trim_start_seconds,
                    trim_end_seconds=shot.trim_end_seconds,
                )
            )
            source_asset_ids.append(run.output_asset_id)

        assert dimensions is not None
        now = datetime.now(UTC)
        project = VideoProject(
            project_id=uuid4().hex,
            source_run_id=command.source_run_id,
            input_hash=input_hash,
            shots=command.shots,
            target_duration_seconds=command.target_duration_seconds,
            state=VideoProjectState.ASSEMBLING,
            source_asset_ids=tuple(dict.fromkeys(source_asset_ids)),
            output_asset_id=None,
            output_checksum_sha256=None,
            actual_width=None,
            actual_height=None,
            actual_duration_milliseconds=None,
            error_code=None,
            created_at=now,
        )
        await self._repository.save(project)
        try:
            result = await asyncio.to_thread(
                self._compositor.compose,
                VideoCompositionRequest(
                    project_id=project.project_id,
                    shots=tuple(composition_shots),
                    target_duration_seconds=project.target_duration_seconds,
                    width=dimensions[0],
                    height=dimensions[1],
                ),
            )
            content = await asyncio.to_thread(result.output_path.read_bytes)
            output_asset = await self._media_assets.register_generated_video(
                content,
                source_run_id=project.project_id,
                parent_asset_ids=project.source_asset_ids,
            )
        except (MediaAssetError, VideoCompositionError) as error:
            error_code = error.code
            failed = replace(
                project,
                state=VideoProjectState.FAILED,
                error_code=error_code,
                completed_at=datetime.now(UTC),
            )
            await self._repository.save(failed)
            raise MediaLabVideoProjectError(str(error), status_code=422, code=error_code) from error

        completed = replace(
            project,
            state=VideoProjectState.AWAITING_HUMAN_REVIEW,
            output_asset_id=output_asset.asset_id,
            output_checksum_sha256=output_asset.checksum_sha256,
            actual_width=output_asset.width or result.width,
            actual_height=output_asset.height or result.height,
            actual_duration_milliseconds=(
                output_asset.duration_milliseconds or result.duration_milliseconds
            ),
            completed_at=datetime.now(UTC),
        )
        await self._repository.save(completed)
        return completed

    async def get(self, project_id: str) -> VideoProject:
        project = await self._repository.get(project_id)
        if project is None:
            raise MediaLabVideoProjectError(
                "Media Lab video project was not found", status_code=404, code="not_found"
            )
        return project

    async def list(self) -> list[VideoProject]:
        return await self._repository.list()

    async def review(self, project_id: str, state: VideoProjectState) -> VideoProject:
        if state not in {VideoProjectState.APPROVED, VideoProjectState.REJECTED}:
            raise MediaLabVideoProjectError("Video project review decision is invalid")
        project = await self.get(project_id)
        if (
            project.state != VideoProjectState.AWAITING_HUMAN_REVIEW
            or project.output_asset_id is None
            or project.output_checksum_sha256 is None
        ):
            raise MediaLabVideoProjectError(
                "Only an exact completed final video can be reviewed",
                status_code=409,
                code="review_not_ready",
            )
        reviewed = replace(project, state=state, reviewed_at=datetime.now(UTC))
        await self._repository.save(reviewed)
        return reviewed


def _validate_command(command: CreateVideoProjectCommand) -> None:
    if not command.source_run_id.strip():
        raise MediaLabVideoProjectError("Video project source_run_id cannot be blank")
    if not _MIN_PROJECT_SECONDS <= command.target_duration_seconds <= _MAX_PROJECT_SECONDS:
        raise MediaLabVideoProjectError(
            "Final Ads video duration must be between 20 and 25 seconds",
            code="invalid_target_duration",
        )
    if not 2 <= len(command.shots) <= _MAX_PROJECT_SHOTS:
        raise MediaLabVideoProjectError(
            "Final Ads video requires between 2 and 8 ordered shots",
            code="invalid_shot_count",
        )
    shot_ids = [shot.shot_id.strip() for shot in command.shots]
    if any(not shot_id for shot_id in shot_ids) or len(set(shot_ids)) != len(shot_ids):
        raise MediaLabVideoProjectError(
            "Video project shot IDs must be non-empty and unique", code="invalid_shot_id"
        )
    if any(
        shot.trim_start_seconds < 0 or shot.trim_end_seconds <= shot.trim_start_seconds
        for shot in command.shots
    ):
        raise MediaLabVideoProjectError(
            "Every shot requires a valid positive trim window", code="invalid_trim_window"
        )
    planned_duration = sum(shot.duration_seconds for shot in command.shots)
    if abs(planned_duration - command.target_duration_seconds) > _DURATION_TOLERANCE_SECONDS:
        raise MediaLabVideoProjectError(
            "Shot trim durations must add up to the final target duration",
            code="duration_mismatch",
        )


def _command_hash(command: CreateVideoProjectCommand) -> str:
    payload = {
        "source_run_id": command.source_run_id,
        "target_duration_seconds": command.target_duration_seconds,
        "shots": [
            {
                "shot_id": shot.shot_id,
                "source_run_id": shot.source_run_id,
                "trim_start_seconds": shot.trim_start_seconds,
                "trim_end_seconds": shot.trim_end_seconds,
            }
            for shot in command.shots
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["MediaLabVideoProjectService"]
