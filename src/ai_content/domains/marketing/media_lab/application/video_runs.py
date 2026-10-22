"""Create Video orchestration for the bounded Media Lab ML2 slice."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger

from ..domain.models import ImageBinary
from ..domain.video_models import (
    CreateVideoCommand,
    VideoCapability,
    VideoGenerationState,
    VideoImageSourceInput,
    VideoIntent,
    VideoOutputFormat,
    VideoOutputPreset,
    VideoOutputSpec,
    VideoQualityDecision,
    VideoQualityIssue,
    VideoQualityIssueSeverity,
    VideoQualityReview,
    VideoQualityReviewRequest,
    VideoQualityReviewSource,
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
    VideoTemporalEvidence,
    VideoVerificationReport,
    VideoVerificationStage,
    VideoVerificationState,
    VideoVerificationStatus,
)
from ..ports.assets import IGeneratedMediaAssetWriter, MediaAssetError
from ..ports.interfaces import MediaLabImageError
from ..ports.video_interfaces import (
    IImageOutputSource,
    IVideoArtifactStore,
    IVideoEvidenceVerifier,
    IVideoFrameSampler,
    IVideoGenerationBackend,
    IVideoQualityReviewer,
    IVideoRunRepository,
    MediaLabVideoError,
    MediaLabVideoQualityReviewError,
    PinnedVideoGeneration,
    PinnedVideoGraph,
    VideoBackendUpdate,
    VideoEvidenceVerificationRequest,
    VideoVerificationImage,
)

_DURATION_SECONDS = tuple(range(4, 16))
_VIDEO_OUTPUT_PRESETS = (
    VideoOutputPreset("square_0_8mp", "Square 1:1  -  final", "1:1", "1:1 (Square)", 0.8),
    VideoOutputPreset(
        "portrait_9_16_0_8mp",
        "Vertical 9:16  -  final",
        "9:16",
        "9:16 (Portrait Widescreen)",
        0.8,
    ),
    VideoOutputPreset(
        "landscape_16_9_0_8mp",
        "Landscape 16:9  -  final",
        "16:9",
        "16:9 (Widescreen)",
        0.8,
    ),
    VideoOutputPreset("square_0_6mp", "Square 1:1  -  0.6 MP", "1:1", "1:1 (Square)", 0.6),
    VideoOutputPreset(
        "portrait_9_16_1mp", "Vertical 9:16  -  final", "9:16", "9:16 (Portrait Widescreen)", 1.0
    ),
    VideoOutputPreset(
        "landscape_16_9_1mp",
        "Landscape 16:9  -  final",
        "16:9",
        "16:9 (Widescreen)",
        1.0,
    ),
    VideoOutputPreset("square_0_4mp", "Square 1:1  -  0.4 MP", "1:1", "1:1 (Square)", 0.4),
    VideoOutputPreset(
        "portrait_9_16_0_4mp", "Vertical 9:16  -  0.4 MP", "9:16", "9:16 (Portrait Widescreen)", 0.4
    ),
    VideoOutputPreset(
        "landscape_16_9_0_4mp", "Landscape 16:9  -  0.4 MP", "16:9", "16:9 (Widescreen)", 0.4
    ),
)
_VIDEO_OUTPUT_FORMATS = (VideoOutputFormat.MP4,)
_GRAPH_BY_CAPABILITY = {
    "create_from_text": PinnedVideoGraph.TEXT_TO_VIDEO,
    "create_from_images": PinnedVideoGraph.IMAGE_TO_VIDEO,
}


def build_video_capabilities(generator: IVideoGenerationBackend) -> tuple[VideoCapability, ...]:
    image_input_capacity = generator.pinned_video_image_input_capacity(
        PinnedVideoGraph.IMAGE_TO_VIDEO
    )
    capabilities = [
        VideoCapability(
            capability_id="create_from_text",
            intent=VideoIntent.CREATE_FROM_TEXT,
            label="Create video from text",
            description="Create one short video shot from a visual prompt without source images.",
            minimum_generation_images=0,
            maximum_generation_images=0,
            supported_duration_seconds=_DURATION_SECONDS,
            output_presets=_VIDEO_OUTPUT_PRESETS,
            supported_output_formats=_VIDEO_OUTPUT_FORMATS,
            default_output_preset_id="landscape_16_9_0_8mp",
        )
    ]
    if image_input_capacity > 0:
        capabilities.append(
            VideoCapability(
                capability_id="create_from_images",
                intent=VideoIntent.CREATE_FROM_IMAGES,
                label="Create video from image sources",
                description=(
                    "Use one or more Terra-resolved image sources for product, character, "
                    "scene, style, keyframe, or storyboard conditioning."
                ),
                minimum_generation_images=1,
                maximum_generation_images=image_input_capacity,
                supported_duration_seconds=_DURATION_SECONDS,
                output_presets=_VIDEO_OUTPUT_PRESETS,
                supported_output_formats=_VIDEO_OUTPUT_FORMATS,
                default_output_preset_id="square_0_8mp",
            )
        )
    return tuple(capabilities)


class MediaLabVideoService:
    def __init__(
        self,
        repository: IVideoRunRepository,
        artifacts: IVideoArtifactStore,
        generator: IVideoGenerationBackend,
        image_source: IImageOutputSource,
        *,
        quality_reviewer: IVideoQualityReviewer | None = None,
        frame_sampler: IVideoFrameSampler | None = None,
        evidence_verifier: IVideoEvidenceVerifier | None = None,
        media_assets: IGeneratedMediaAssetWriter | None = None,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._generator = generator
        self._image_source = image_source
        self._quality_reviewer = quality_reviewer
        self._frame_sampler = frame_sampler
        self._evidence_verifier = evidence_verifier
        self._media_assets = media_assets
        self._capabilities = build_video_capabilities(generator)
        self._backend_run_ids: dict[str, str] = {}
        self._generator.add_video_observer(self.observe_backend_update)

    def capabilities(self) -> tuple[VideoCapability, ...]:
        return self._capabilities

    def capability(self, capability_id: str) -> VideoCapability:
        for capability in self._capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise MediaLabVideoError(
            "Media Lab video capability is invalid", code="unsupported_capability"
        )

    def maximum_source_count(self) -> int:
        return max(capability.maximum_generation_images for capability in self._capabilities)

    def enabled(self) -> bool:
        return self._generator.video_generation_available()

    def notice(self) -> str | None:
        return self._generator.video_generation_notice()

    def queue_position(self, backend_run_id: str | None) -> int | None:
        if backend_run_id is None:
            return None
        resolver = getattr(self._generator, "queue_position", None)
        return resolver(backend_run_id) if callable(resolver) else None

    def quality_review_enabled(self) -> bool:
        return self._quality_reviewer is not None

    def max_regenerations(self) -> int:
        return self._quality_reviewer.max_regenerations if self._quality_reviewer else 0

    async def interrupt_inflight(self) -> int:
        return await self._repository.mark_inflight_interrupted()

    def close(self) -> None:
        self._repository.close()

    async def create(
        self,
        command: CreateVideoCommand,
        *,
        retry_of_run_id: str | None = None,
        regeneration_count: int = 0,
    ) -> VideoRun:
        if regeneration_count < 0 or (regeneration_count and retry_of_run_id is None):
            raise MediaLabVideoError(
                "Video regeneration lineage is invalid", code="invalid_regeneration"
            )
        if not command.prompt.strip():
            raise MediaLabVideoError("Visual instruction cannot be blank", code="invalid_prompt")
        capability = _resolve_capability(command, self._capabilities)
        if not self.enabled():
            raise MediaLabVideoError(
                "Media Lab is not configured", status_code=503, code="not_configured"
            )
        output_spec = _resolve_output_spec(command, capability)
        run_id = uuid4().hex
        sources, materials = await self._persist_sources(run_id, command.sources)
        rendered_prompt = _render_prompt(command.prompt, sources)
        now = datetime.now(UTC)
        run = VideoRun(
            run_id=run_id,
            intent=command.intent,
            prompt=command.prompt.strip(),
            rendered_prompt=rendered_prompt,
            sources=sources,
            verification_plan=command.verification_plan,
            output_spec=output_spec,
            seed=command.seed,
            generation_state=VideoGenerationState.QUEUED,
            review_state=VideoReviewState.NOT_READY,
            model=None,
            checkpoint_observation=None,
            graph_template_hash=None,
            backend_run_id=None,
            provider_job_id=None,
            orchestration=command.orchestration,
            output_ref=None,
            output_checksum_sha256=None,
            output_content_type=None,
            manifest_ref=None,
            error_code=None,
            quality_review_state=VideoQualityReviewState.NOT_REQUESTED,
            quality_review=None,
            quality_review_error_code=None,
            regenerated_run_id=None,
            retry_of_run_id=retry_of_run_id,
            regeneration_count=regeneration_count,
            created_at=now,
            retry_memory=command.retry_memory,
        )
        await self._repository.save(run)
        try:
            backend = await self._generator.submit_pinned_video(
                PinnedVideoGeneration(
                    graph=_GRAPH_BY_CAPABILITY[capability.capability_id],
                    prompt=rendered_prompt,
                    images=materials,
                    duration_seconds=output_spec.duration_seconds,
                    seed=command.seed,
                    selector_aspect_ratio=_selector_aspect_ratio(output_spec),
                    megapixels=output_spec.megapixels,
                )
            )
        except Exception:
            await self._repository.save(
                replace(
                    run,
                    generation_state=VideoGenerationState.FAILED,
                    completed_at=datetime.now(UTC),
                    error_code="submission_failed",
                )
            )
            raise
        run = replace(
            run,
            seed=backend.seed,
            model=backend.model,
            checkpoint_observation=backend.checkpoint_observation,
            graph_template_hash=backend.graph_template_hash,
            backend_run_id=backend.backend_run_id,
        )
        self._backend_run_ids[backend.backend_run_id] = run.run_id
        await self._repository.save(run)
        return run

    async def get(self, run_id: str) -> VideoRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise MediaLabVideoError(
                "Media Lab video run was not found", status_code=404, code="not_found"
            )
        return run

    async def list(self) -> list[VideoRun]:
        return await self._repository.list()

    async def delete(self, run_id: str) -> None:
        run = await self.get(run_id)
        if run.generation_state in {
            VideoGenerationState.QUEUED,
            VideoGenerationState.RUNNING,
        }:
            raise MediaLabVideoError(
                "A running video cannot be removed from Media Library",
                status_code=409,
                code="run_active",
            )
        await self._repository.delete(run_id)

    async def retry_lineage(self, run_id: str) -> tuple[VideoRun, ...]:
        run = await self.get(run_id)
        runs = {item.run_id: item for item in await self._repository.list()}
        root = _retry_root(run, runs)
        children: dict[str, list[VideoRun]] = {}
        for item in runs.values():
            if item.retry_of_run_id is not None:
                children.setdefault(item.retry_of_run_id, []).append(item)

        lineage: list[VideoRun] = []
        pending = [root]
        visited: set[str] = set()
        while pending:
            candidate = pending.pop()
            if candidate.run_id in visited:
                raise MediaLabVideoError(
                    "Video regeneration lineage contains a cycle",
                    status_code=409,
                    code="invalid_retry_lineage",
                )
            visited.add(candidate.run_id)
            lineage.append(candidate)
            pending.extend(children.get(candidate.run_id, ()))
        return tuple(
            sorted(
                lineage, key=lambda item: (item.regeneration_count, item.created_at, item.run_id)
            )
        )

    async def review(self, run_id: str, state: VideoReviewState) -> VideoRun:
        if state not in {VideoReviewState.APPROVED, VideoReviewState.REJECTED}:
            raise MediaLabVideoError("Review decision is invalid", code="invalid_review")
        run = await self.get(run_id)
        ready_for_human_review = (
            run.generation_state == VideoGenerationState.SUCCEEDED
            and run.review_state == VideoReviewState.AWAITING_HUMAN_REVIEW
        )
        automated_review_ready = (
            run.verification_state == VideoVerificationState.VERIFIED
            and run.verification is not None
            and run.quality_review is not None
            and run.verification_error_code is None
            and run.quality_review_error_code in {None, "retry_budget_exhausted"}
            and run.quality_review_state
            in {
                VideoQualityReviewState.PASSED,
                VideoQualityReviewState.REQUIRES_HUMAN_REVIEW,
            }
        )
        if not ready_for_human_review or (
            self.quality_review_enabled() and not automated_review_ready
        ):
            raise MediaLabVideoError(
                "This generated video is not ready for human review",
                status_code=409,
                code="review_not_ready",
            )
        updated = replace(run, review_state=state, reviewed_at=datetime.now(UTC))
        updated = replace(updated, manifest_ref=self._artifacts.write_manifest(updated))
        await self._repository.save(updated)
        return updated

    async def output_file(self, run_id: str) -> tuple[Path, str]:
        run = await self.get(run_id)
        if run.generation_state != VideoGenerationState.SUCCEEDED or run.output_ref is None:
            raise MediaLabVideoError(
                "Media output is not ready", status_code=409, code="output_not_ready"
            )
        path = self._artifacts.output_path(run.output_ref)
        if not path.is_file() or run.output_content_type is None:
            raise MediaLabVideoError(
                "Media output is unavailable", status_code=404, code="output_missing"
            )
        return path, run.output_content_type

    async def review_frame_file(self, run_id: str, frame_index: int) -> tuple[Path, str]:
        run = await self.get(run_id)
        frames = run.verification_frames
        if not frames and run.quality_review is not None:
            frames = run.quality_review.sampled_frames
        if frame_index < 1 or frame_index > len(frames):
            raise MediaLabVideoError(
                "Media Lab review frame is unavailable",
                status_code=404,
                code="review_frame_missing",
            )
        path = self._artifacts.output_path(frames[frame_index - 1].artifact_ref)
        if not path.is_file():
            raise MediaLabVideoError(
                "Media Lab review frame is unavailable",
                status_code=404,
                code="review_frame_missing",
            )
        content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return path, content_type

    async def source_file(self, run_id: str, source_index: int) -> tuple[Path, str]:
        run = await self.get(run_id)
        if source_index < 1 or source_index > len(run.sources):
            raise MediaLabVideoError(
                "Media Lab video source is unavailable",
                status_code=404,
                code="source_missing",
            )
        source = run.sources[source_index - 1]
        path = self._artifacts.output_path(source.artifact_ref)
        if not path.is_file():
            raise MediaLabVideoError(
                "Media Lab video source is unavailable",
                status_code=404,
                code="source_missing",
            )
        return path, source.content_type

    async def observe_backend_update(self, update: VideoBackendUpdate) -> None:
        run_id = self._backend_run_ids.get(update.backend_run_id)
        if run_id is None:
            return
        run = await self._repository.get(run_id)
        if run is None or run.generation_state not in {
            VideoGenerationState.QUEUED,
            VideoGenerationState.RUNNING,
        }:
            return
        if update.state == VideoGenerationState.RUNNING:
            updated = replace(
                run,
                generation_state=VideoGenerationState.RUNNING,
                provider_job_id=update.provider_job_id,
                started_at=update.started_at,
            )
        elif update.state == VideoGenerationState.SUCCEEDED:
            updated = await self._complete_output(run, update)
            await self._repository.save(updated)
            if updated.verification_state != VideoVerificationState.NOT_REQUESTED:
                updated = await self._verify_and_review(updated)
        elif update.state in {VideoGenerationState.FAILED, VideoGenerationState.INTERRUPTED}:
            updated = replace(
                run,
                generation_state=update.state,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                error_code=update.error_code,
            )
        else:
            return
        updated = replace(
            updated,
            queue_wait_milliseconds=update.queue_wait_milliseconds,
            provider_delay_milliseconds=update.provider_delay_milliseconds,
            provider_execution_milliseconds=update.provider_execution_milliseconds,
        )
        await self._repository.save(updated)

    async def _persist_sources(
        self,
        run_id: str,
        inputs: tuple[VideoImageSourceInput, ...],
    ) -> tuple[tuple[VideoSource, ...], tuple[ImageBinary, ...]]:
        sources: list[VideoSource] = []
        materials: list[ImageBinary] = []
        for item in sorted(inputs, key=lambda value: value.source_index):
            source_id = uuid4().hex
            image, source_run_id = await self._resolve_input(item)
            artifact_ref, checksum = self._artifacts.write_source(run_id, source_id, image)
            sources.append(
                VideoSource(
                    source_id=source_id,
                    source_index=item.source_index,
                    role=item.role,
                    usage=item.usage,
                    priority=item.priority,
                    must_preserve=item.must_preserve,
                    allowed_changes=item.allowed_changes,
                    source_origin=item.source_origin,
                    source_checksum_sha256=checksum,
                    artifact_ref=artifact_ref,
                    content_type=image.content_type,
                    source_run_id=source_run_id,
                    identity_group=item.identity_group,
                    is_primary_identity=item.is_primary_identity,
                    asset_id=item.asset_id,
                )
            )
            if item.usage in {VideoSourceUsage.GENERATION, VideoSourceUsage.BOTH}:
                materials.append(image)
        return tuple(sources), tuple(materials)

    async def _resolve_input(
        self,
        item: VideoImageSourceInput,
    ) -> tuple[ImageBinary, str | None]:
        if item.source_origin == VideoSourceOrigin.UPLOAD:
            if item.binary is None or item.source_run_id is not None:
                raise MediaLabVideoError(
                    "Uploaded image source is invalid", code="invalid_reference"
                )
            return item.binary, None
        if item.source_origin != VideoSourceOrigin.MEDIA_LAB_IMAGE_OUTPUT:
            raise MediaLabVideoError("Video source origin is invalid", code="invalid_reference")
        if item.source_run_id is None:
            raise MediaLabVideoError(
                "A prior Media Lab image source is invalid", code="invalid_reference"
            )
        if item.binary is not None:
            return item.binary, item.source_run_id
        try:
            source_path, content_type = await self._image_source.output_file(item.source_run_id)
        except MediaLabImageError as error:
            raise MediaLabVideoError(
                "The selected Media Lab image output is not ready",
                status_code=error.status_code,
                code=error.code,
            ) from error
        if content_type not in {"image/png", "image/jpeg"}:
            raise MediaLabVideoError("The selected image source is invalid", code="source_missing")
        try:
            content = await asyncio.to_thread(source_path.read_bytes)
        except OSError as error:
            raise MediaLabVideoError(
                "The selected image source is unavailable", code="source_missing"
            ) from error
        extension = ".png" if content_type == "image/png" else ".jpg"
        return ImageBinary(content, extension, content_type), item.source_run_id

    async def _complete_output(self, run: VideoRun, update: VideoBackendUpdate) -> VideoRun:
        if update.output_path is None or update.output_content_type != "video/mp4":
            return replace(
                run,
                generation_state=VideoGenerationState.FAILED,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                error_code="output_missing",
            )
        try:
            content = await asyncio.to_thread(update.output_path.read_bytes)
        except OSError:
            return replace(
                run,
                generation_state=VideoGenerationState.FAILED,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                error_code="output_missing",
            )
        output_ref, checksum = self._artifacts.write_output(run.run_id, content)
        output_asset_id = None
        actual_width = None
        actual_height = None
        actual_duration_milliseconds = None
        if self._media_assets is not None:
            try:
                output_asset = await self._media_assets.register_generated_video(
                    content,
                    source_run_id=run.run_id,
                    parent_asset_ids=tuple(
                        dict.fromkeys(
                            source.asset_id for source in run.sources if source.asset_id is not None
                        )
                    ),
                )
            except (MediaAssetError, OSError):
                failed = replace(
                    run,
                    generation_state=VideoGenerationState.FAILED,
                    completed_at=update.completed_at or datetime.now(UTC),
                    provider_job_id=update.provider_job_id,
                    output_ref=output_ref,
                    output_checksum_sha256=checksum,
                    output_content_type=update.output_content_type,
                    error_code="asset_persistence_failed",
                )
                return self._write_manifest(failed)
            output_asset_id = output_asset.asset_id
            actual_width = output_asset.width
            actual_height = output_asset.height
            actual_duration_milliseconds = output_asset.duration_milliseconds
        review_enabled = bool(run.verification_plan) and self.quality_review_enabled()
        return self._write_manifest(
            replace(
                run,
                generation_state=VideoGenerationState.SUCCEEDED,
                review_state=(
                    VideoReviewState.NOT_READY
                    if review_enabled
                    else VideoReviewState.AWAITING_HUMAN_REVIEW
                ),
                quality_review_state=(
                    VideoQualityReviewState.REVIEWING
                    if review_enabled
                    and self._quality_reviewer is not None
                    and self._evidence_verifier is not None
                    else (
                        VideoQualityReviewState.UNAVAILABLE
                        if review_enabled and self._quality_reviewer is None
                        else VideoQualityReviewState.NOT_REQUESTED
                    )
                ),
                quality_review_error_code=(
                    "quality_review_not_configured"
                    if review_enabled and self._quality_reviewer is None
                    else None
                ),
                verification_state=(
                    VideoVerificationState.VERIFYING
                    if review_enabled and self._evidence_verifier is not None
                    else (
                        VideoVerificationState.FAILED
                        if review_enabled
                        else VideoVerificationState.NOT_REQUESTED
                    )
                ),
                verification_error_code=(
                    "verification_not_configured"
                    if review_enabled and self._evidence_verifier is None
                    else None
                ),
                started_at=update.started_at or run.started_at,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                output_ref=output_ref,
                output_checksum_sha256=checksum,
                output_content_type=update.output_content_type,
                output_asset_id=output_asset_id,
                actual_width=actual_width,
                actual_height=actual_height,
                actual_duration_milliseconds=actual_duration_milliseconds,
                error_code=None,
            )
        )

    async def _verify_and_review(self, run: VideoRun) -> VideoRun:
        if self._evidence_verifier is None:
            return self._write_manifest(run)
        try:
            evidence, sampled_frames = await self._sample_temporal_evidence(run)
        except Exception as error:  # noqa: BLE001 - persist asynchronous verifier failures
            return self._verification_failed(run, error)

        sampling_complete = self._write_manifest(
            replace(
                run,
                verification_state=VideoVerificationState.VERIFYING,
                verification_frames=sampled_frames,
                verification_error_code=None,
            )
        )
        await self._repository.save(sampling_complete)
        try:
            verification = await self._evidence_verifier.verify(
                self._verification_request(sampling_complete)
            )
        except Exception as error:  # noqa: BLE001 - persist asynchronous verifier failures
            return self._verification_failed(sampling_complete, error)

        if any(
            stage.status == VideoVerificationStatus.UNAVAILABLE for stage in verification.stages
        ):
            return self._verification_report_failed(sampling_complete, verification)

        verified = self._write_manifest(
            replace(
                sampling_complete,
                verification_state=VideoVerificationState.VERIFIED,
                verification=verification,
                verification_error_code=None,
            )
        )
        await self._repository.save(verified)
        if verification.suspicious_timestamps_milliseconds and hasattr(
            self._frame_sampler, "sample_at"
        ):
            try:
                targeted = await asyncio.to_thread(
                    self._frame_sampler.sample_at,
                    self._artifacts.output_path(verified.output_ref or ""),
                    tuple(
                        timestamp / 1_000
                        for timestamp in verification.suspicious_timestamps_milliseconds
                    ),
                )
                evidence = _merge_temporal_evidence(evidence, targeted)
                verified = self._write_manifest(
                    replace(
                        verified,
                        verification_frames=self._persist_review_frames(verified.run_id, evidence),
                    )
                )
                await self._repository.save(verified)
            except Exception as error:  # noqa: BLE001 - preserve verifier report and expose review failure
                return self._quality_review_failed(verified, error)
        return await self._run_quality_review(verified, evidence)

    async def _sample_temporal_evidence(
        self,
        run: VideoRun,
    ) -> tuple[VideoTemporalEvidence, tuple[VideoReviewFrame, ...]]:
        if self._frame_sampler is None or run.output_ref is None:
            raise MediaLabVideoQualityReviewError(
                "Media Lab video frame sampling is not configured",
                code="frame_sampling_unavailable",
            )
        evidence = await asyncio.to_thread(
            self._frame_sampler.sample,
            self._artifacts.output_path(run.output_ref),
        )
        if not evidence.frames:
            raise MediaLabVideoQualityReviewError(
                "Media Lab video frame sampling returned no frames",
                code="frame_sampling_failed",
            )
        return evidence, self._persist_review_frames(run.run_id, evidence)

    def _persist_review_frames(
        self,
        run_id: str,
        evidence: VideoTemporalEvidence,
    ) -> tuple[VideoReviewFrame, ...]:
        frames: list[VideoReviewFrame] = []
        for index, frame in enumerate(evidence.frames, start=1):
            artifact_ref, checksum = self._artifacts.write_review_frame(run_id, index, frame.image)
            frames.append(
                VideoReviewFrame(
                    label=frame.label,
                    timestamp_milliseconds=frame.timestamp_milliseconds,
                    artifact_ref=artifact_ref,
                    checksum_sha256=checksum,
                )
            )
        return tuple(frames)

    def _verification_request(self, run: VideoRun) -> VideoEvidenceVerificationRequest:
        if run.output_ref is None:
            raise MediaLabVideoQualityReviewError(
                "Media Lab video output is unavailable for verification",
                code="output_missing",
            )
        images = tuple(
            VideoVerificationImage(
                source_id=source.source_id,
                role=source.role,
                image=ImageBinary(
                    self._artifacts.read(source.artifact_ref),
                    _image_extension(source.content_type),
                    source.content_type,
                ),
                checksum_sha256=source.source_checksum_sha256,
                must_preserve=source.must_preserve,
                artifact_ref=source.artifact_ref,
                source_origin=source.source_origin,
                identity_group=source.identity_group,
                is_primary_identity=source.is_primary_identity,
            )
            for source in run.sources
            if source.usage in {VideoSourceUsage.VERIFICATION, VideoSourceUsage.BOTH}
        )
        return VideoEvidenceVerificationRequest(
            run_id=run.run_id,
            video_path=self._artifacts.output_path(run.output_ref),
            video_checksum_sha256=run.output_checksum_sha256 or "",
            production_prompt=run.rendered_prompt,
            expected_duration_seconds=run.output_spec.duration_seconds,
            sources=images,
            selected_stages=tuple(item.stage for item in run.verification_plan),
        )

    async def _run_quality_review(
        self,
        run: VideoRun,
        evidence: VideoTemporalEvidence,
    ) -> VideoRun:
        reviewer = self._quality_reviewer
        if reviewer is None:
            return self._write_manifest(
                replace(
                    run,
                    quality_review_state=VideoQualityReviewState.UNAVAILABLE,
                    quality_review_error_code="quality_review_not_configured",
                    review_state=VideoReviewState.NOT_READY,
                )
            )
        try:
            request = self._quality_review_request(run, evidence)
            review = replace(
                await reviewer.review(request),
                sampled_frames=run.verification_frames,
                temporal_sampling_rate_fps=evidence.sampling_rate_fps,
                temporal_duration_milliseconds=evidence.duration_milliseconds,
                verification=run.verification,
            )
            review = _apply_verification_policy(review, run.verification)
            review = _with_review_hash(review)
        except Exception as error:  # noqa: BLE001 - preserve specialized evidence at the async boundary
            return self._quality_review_failed(run, error)

        reviewed = self._write_manifest(
            replace(
                run,
                quality_review=review,
                quality_review_error_code=None,
            )
        )
        await self._repository.save(reviewed)
        if review.decision == VideoQualityDecision.PASS:
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=VideoQualityReviewState.PASSED,
                    review_state=VideoReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        if review.decision == VideoQualityDecision.HUMAN_REVIEW:
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=VideoQualityReviewState.REQUIRES_HUMAN_REVIEW,
                    review_state=VideoReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        if run.regeneration_count >= reviewer.max_regenerations:
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=VideoQualityReviewState.REQUIRES_HUMAN_REVIEW,
                    quality_review_error_code="retry_budget_exhausted",
                    review_state=VideoReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        try:
            repaired = await reviewer.repair_prompt(request, review)
            if repaired.repair_prompt is None:
                raise MediaLabVideoQualityReviewError(
                    "Terra did not return a replacement Media Lab video prompt",
                    code="invalid_provider_output",
                )
            child = await self.create(
                await self._regeneration_command(
                    run,
                    repaired.repair_prompt,
                    _next_retry_memory(run, repaired),
                ),
                retry_of_run_id=run.run_id,
                regeneration_count=run.regeneration_count + 1,
            )
        except Exception as error:  # noqa: BLE001 - persist review/repair failures
            return self._quality_review_failed(reviewed, error)
        return self._write_manifest(
            replace(
                reviewed,
                quality_review=repaired,
                quality_review_state=VideoQualityReviewState.REGENERATING,
                regenerated_run_id=child.run_id,
                review_state=VideoReviewState.NOT_READY,
            )
        )

    def _quality_review_request(
        self,
        run: VideoRun,
        evidence: VideoTemporalEvidence,
    ) -> VideoQualityReviewRequest:
        sources = tuple(
            VideoQualityReviewSource(
                label=f"source:{source.source_index}",
                role=source.role,
                usage=source.usage,
                must_preserve=source.must_preserve,
                allowed_changes=source.allowed_changes,
                image=ImageBinary(
                    self._artifacts.read(source.artifact_ref),
                    _image_extension(source.content_type),
                    source.content_type,
                ),
                source_id=source.source_id,
                identity_group=source.identity_group,
                is_primary_identity=source.is_primary_identity,
            )
            for source in run.sources
        )
        return VideoQualityReviewRequest(
            run_id=run.run_id,
            user_request=run.orchestration.user_request if run.orchestration else None,
            production_prompt=run.rendered_prompt,
            candidate_evidence=evidence,
            sources=sources,
            verification=run.verification,
            retry_memory=run.retry_memory,
        )

    def _verification_failed(self, run: VideoRun, error: Exception) -> VideoRun:
        error_code = _quality_error_code(error)
        logger.warning(
            "Media Lab specialized video verification failed for {}: type={}, code={}",
            run.run_id,
            type(error).__name__,
            error_code,
        )
        return self._write_manifest(
            replace(
                run,
                verification_state=VideoVerificationState.FAILED,
                verification_error_code=error_code,
                quality_review_state=VideoQualityReviewState.NOT_REQUESTED,
                review_state=VideoReviewState.NOT_READY,
            )
        )

    def _verification_report_failed(
        self,
        run: VideoRun,
        verification: VideoVerificationReport,
    ) -> VideoRun:
        logger.warning(
            "Media Lab specialized video verification returned an unavailable stage for {}",
            run.run_id,
        )
        return self._write_manifest(
            replace(
                run,
                verification_state=VideoVerificationState.FAILED,
                verification=verification,
                verification_error_code="verification_stage_unavailable",
                quality_review_state=VideoQualityReviewState.NOT_REQUESTED,
                review_state=VideoReviewState.NOT_READY,
            )
        )

    def _quality_review_failed(self, run: VideoRun, error: Exception) -> VideoRun:
        error_code = _quality_error_code(error)
        logger.warning(
            "Media Lab Terra video quality review failed for {}: type={}, code={}",
            run.run_id,
            type(error).__name__,
            error_code,
        )
        return self._write_manifest(
            replace(
                run,
                quality_review_state=VideoQualityReviewState.UNAVAILABLE,
                quality_review_error_code=error_code,
                review_state=VideoReviewState.NOT_READY,
            )
        )

    async def _regeneration_command(
        self,
        run: VideoRun,
        prompt: str,
        retry_memory: VideoRetryMemory,
    ) -> CreateVideoCommand:
        sources: list[VideoImageSourceInput] = []
        for source in run.sources:
            if source.source_origin == VideoSourceOrigin.MEDIA_LAB_IMAGE_OUTPUT:
                sources.append(
                    VideoImageSourceInput(
                        source_index=source.source_index,
                        role=source.role,
                        usage=source.usage,
                        priority=source.priority,
                        must_preserve=source.must_preserve,
                        allowed_changes=source.allowed_changes,
                        source_origin=source.source_origin,
                        source_run_id=source.source_run_id,
                        identity_group=source.identity_group,
                        is_primary_identity=source.is_primary_identity,
                        asset_id=source.asset_id,
                    )
                )
                continue
            sources.append(
                VideoImageSourceInput(
                    source_index=source.source_index,
                    role=source.role,
                    usage=source.usage,
                    priority=source.priority,
                    must_preserve=source.must_preserve,
                    allowed_changes=source.allowed_changes,
                    source_origin=VideoSourceOrigin.UPLOAD,
                    identity_group=source.identity_group,
                    is_primary_identity=source.is_primary_identity,
                    binary=ImageBinary(
                        self._artifacts.read(source.artifact_ref),
                        _image_extension(source.content_type),
                        source.content_type,
                    ),
                    asset_id=source.asset_id,
                )
            )
        return CreateVideoCommand(
            intent=run.intent,
            prompt=prompt,
            sources=tuple(sources),
            duration_seconds=run.output_spec.duration_seconds,
            seed=None,
            orchestration=run.orchestration,
            verification_plan=run.verification_plan,
            output_preset_id=run.output_spec.preset_id,
            output_format=run.output_spec.output_format,
            retry_memory=retry_memory,
        )

    def _write_manifest(self, run: VideoRun) -> VideoRun:
        return replace(run, manifest_ref=self._artifacts.write_manifest(run))


def _resolve_capability(
    command: CreateVideoCommand,
    capabilities: tuple[VideoCapability, ...],
) -> VideoCapability:
    source_indexes = tuple(item.source_index for item in command.sources)
    if source_indexes != tuple(range(len(command.sources))):
        raise MediaLabVideoError(
            "Video sources must keep consecutive prepared indexes", code="invalid_sources"
        )
    for item in command.sources:
        if item.priority < 1 or item.priority > 100:
            raise MediaLabVideoError(
                "Source priority must be between 1 and 100", code="invalid_priority"
            )
        if (
            item.usage in {VideoSourceUsage.VERIFICATION, VideoSourceUsage.BOTH}
            and not item.must_preserve
        ):
            raise MediaLabVideoError(
                "A verification source requires preservation constraints",
                code="missing_preservation_constraint",
            )
    generation_count = sum(
        item.usage in {VideoSourceUsage.GENERATION, VideoSourceUsage.BOTH}
        for item in command.sources
    )
    for capability in capabilities:
        if (
            command.intent == capability.intent
            and capability.minimum_generation_images
            <= generation_count
            <= capability.maximum_generation_images
        ):
            if (
                command.orchestration is not None
                and command.orchestration.capability_id != capability.capability_id
            ):
                raise MediaLabVideoError(
                    "The orchestration plan does not match the submitted video capability",
                    code="orchestration_mismatch",
                )
            selected_stages = tuple(item.stage for item in command.verification_plan)
            if (
                len(set(selected_stages)) != len(selected_stages)
                or VideoVerificationStage.TECHNICAL in selected_stages
                or (
                    not command.technical_only
                    and VideoVerificationStage.TEMPORAL_QUALITY not in selected_stages
                )
                or (
                    VideoVerificationStage.PRODUCT_FIDELITY in selected_stages
                    and VideoVerificationStage.TRACKING not in selected_stages
                )
            ):
                raise MediaLabVideoError(
                    "The submitted verification plan is invalid",
                    code="invalid_verification_plan",
                )

            identity_roles = {VideoSourceRole.PRODUCT, VideoSourceRole.CHARACTER}
            for item in command.sources:
                if item.role in identity_roles and not item.identity_group:
                    raise MediaLabVideoError(
                        "Product and character sources require an identity group",
                        code="invalid_identity_contract",
                    )
                if item.role not in identity_roles and (
                    item.identity_group is not None or item.is_primary_identity
                ):
                    raise MediaLabVideoError(
                        "Identity metadata is only valid for product or character sources",
                        code="invalid_identity_contract",
                    )
                if item.is_primary_identity and item.usage not in {
                    VideoSourceUsage.VERIFICATION,
                    VideoSourceUsage.BOTH,
                }:
                    raise MediaLabVideoError(
                        "A primary identity must be used for verification",
                        code="invalid_identity_contract",
                    )

            tracking_sources = tuple(
                item
                for item in command.sources
                if item.role in identity_roles
                and item.usage in {VideoSourceUsage.VERIFICATION, VideoSourceUsage.BOTH}
            )
            primary_sources = tuple(item for item in tracking_sources if item.is_primary_identity)
            if VideoVerificationStage.TRACKING in selected_stages:
                primary_groups = {item.identity_group for item in primary_sources}
                primary_roles = {item.role for item in primary_sources}
                if (
                    not primary_sources
                    or len(primary_groups) != 1
                    or None in primary_groups
                    or len(primary_roles) != 1
                    or any(not item.is_primary_identity for item in tracking_sources)
                ):
                    raise MediaLabVideoError(
                        "Tracking requires exactly one primary product or character identity group",
                        code="invalid_verification_source",
                    )
            elif any(item.is_primary_identity for item in command.sources):
                raise MediaLabVideoError(
                    "A primary identity requires tracking verification",
                    code="invalid_verification_plan",
                )

            if VideoVerificationStage.PRODUCT_FIDELITY in selected_stages and (
                not primary_sources
                or any(
                    item.role != VideoSourceRole.PRODUCT
                    or item.source_origin != VideoSourceOrigin.UPLOAD
                    for item in primary_sources
                )
            ):
                raise MediaLabVideoError(
                    "Product fidelity requires one primary original uploaded product identity",
                    code="invalid_verification_source",
                )
            return capability
    raise MediaLabVideoError(
        "This source plan is not supported by the pinned ML2 graphs",
        code="unsupported_capability",
    )


def _resolve_output_spec(
    command: CreateVideoCommand, capability: VideoCapability
) -> VideoOutputSpec:
    if command.duration_seconds not in capability.supported_duration_seconds:
        raise MediaLabVideoError(
            "Video duration is not supported by the pinned graph", code="duration_not_supported"
        )
    if command.output_format not in capability.supported_output_formats:
        raise MediaLabVideoError(
            "The requested video format is not supported by the pinned graph",
            code="format_not_supported",
        )
    preset_id = command.output_preset_id or capability.default_output_preset_id
    preset = next(
        (item for item in capability.output_presets if item.preset_id == preset_id),
        None,
    )
    if preset is None:
        raise MediaLabVideoError(
            "The requested video output preset is not supported by the pinned graph",
            code="output_preset_not_supported",
        )
    return VideoOutputSpec(
        duration_seconds=command.duration_seconds,
        preset_id=preset.preset_id,
        aspect_ratio=preset.aspect_ratio,
        megapixels=preset.megapixels,
        output_format=command.output_format,
    )


def _selector_aspect_ratio(output_spec: VideoOutputSpec) -> str | None:
    preset = next(
        (item for item in _VIDEO_OUTPUT_PRESETS if item.preset_id == output_spec.preset_id),
        None,
    )
    return preset.selector_aspect_ratio if preset is not None else None


def _next_retry_memory(
    run: VideoRun,
    review: VideoQualityReview,
) -> VideoRetryMemory:
    prior_attempts = run.retry_memory.attempts if run.retry_memory is not None else ()
    attempt = VideoRetryAttempt(
        run_id=run.run_id,
        seed=run.seed,
        production_prompt=run.prompt,
        output_asset_id=run.output_asset_id,
        output_checksum_sha256=run.output_checksum_sha256,
        duration_seconds=run.output_spec.duration_seconds,
        output_preset_id=run.output_spec.preset_id,
        review_decision=review.decision,
        review_summary=review.summary,
        repair_instructions=review.repair_instructions,
        repair_prompt=review.repair_prompt,
        verifier_status=run.verification.status if run.verification is not None else None,
        suspicious_timestamps_milliseconds=(
            run.verification.suspicious_timestamps_milliseconds
            if run.verification is not None
            else ()
        ),
    )
    return VideoRetryMemory(
        root_run_id=(run.retry_memory.root_run_id if run.retry_memory is not None else run.run_id),
        attempts=(*prior_attempts, attempt),
    )


def _retry_root(run: VideoRun, runs: dict[str, VideoRun]) -> VideoRun:
    current = run
    visited: set[str] = set()
    while current.retry_of_run_id is not None:
        if current.run_id in visited:
            raise MediaLabVideoError(
                "Video regeneration lineage contains a cycle",
                status_code=409,
                code="invalid_retry_lineage",
            )
        visited.add(current.run_id)
        parent = runs.get(current.retry_of_run_id)
        if parent is None:
            raise MediaLabVideoError(
                "Video regeneration lineage is incomplete",
                status_code=409,
                code="invalid_retry_lineage",
            )
        current = parent
    return current


def _render_prompt(prompt: str, sources: tuple[VideoSource, ...]) -> str:
    lines = [prompt.strip()]
    generation_sources = tuple(
        source
        for source in sources
        if source.usage in {VideoSourceUsage.GENERATION, VideoSourceUsage.BOTH}
    )
    if generation_sources:
        lines.append("Resolved generation source contract:")
    for source in generation_sources:
        line = f"- source {source.source_index}: {source.role.value} (priority {source.priority})"
        if source.identity_group:
            line += f"; identity group: {source.identity_group}"
        if source.is_primary_identity:
            line += "; primary verification identity"
        if source.must_preserve:
            line += f"; must preserve: {', '.join(source.must_preserve)}"
        if source.allowed_changes:
            line += f"; allowed changes: {', '.join(source.allowed_changes)}"
        lines.append(line)
    return "\n".join(lines)


def _image_extension(content_type: str) -> str:
    return ".png" if content_type == "image/png" else ".jpg"


def _quality_error_code(error: Exception) -> str:
    if isinstance(error, MediaLabVideoQualityReviewError):
        return error.code
    if isinstance(error, MediaLabVideoError):
        return error.code
    if isinstance(error, FileNotFoundError):
        return "artifact_missing"
    if isinstance(error, OSError):
        return "artifact_unavailable"
    return "quality_review_failed"


def _apply_verification_policy(
    review: VideoQualityReview,
    verification: VideoVerificationReport | None,
) -> VideoQualityReview:
    if verification is None or verification.status == VideoVerificationStatus.PASS:
        return review
    if (
        verification.status == VideoVerificationStatus.FAIL
        and review.decision == VideoQualityDecision.REGENERATE
    ):
        return review
    reason = (
        "The specialized video verifier returned "
        f"{verification.status.value}; human review is required before approval."
    )
    issue = VideoQualityIssue(
        category="specialized_verification_uncertain",
        severity=VideoQualityIssueSeverity.CRITICAL,
        description=reason,
    )
    uncertainties = tuple(dict.fromkeys((*review.uncertainties, reason)))
    return replace(
        review,
        decision=VideoQualityDecision.HUMAN_REVIEW,
        summary=f"{review.summary} {reason}",
        issues=(*review.issues, issue),
        uncertainties=uncertainties,
    )


def _with_review_hash(review: VideoQualityReview) -> VideoQualityReview:
    payload = {
        "decision": review.decision.value,
        "summary": review.summary,
        "issues": [
            {
                "category": issue.category,
                "severity": issue.severity.value,
                "description": issue.description,
            }
            for issue in review.issues
        ],
        "repair_instructions": list(review.repair_instructions),
        "uncertainties": list(review.uncertainties),
    }
    review_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return replace(review, review_hash=review_hash)


def _merge_temporal_evidence(
    base: VideoTemporalEvidence,
    extra: VideoTemporalEvidence,
) -> VideoTemporalEvidence:
    frames = {frame.timestamp_milliseconds: frame for frame in base.frames}
    frames.update({frame.timestamp_milliseconds: frame for frame in extra.frames})
    ordered_frames = tuple(frames[key] for key in sorted(frames))
    return VideoTemporalEvidence(
        sampling_rate_fps=base.sampling_rate_fps,
        duration_milliseconds=max(base.duration_milliseconds, extra.duration_milliseconds),
        frames=tuple(
            replace(frame, label=f"candidate_frame_{index:03d}")
            for index, frame in enumerate(ordered_frames, start=1)
        ),
    )


__all__ = ["MediaLabVideoService", "build_video_capabilities"]
