"""Durable coordinator for slow Media Lab planning requests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from loguru import logger

from ..domain.assets import MediaAssetOrigin
from ..domain.models import (
    ImageOrchestrationPlan,
    ImagePlanningSource,
    ImagePlanningState,
    ImageSourceOrigin,
)
from ..domain.planning_jobs import PlanningJob, PlanningJobKind, PlanningJobState
from ..domain.video_models import (
    VideoPlanningImageSource,
    VideoPlanningState,
    VideoSourceOrigin,
)
from ..ports.assets import IMediaAssetResolver, MediaAssetError
from ..ports.interfaces import MediaLabImageOrchestrationError
from ..ports.planning_jobs import IPlanningJobRepository, MediaLabPlanningJobError
from ..ports.video_interfaces import MediaLabVideoOrchestrationError
from .orchestration import MediaLabImageOrchestrationService
from .video_orchestration import MediaLabVideoOrchestrationService


class MediaLabPlanningJobService:
    def __init__(
        self,
        repository: IPlanningJobRepository,
        media_assets: IMediaAssetResolver,
        image_planner: MediaLabImageOrchestrationService | None,
        video_planner: MediaLabVideoOrchestrationService | None,
        *,
        timeout_seconds: float = 150,
    ) -> None:
        self._repository = repository
        self._media_assets = media_assets
        self._image_planner = image_planner
        self._video_planner = video_planner
        self._timeout_seconds = timeout_seconds
        self._advance_lock = asyncio.Lock()
        self._planning_slots = asyncio.Semaphore(2)

    def close(self) -> None:
        self._repository.close()

    async def create(
        self,
        *,
        source_run_id: str,
        kind: PlanningJobKind,
        user_request: str,
        source_asset_ids: tuple[str, ...],
    ) -> PlanningJob:
        if not source_run_id.strip() or not user_request.strip():
            raise MediaLabPlanningJobError("Planning request is incomplete")
        input_hash = _input_hash(kind, user_request, source_asset_ids)
        existing = await self._repository.get_by_source_run_id(source_run_id)
        if existing is not None:
            if existing.input_hash != input_hash:
                raise MediaLabPlanningJobError(
                    "Planning request changed for an existing request ID",
                    status_code=409,
                    code="input_drift",
                )
            return existing
        now = datetime.now(UTC)
        job = PlanningJob(
            job_id=uuid4().hex,
            source_run_id=source_run_id,
            input_hash=input_hash,
            kind=kind,
            user_request=user_request.strip(),
            source_asset_ids=source_asset_ids,
            state=PlanningJobState.PLANNING,
            plan=None,
            error_code=None,
            created_at=now,
            updated_at=now,
        )
        await self._repository.save(job)
        return job

    async def get(self, job_id: str) -> PlanningJob:
        job = await self._repository.get(job_id)
        if job is None:
            raise MediaLabPlanningJobError(
                "Planning job was not found", status_code=404, code="not_found"
            )
        return job

    async def accept_image_draft(self, job_id: str) -> PlanningJob:
        job = await self.get(job_id)
        if job.kind != PlanningJobKind.IMAGE:
            raise MediaLabPlanningJobError(
                "Image planning job was not found", status_code=404, code="not_found"
            )
        if job.state == PlanningJobState.READY:
            return job
        if job.state != PlanningJobState.NEEDS_INPUT or not isinstance(
            job.plan, ImageOrchestrationPlan
        ):
            raise MediaLabPlanningJobError(
                "This request cannot be generated as a draft",
                status_code=409,
                code="draft_not_available",
            )
        if self._image_planner is None:
            raise MediaLabPlanningJobError("Image planning is unavailable", code="unavailable")
        sources = []
        for index, asset_id in enumerate(job.source_asset_ids):
            asset, image = await self._media_assets.image_binary(asset_id)
            if asset.origin == MediaAssetOrigin.UPLOAD:
                origin, run_id = ImageSourceOrigin.UPLOAD, None
            elif asset.origin == MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT and asset.source_run_id:
                origin, run_id = ImageSourceOrigin.MEDIA_LAB_OUTPUT, asset.source_run_id
            else:
                raise MediaAssetError("Unsupported image source", code="unsupported_source")
            sources.append(ImagePlanningSource(index, image, origin, run_id))
        plan = self._image_planner.draft(
            job.user_request,
            tuple(sources),
            questions=job.plan.questions,
            uncertainties=job.plan.uncertainties,
        )
        updated = replace(
            job,
            plan=plan,
            state=PlanningJobState.READY,
            updated_at=datetime.now(UTC),
        )
        await self._repository.save(updated)
        return updated

    async def advance_all(self) -> None:
        async with self._advance_lock:
            await asyncio.gather(
                *(self._advance_safely(job) for job in await self._repository.list_active())
            )

    async def _advance_safely(self, job: PlanningJob) -> None:
        async with self._planning_slots:
            try:
                await self._advance(job)
            except Exception as error:  # noqa: BLE001 - isolate persisted jobs
                logger.exception("Media Lab planning job {} failed", job.job_id)
                await self._persist_failure(job, error)

    async def run_forever(self, stop_event: asyncio.Event, interval_seconds: float = 1.0) -> None:
        while not stop_event.is_set():
            await self.advance_all()
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)

    async def _advance(self, job: PlanningJob) -> PlanningJob:
        async with asyncio.timeout(self._timeout_seconds):
            if job.kind == PlanningJobKind.IMAGE:
                plan = await self._plan_image(job)
                state = (
                    PlanningJobState.READY
                    if plan.state == ImagePlanningState.READY
                    else PlanningJobState.NEEDS_INPUT
                )
            else:
                plan = await self._plan_video(job)
                state = (
                    PlanningJobState.READY
                    if plan.state == VideoPlanningState.READY
                    else PlanningJobState.NEEDS_INPUT
                )
        updated = replace(job, plan=plan, state=state, updated_at=datetime.now(UTC))
        await self._repository.save(updated)
        return updated

    async def _plan_image(self, job: PlanningJob):
        if self._image_planner is None:
            raise MediaLabPlanningJobError("Image planning is unavailable", code="unavailable")
        sources = []
        for index, asset_id in enumerate(job.source_asset_ids):
            asset, image = await self._media_assets.image_binary(asset_id)
            if asset.origin == MediaAssetOrigin.UPLOAD:
                origin, run_id = ImageSourceOrigin.UPLOAD, None
            elif asset.origin == MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT and asset.source_run_id:
                origin, run_id = ImageSourceOrigin.MEDIA_LAB_OUTPUT, asset.source_run_id
            else:
                raise MediaAssetError("Unsupported image source", code="unsupported_source")
            sources.append(ImagePlanningSource(index, image, origin, run_id))
        return await self._image_planner.plan(job.user_request, tuple(sources))

    async def _plan_video(self, job: PlanningJob):
        if self._video_planner is None:
            raise MediaLabPlanningJobError("Video planning is unavailable", code="unavailable")
        sources = []
        for index, asset_id in enumerate(job.source_asset_ids):
            asset, image = await self._media_assets.image_binary(asset_id)
            if asset.origin == MediaAssetOrigin.UPLOAD:
                origin, run_id = VideoSourceOrigin.UPLOAD, None
            elif asset.origin == MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT and asset.source_run_id:
                origin, run_id = VideoSourceOrigin.MEDIA_LAB_IMAGE_OUTPUT, asset.source_run_id
            else:
                raise MediaAssetError("Unsupported video source", code="unsupported_source")
            sources.append(VideoPlanningImageSource(index, image, origin, run_id))
        return await self._video_planner.plan(job.user_request, tuple(sources))

    async def _persist_failure(self, job: PlanningJob, error: Exception) -> None:
        if isinstance(
            error,
            (
                MediaAssetError,
                MediaLabImageOrchestrationError,
                MediaLabVideoOrchestrationError,
                MediaLabPlanningJobError,
            ),
        ):
            code = error.code
        elif isinstance(error, TimeoutError):
            code = "planning_timeout"
        else:
            code = "planning_failed"
        await self._repository.save(
            replace(
                job,
                state=PlanningJobState.FAILED,
                error_code=code,
                updated_at=datetime.now(UTC),
            )
        )


def _input_hash(kind: PlanningJobKind, user_request: str, source_asset_ids: tuple[str, ...]) -> str:
    payload = json.dumps(
        {
            "kind": kind.value,
            "user_request": user_request.strip(),
            "source_asset_ids": source_asset_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["MediaLabPlanningJobService"]
