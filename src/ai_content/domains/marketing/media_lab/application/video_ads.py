"""Autonomous brief-to-final Video Ad coordinator."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger

from ..domain.assets import MediaAssetOrigin
from ..domain.video_ads import (
    CreateVideoAdCommand,
    VideoAdCandidate,
    VideoAdJob,
    VideoAdJobState,
)
from ..domain.video_models import (
    CreateVideoCommand,
    VideoGenerationState,
    VideoImageSourceInput,
    VideoOutputFormat,
    VideoSourceOrigin,
)
from ..ports.assets import IGeneratedMediaAssetWriter, IMediaAssetResolver, MediaAssetError
from ..ports.video_ads import (
    IVideoAdPlanner,
    IVideoAdRepository,
    IVideoCandidateSelector,
    MediaLabVideoAdError,
)
from ..ports.video_interfaces import MediaLabVideoOrchestrationError
from ..ports.video_projects import (
    IVideoCompositor,
    VideoCompositionError,
    VideoCompositionRequest,
    VideoCompositionShot,
)
from .video_runs import MediaLabVideoService

_ACTIVE_STATES = {
    VideoAdJobState.PLANNING,
    VideoAdJobState.GENERATING_SHOTS,
    VideoAdJobState.SELECTING_SEGMENTS,
    VideoAdJobState.ASSEMBLING,
    VideoAdJobState.CANCEL_REQUESTED,
}
_OUTPUT_PRESET = {
    "1:1": ("square_0_8mp", 896, 896),
    "9:16": ("portrait_9_16_0_8mp", 720, 1280),
    "16:9": ("landscape_16_9_0_8mp", 1280, 720),
}


class MediaLabVideoAdService:
    def __init__(
        self,
        repository: IVideoAdRepository,
        planner: IVideoAdPlanner,
        video_runs: MediaLabVideoService,
        selector: IVideoCandidateSelector,
        compositor: IVideoCompositor,
        media_assets: IMediaAssetResolver,
        output_writer: IGeneratedMediaAssetWriter,
    ) -> None:
        self._repository = repository
        self._planner = planner
        self._video_runs = video_runs
        self._selector = selector
        self._compositor = compositor
        self._media_assets = media_assets
        self._output_writer = output_writer
        self._advance_lock = asyncio.Lock()

    def close(self) -> None:
        self._repository.close()

    async def create(self, command: CreateVideoAdCommand) -> VideoAdJob:
        _validate_command(command)
        input_hash = _command_hash(command)
        existing = await self._repository.get_by_source_run_id(command.source_run_id)
        if existing is not None:
            if existing.input_hash != input_hash:
                raise MediaLabVideoAdError(
                    "Video Ad source_run_id was already used with different input",
                    status_code=409,
                    code="input_drift",
                )
            return existing

        now = datetime.now(UTC)
        job = VideoAdJob(
            job_id=uuid4().hex,
            source_run_id=command.source_run_id,
            input_hash=input_hash,
            brief=command.brief,
            state=VideoAdJobState.PLANNING,
            plan=None,
            candidates=(),
            selected_segments=(),
            output_asset_id=None,
            output_checksum_sha256=None,
            actual_width=None,
            actual_height=None,
            actual_duration_milliseconds=None,
            error_code=None,
            created_at=now,
            updated_at=now,
        )
        await self._repository.save(job)
        return job

    async def get(self, job_id: str) -> VideoAdJob:
        job = await self._repository.get(job_id)
        if job is None:
            raise MediaLabVideoAdError(
                "Video Ad job was not found", status_code=404, code="not_found"
            )
        return job

    async def list(self) -> list[VideoAdJob]:
        return await self._repository.list()

    async def delete(self, job_id: str) -> None:
        job = await self.get(job_id)
        if job.state in _ACTIVE_STATES:
            raise MediaLabVideoAdError(
                "An active Video Ad cannot be removed from Media Library",
                status_code=409,
                code="job_active",
            )
        await self._repository.delete(job_id)

    async def cancel(self, job_id: str) -> VideoAdJob:
        job = await self.get(job_id)
        if job.state not in _ACTIVE_STATES:
            raise MediaLabVideoAdError(
                "Only an active Video Ad job can be cancelled",
                status_code=409,
                code="job_not_active",
            )
        updated = replace(job, state=VideoAdJobState.CANCEL_REQUESTED, updated_at=datetime.now(UTC))
        await self._repository.save(updated)
        return updated

    async def advance_all(self) -> None:
        async with self._advance_lock:
            for job in await self._repository.list_active():
                try:
                    await self._advance(job)
                except Exception as error:  # noqa: BLE001 - isolate persisted jobs
                    logger.exception("Autonomous Video Ad job {} failed", job.job_id)
                    await self._persist_failure(job, error)

    async def advance(self, job_id: str) -> VideoAdJob:
        async with self._advance_lock:
            job = await self.get(job_id)
            try:
                return await self._advance(job)
            except Exception as error:
                await self._persist_failure(job, error)
                raise

    async def run_forever(self, stop_event: asyncio.Event, interval_seconds: float = 2.0) -> None:
        while not stop_event.is_set():
            await self.advance_all()
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)

    async def _advance(self, job: VideoAdJob) -> VideoAdJob:
        if job.state == VideoAdJobState.CANCEL_REQUESTED:
            cancelled = replace(
                job,
                state=VideoAdJobState.CANCELLED,
                updated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            await self._repository.save(cancelled)
            return cancelled
        if job.state == VideoAdJobState.PLANNING:
            return await self._advance_planning(job)
        if job.state == VideoAdJobState.GENERATING_SHOTS:
            return await self._advance_generation(job)
        if job.state == VideoAdJobState.SELECTING_SEGMENTS:
            return await self._select_segments(job)
        if job.state == VideoAdJobState.ASSEMBLING:
            return await self._assemble(job)
        return job

    async def _advance_planning(self, job: VideoAdJob) -> VideoAdJob:
        images = []
        for asset_id in job.brief.source_asset_ids:
            _, image = await self._media_assets.image_binary(asset_id)
            images.append(image)
        plan = await self._planner.plan_video_ad(
            job.brief.user_request,
            brand=job.brief.brand,
            sku=job.brief.sku,
            angle=job.brief.angle,
            target_duration_seconds=job.brief.target_duration_seconds,
            aspect_ratio=job.brief.aspect_ratio,
            cta_text=job.brief.cta_text,
            sources=tuple(images),
        )
        state = VideoAdJobState.NEEDS_INPUT if not plan.shots else VideoAdJobState.GENERATING_SHOTS
        planned = replace(job, plan=plan, state=state, updated_at=datetime.now(UTC))
        await self._repository.save(planned)
        return planned

    async def _advance_generation(self, job: VideoAdJob) -> VideoAdJob:
        assert job.plan is not None
        runs = {item.run_id: await self._video_runs.get(item.run_id) for item in job.candidates}
        if any(
            run.generation_state in {VideoGenerationState.QUEUED, VideoGenerationState.RUNNING}
            for run in runs.values()
        ):
            return job
        for shot in job.plan.shots:
            shot_candidates = [item for item in job.candidates if item.shot_id == shot.shot_id]
            successful = [
                item
                for item in shot_candidates
                if runs[item.run_id].generation_state == VideoGenerationState.SUCCEEDED
            ]
            attempts = len(shot_candidates)
            needs_technical_retry = job.error_code == f"no_usable_candidate:{shot.shot_id}"
            if len(successful) >= job.brief.candidate_count and not needs_technical_retry:
                continue
            if attempts >= job.brief.candidate_count + 1:
                raise MediaLabVideoAdError(
                    f"Shot {shot.shot_id} exhausted its technical generation budget",
                    status_code=422,
                    code="shot_generation_failed",
                )
            candidate_index = attempts + 1
            run = await self._create_candidate(job, shot, candidate_index)
            updated = replace(
                job,
                candidates=(
                    *job.candidates,
                    VideoAdCandidate(
                        shot_id=shot.shot_id,
                        candidate_index=candidate_index,
                        run_id=run.run_id,
                        seed=run.seed,
                    ),
                ),
                error_code=None,
                updated_at=datetime.now(UTC),
            )
            await self._repository.save(updated)
            return updated
        updated = replace(
            job,
            state=VideoAdJobState.SELECTING_SEGMENTS,
            updated_at=datetime.now(UTC),
        )
        await self._repository.save(updated)
        return await self._select_segments(updated)

    async def _create_candidate(self, job: VideoAdJob, shot, candidate_index: int):
        assert job.plan is not None
        source_plan_by_index = {source.source_index: source for source in job.plan.sources}
        sources = []
        for source_index in shot.source_indexes:
            asset_id = job.brief.source_asset_ids[source_index]
            asset, image = await self._media_assets.image_binary(asset_id)
            planned = source_plan_by_index[source_index]
            sources.append(
                VideoImageSourceInput(
                    source_index=len(sources),
                    role=planned.role,
                    usage=planned.usage,
                    priority=planned.priority,
                    must_preserve=planned.must_preserve,
                    allowed_changes=planned.allowed_changes,
                    source_origin=(
                        VideoSourceOrigin.MEDIA_LAB_IMAGE_OUTPUT
                        if asset.origin == MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT
                        else VideoSourceOrigin.UPLOAD
                    ),
                    binary=image,
                    identity_group=planned.identity_group,
                    # Final Ads run in technical-only mode without specialized
                    # identity verification. Keep the planner's identity group
                    # for generation provenance, but do not submit a primary
                    # verification target to the short-video service.
                    is_primary_identity=False,
                    asset_id=asset_id,
                )
            )
        preset_id = _OUTPUT_PRESET[job.brief.aspect_ratio][0]
        return await self._video_runs.create(
            CreateVideoCommand(
                intent=shot.intent,
                prompt=shot.prompt,
                sources=tuple(sources),
                duration_seconds=shot.generation_duration_seconds,
                seed=_candidate_seed(job.job_id, shot.shot_id, candidate_index),
                verification_plan=(),
                output_preset_id=preset_id,
                output_format=VideoOutputFormat.MP4,
                technical_only=True,
            )
        )

    async def _select_segments(self, job: VideoAdJob) -> VideoAdJob:
        assert job.plan is not None
        selected = []
        for shot in job.plan.shots:
            candidates = []
            for item in job.candidates:
                if item.shot_id != shot.shot_id:
                    continue
                run = await self._video_runs.get(item.run_id)
                if run.generation_state != VideoGenerationState.SUCCEEDED:
                    continue
                path, content_type = await self._video_runs.output_file(item.run_id)
                if content_type == "video/mp4":
                    candidates.append((item.candidate_index, item.run_id, path))
            try:
                segment = await asyncio.to_thread(
                    self._selector.select,
                    shot.shot_id,
                    tuple(candidates),
                    shot.usable_duration_seconds,
                )
            except MediaLabVideoAdError:
                attempts = len([item for item in job.candidates if item.shot_id == shot.shot_id])
                if attempts < job.brief.candidate_count + 1:
                    retry_job = replace(
                        job,
                        state=VideoAdJobState.GENERATING_SHOTS,
                        error_code=f"no_usable_candidate:{shot.shot_id}",
                        updated_at=datetime.now(UTC),
                    )
                    await self._repository.save(retry_job)
                    return retry_job
                raise
            selected.append(segment)
        updated = replace(
            job,
            selected_segments=tuple(selected),
            state=VideoAdJobState.ASSEMBLING,
            updated_at=datetime.now(UTC),
        )
        await self._repository.save(updated)
        return await self._assemble(updated)

    async def _assemble(self, job: VideoAdJob) -> VideoAdJob:
        assert job.plan is not None
        shot_by_id = {shot.shot_id: shot for shot in job.plan.shots}
        composition_shots = []
        parent_asset_ids = list(job.brief.source_asset_ids)
        for segment in job.selected_segments:
            path, _ = await self._video_runs.output_file(segment.run_id)
            run = await self._video_runs.get(segment.run_id)
            if run.output_asset_id is not None:
                parent_asset_ids.append(run.output_asset_id)
            planned = shot_by_id[segment.shot_id]
            composition_shots.append(
                VideoCompositionShot(
                    shot_id=segment.shot_id,
                    source_path=path,
                    trim_start_seconds=segment.trim_start_seconds,
                    trim_end_seconds=segment.trim_end_seconds,
                    overlay_text=planned.on_screen_text,
                )
            )
        _, width, height = _OUTPUT_PRESET[job.brief.aspect_ratio]
        with tempfile.TemporaryDirectory(prefix="video-ad-") as temporary_directory:
            logo_path = await self._write_logo(job, Path(temporary_directory))
            if job.brief.logo_asset_id:
                parent_asset_ids.append(job.brief.logo_asset_id)
            result = await asyncio.to_thread(
                self._compositor.compose,
                VideoCompositionRequest(
                    project_id=job.job_id,
                    shots=tuple(composition_shots),
                    target_duration_seconds=job.brief.target_duration_seconds,
                    width=width,
                    height=height,
                    logo_path=logo_path,
                    cta_text=job.brief.cta_text,
                ),
            )
        content = await asyncio.to_thread(result.output_path.read_bytes)
        output = await self._output_writer.register_generated_video(
            content,
            source_run_id=job.job_id,
            parent_asset_ids=tuple(dict.fromkeys(parent_asset_ids)),
        )
        completed = replace(
            job,
            state=VideoAdJobState.COMPLETED,
            output_asset_id=output.asset_id,
            output_checksum_sha256=output.checksum_sha256,
            actual_width=output.width or result.width,
            actual_height=output.height or result.height,
            actual_duration_milliseconds=(
                output.duration_milliseconds or result.duration_milliseconds
            ),
            error_code=None,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        await self._repository.save(completed)
        return completed

    async def _write_logo(self, job: VideoAdJob, directory: Path) -> Path | None:
        if not job.brief.logo_asset_id:
            return None
        content, content_type = await self._media_assets.read_original(job.brief.logo_asset_id)
        if content_type not in {"image/png", "image/jpeg"}:
            raise MediaLabVideoAdError(
                "Logo asset must be a PNG or JPEG", code="invalid_logo_asset"
            )
        suffix = ".png" if content_type == "image/png" else ".jpg"
        path = directory / f"logo{suffix}"
        path.write_bytes(content)
        return path

    def _failed(self, job: VideoAdJob, error_code: str) -> VideoAdJob:
        return replace(
            job,
            state=VideoAdJobState.FAILED,
            error_code=error_code,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

    async def _persist_failure(self, fallback: VideoAdJob, error: Exception) -> VideoAdJob:
        latest = await self._repository.get(fallback.job_id) or fallback
        failed = self._failed(latest, _error_code(error))
        await self._repository.save(failed)
        return failed


def _validate_command(command: CreateVideoAdCommand) -> None:
    brief = command.brief
    if not command.source_run_id.strip() or not brief.user_request.strip():
        raise MediaLabVideoAdError("Video Ad source ID and request are required")
    if not 20 <= brief.target_duration_seconds <= 25:
        raise MediaLabVideoAdError("Final Video Ad duration must be between 20 and 25 seconds")
    if brief.aspect_ratio not in _OUTPUT_PRESET:
        raise MediaLabVideoAdError("Final Video Ad aspect ratio must be 1:1, 9:16, or 16:9")
    if not 1 <= brief.candidate_count <= 3:
        raise MediaLabVideoAdError("Video Ad candidate_count must be between 1 and 3")
    if len(brief.source_asset_ids) > 8:
        raise MediaLabVideoAdError("Video Ad planning accepts at most 8 image sources")


def _command_hash(command: CreateVideoAdCommand) -> str:
    payload = {
        "source_run_id": command.source_run_id,
        "brief": {
            "user_request": command.brief.user_request,
            "brand": command.brief.brand,
            "sku": command.brief.sku,
            "angle": command.brief.angle,
            "source_asset_ids": command.brief.source_asset_ids,
            "target_duration_seconds": command.brief.target_duration_seconds,
            "aspect_ratio": command.brief.aspect_ratio,
            "candidate_count": command.brief.candidate_count,
            "cta_text": command.brief.cta_text,
            "logo_asset_id": command.brief.logo_asset_id,
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _candidate_seed(job_id: str, shot_id: str, candidate_index: int) -> int:
    digest = hashlib.sha256(f"{job_id}:{shot_id}:{candidate_index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _error_code(error: Exception) -> str:
    if isinstance(
        error,
        (
            MediaLabVideoAdError,
            MediaLabVideoOrchestrationError,
            MediaAssetError,
            VideoCompositionError,
        ),
    ):
        return error.code
    if isinstance(error, OSError):
        return "artifact_unavailable"
    return "video_ad_failed"


__all__ = ["MediaLabVideoAdService"]
