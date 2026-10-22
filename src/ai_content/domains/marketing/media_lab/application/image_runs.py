"""Create Image orchestration for the bounded Media Lab ML1 slice."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger

from ..domain.models import (
    CreateImageCommand,
    ImageBinary,
    ImageCapability,
    ImageGenerationState,
    ImageIntent,
    ImageOutputFormat,
    ImageOutputPreset,
    ImageOutputSpec,
    ImageQualityDecision,
    ImageQualityReview,
    ImageQualityReviewRequest,
    ImageQualityReviewSource,
    ImageQualityReviewState,
    ImageReference,
    ImageReferenceInput,
    ImageReferenceRole,
    ImageRetryAttempt,
    ImageRetryMemory,
    ImageReviewState,
    ImageRun,
    ImageSourceOrigin,
)
from ..ports.assets import IGeneratedMediaAssetWriter, MediaAssetError
from ..ports.interfaces import (
    IImageArtifactStore,
    IImageGenerationBackend,
    IImageQualityReviewer,
    IImageRunRepository,
    ImageBackendUpdate,
    MediaLabImageError,
    MediaLabImageOrchestrationError,
    MediaLabImageQualityReviewError,
    PinnedImageGeneration,
    PinnedImageGraph,
)


def build_image_capabilities(generator: IImageGenerationBackend) -> tuple[ImageCapability, ...]:
    return _build_capabilities(
        generator.pinned_image_input_capacity(PinnedImageGraph.MULTI_REFERENCE)
    )


_IMAGE_OUTPUT_PRESETS = (
    ImageOutputPreset("square_2mp", "Standard - Square 1:1", "1:1", 1440, 1440),
    ImageOutputPreset("portrait_4_5_2mp", "Standard - Portrait 4:5", "4:5", 1280, 1600),
    ImageOutputPreset("portrait_3_4_2mp", "Standard - Portrait 3:4", "3:4", 1248, 1664),
    ImageOutputPreset("portrait_9_16_2mp", "Standard - Vertical 9:16", "9:16", 1088, 1920),
    ImageOutputPreset("landscape_16_9_2mp", "Standard - Landscape 16:9", "16:9", 1920, 1088),
    ImageOutputPreset("square_4mp", "High resolution - Square 1:1", "1:1", 2048, 2048),
    ImageOutputPreset("portrait_4_5_4mp", "High resolution - Portrait 4:5", "4:5", 1792, 2240),
    ImageOutputPreset("portrait_3_4_4mp", "High resolution - Portrait 3:4", "3:4", 1728, 2304),
    ImageOutputPreset("portrait_9_16_4mp", "High resolution - Vertical 9:16", "9:16", 1440, 2560),
    ImageOutputPreset("landscape_16_9_4mp", "High resolution - Landscape 16:9", "16:9", 2560, 1440),
)

# Keep accepting the original preset IDs without advertising them in the canonical UI.
_LEGACY_IMAGE_OUTPUT_PRESETS = (
    ImageOutputPreset("square_1024", "Square 1:1", "1:1", 1024, 1024),
    ImageOutputPreset("portrait_4_5", "Portrait 4:5", "4:5", 1024, 1280),
    ImageOutputPreset("portrait_3_4", "Portrait 3:4", "3:4", 1152, 1536),
    ImageOutputPreset("portrait_9_16", "Vertical 9:16", "9:16", 864, 1536),
    ImageOutputPreset("landscape_16_9", "Landscape 16:9", "16:9", 1536, 864),
)
_IMAGE_OUTPUT_FORMATS = (
    ImageOutputFormat.PNG,
    ImageOutputFormat.JPEG,
    ImageOutputFormat.WEBP,
)


def _build_capabilities(multi_reference_input_capacity: int) -> tuple[ImageCapability, ...]:
    capabilities = [
        ImageCapability(
            capability_id="create_from_text",
            intent=ImageIntent.CREATE_FROM_TEXT,
            label="Create from text",
            description="Create one image from a visual prompt without a reference image.",
            required_roles=(),
            supports_output_size=True,
            maximum_reference_count=0,
            output_presets=_IMAGE_OUTPUT_PRESETS,
            supported_output_formats=_IMAGE_OUTPUT_FORMATS,
        ),
        ImageCapability(
            capability_id="product_source",
            intent=ImageIntent.CREATE_FROM_REFERENCES,
            label="Create from a product source",
            description="Use one confirmed product source as the image reference.",
            required_roles=(ImageReferenceRole.PRODUCT_SOURCE,),
            supports_output_size=False,
            minimum_product_source_count=1,
            maximum_product_source_count=1,
            minimum_reference_count=1,
            maximum_reference_count=1,
            supported_output_formats=_IMAGE_OUTPUT_FORMATS,
        ),
    ]
    if multi_reference_input_capacity >= 2:
        capabilities.extend(
            (
                ImageCapability(
                    capability_id="product_and_style",
                    intent=ImageIntent.CREATE_FROM_REFERENCES,
                    label="Product identity views and style references",
                    description=(
                        "Use one or more views of the same product identity with optional "
                        "style references."
                    ),
                    required_roles=(
                        ImageReferenceRole.PRODUCT_SOURCE,
                        ImageReferenceRole.STYLE_REFERENCE,
                    ),
                    supports_output_size=True,
                    minimum_product_source_count=1,
                    maximum_product_source_count=multi_reference_input_capacity,
                    minimum_reference_count=2,
                    maximum_reference_count=multi_reference_input_capacity,
                    maximum_style_reference_count=multi_reference_input_capacity - 1,
                    output_presets=_IMAGE_OUTPUT_PRESETS,
                    supported_output_formats=_IMAGE_OUTPUT_FORMATS,
                ),
                ImageCapability(
                    capability_id="edit_existing",
                    intent=ImageIntent.EDIT_EXISTING,
                    label="Edit an existing result",
                    description=(
                        "Edit a previous output while retaining one or more original product views."
                    ),
                    required_roles=(
                        ImageReferenceRole.PRODUCT_SOURCE,
                        ImageReferenceRole.PREVIOUS_OUTPUT,
                    ),
                    supports_output_size=True,
                    minimum_product_source_count=1,
                    maximum_product_source_count=multi_reference_input_capacity - 1,
                    minimum_reference_count=2,
                    maximum_reference_count=multi_reference_input_capacity,
                    output_presets=_IMAGE_OUTPUT_PRESETS,
                    supported_output_formats=_IMAGE_OUTPUT_FORMATS,
                ),
            )
        )
    return tuple(capabilities)


_GRAPH_BY_CAPABILITY = {
    "create_from_text": PinnedImageGraph.TEXT_TO_IMAGE,
    "product_source": PinnedImageGraph.PRODUCT_IMAGE_EDIT,
    "product_and_style": PinnedImageGraph.MULTI_REFERENCE,
    "edit_existing": PinnedImageGraph.MULTI_REFERENCE,
}


class MediaLabImageService:
    def __init__(
        self,
        repository: IImageRunRepository,
        artifacts: IImageArtifactStore,
        generator: IImageGenerationBackend,
        *,
        quality_reviewer: IImageQualityReviewer | None = None,
        media_assets: IGeneratedMediaAssetWriter | None = None,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._generator = generator
        self._quality_reviewer = quality_reviewer
        self._media_assets = media_assets
        self._capabilities = build_image_capabilities(generator)
        self._backend_run_ids: dict[str, str] = {}
        self._generator.add_image_observer(self.observe_backend_update)

    def capabilities(self) -> tuple[ImageCapability, ...]:
        return self._capabilities

    def capability(self, capability_id: str) -> ImageCapability:
        for capability in self._capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise MediaLabImageError(
            "Media Lab image capability is invalid", code="unsupported_capability"
        )

    def maximum_source_count(self) -> int:
        return max(capability.maximum_reference_count for capability in self._capabilities)

    def enabled(self) -> bool:
        return self._generator.image_generation_available()

    def notice(self) -> str | None:
        return self._generator.image_generation_notice()

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
        command: CreateImageCommand,
        *,
        retry_of_run_id: str | None = None,
        regeneration_count: int = 0,
    ) -> ImageRun:
        if regeneration_count < 0 or (regeneration_count and retry_of_run_id is None):
            raise MediaLabImageError(
                "Image regeneration lineage is invalid", code="invalid_regeneration"
            )
        if not command.prompt.strip():
            raise MediaLabImageError("Visual instruction cannot be blank", code="invalid_prompt")
        capability = _resolve_capability(command, self._capabilities)
        ordered_inputs = _ordered_reference_inputs(command.references, capability)
        if not self.enabled():
            raise MediaLabImageError(
                "Media Lab is not configured", status_code=503, code="not_configured"
            )
        run_id = uuid4().hex
        references, materials, parent_run_id = await self._persist_references(
            run_id, ordered_inputs
        )
        output_spec = _resolve_output_spec(command, capability)
        rendered_prompt = _render_prompt(command.prompt, references)
        now = datetime.now(UTC)
        run = ImageRun(
            run_id=run_id,
            intent=command.intent,
            prompt=command.prompt.strip(),
            rendered_prompt=rendered_prompt,
            references=references,
            output_spec=output_spec,
            seed=command.seed,
            generation_state=ImageGenerationState.QUEUED,
            review_state=ImageReviewState.NOT_READY,
            model=None,
            checkpoint_observation=None,
            graph_template_hash=None,
            backend_run_id=None,
            provider_job_id=None,
            parent_run_id=parent_run_id,
            orchestration=command.orchestration,
            output_ref=None,
            output_checksum_sha256=None,
            output_content_type=None,
            manifest_ref=None,
            error_code=None,
            quality_review_state=ImageQualityReviewState.NOT_REQUESTED,
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
            backend = await self._generator.submit_pinned_image(
                PinnedImageGeneration(
                    graph=_GRAPH_BY_CAPABILITY[capability.capability_id],
                    prompt=rendered_prompt,
                    images=materials,
                    width=output_spec.width,
                    height=output_spec.height,
                    seed=command.seed,
                )
            )
        except Exception:
            await self._repository.save(
                replace(
                    run,
                    generation_state=ImageGenerationState.FAILED,
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

    async def get(self, run_id: str) -> ImageRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise MediaLabImageError(
                "Media Lab image run was not found", status_code=404, code="not_found"
            )
        return run

    async def list(self) -> list[ImageRun]:
        return await self._repository.list()

    async def delete(self, run_id: str) -> None:
        run = await self.get(run_id)
        if run.generation_state in {
            ImageGenerationState.QUEUED,
            ImageGenerationState.RUNNING,
        }:
            raise MediaLabImageError(
                "A running image cannot be removed from Media Library",
                status_code=409,
                code="run_active",
            )
        await self._repository.delete(run_id)

    async def retry_lineage(self, run_id: str) -> tuple[ImageRun, ...]:
        run = await self.get(run_id)
        runs = {item.run_id: item for item in await self._repository.list()}
        root = _retry_root(run, runs)
        children: dict[str, list[ImageRun]] = {}
        for item in runs.values():
            if item.retry_of_run_id is not None:
                children.setdefault(item.retry_of_run_id, []).append(item)

        lineage: list[ImageRun] = []
        pending = [root]
        visited: set[str] = set()
        while pending:
            candidate = pending.pop()
            if candidate.run_id in visited:
                raise MediaLabImageError(
                    "Image regeneration lineage contains a cycle",
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

    async def review(self, run_id: str, state: ImageReviewState) -> ImageRun:
        if state not in {ImageReviewState.APPROVED, ImageReviewState.REJECTED}:
            raise MediaLabImageError("Review decision is invalid", code="invalid_review")
        run = await self.get(run_id)
        if (
            run.generation_state != ImageGenerationState.SUCCEEDED
            or run.review_state != ImageReviewState.AWAITING_HUMAN_REVIEW
        ):
            raise MediaLabImageError(
                "Only a generated image awaiting human review can be reviewed",
                status_code=409,
                code="review_not_ready",
            )
        updated = replace(run, review_state=state, reviewed_at=datetime.now(UTC))
        updated = replace(updated, manifest_ref=self._artifacts.write_manifest(updated))
        await self._repository.save(updated)
        return updated

    async def output_file(self, run_id: str) -> tuple[Path, str]:
        run = await self.get(run_id)
        if run.generation_state != ImageGenerationState.SUCCEEDED or run.output_ref is None:
            raise MediaLabImageError(
                "Media output is not ready", status_code=409, code="output_not_ready"
            )
        artifact_ref = run.delivery_ref or run.output_ref
        content_type = run.delivery_content_type or run.output_content_type
        path = self._artifacts.output_path(artifact_ref)
        if not path.is_file() or content_type is None:
            raise MediaLabImageError(
                "Media output is unavailable", status_code=404, code="output_missing"
            )
        return path, content_type

    async def source_file(self, run_id: str, source_index: int) -> tuple[Path, str]:
        run = await self.get(run_id)
        if source_index < 1 or source_index > len(run.references):
            raise MediaLabImageError(
                "Media Lab image source is unavailable", status_code=404, code="source_missing"
            )
        reference = run.references[source_index - 1]
        path = self._artifacts.output_path(reference.artifact_ref)
        if not path.is_file():
            raise MediaLabImageError(
                "Media Lab image source is unavailable", status_code=404, code="source_missing"
            )
        return path, reference.content_type

    async def review_master_file(self, run_id: str) -> tuple[Path, str]:
        run = await self.get(run_id)
        if run.generation_state != ImageGenerationState.SUCCEEDED or run.output_ref is None:
            raise MediaLabImageError(
                "Media output is not ready", status_code=409, code="output_not_ready"
            )
        path = self._artifacts.output_path(run.output_ref)
        if not path.is_file() or run.output_content_type is None:
            raise MediaLabImageError(
                "Media output is unavailable", status_code=404, code="output_missing"
            )
        return path, run.output_content_type

    async def observe_backend_update(self, update: ImageBackendUpdate) -> None:
        run_id = self._backend_run_ids.get(update.backend_run_id)
        if run_id is None:
            return
        run = await self._repository.get(run_id)
        if run is None or run.generation_state not in {
            ImageGenerationState.QUEUED,
            ImageGenerationState.RUNNING,
        }:
            return
        if update.state == ImageGenerationState.RUNNING:
            updated = replace(
                run,
                generation_state=ImageGenerationState.RUNNING,
                provider_job_id=update.provider_job_id,
                started_at=update.started_at,
            )
        elif update.state == ImageGenerationState.SUCCEEDED:
            updated = await self._complete_output(run, update)
            await self._repository.save(updated)
            if self._quality_reviewer is not None and updated.output_ref is not None:
                updated = await self._run_quality_review(updated)
        elif update.state in {ImageGenerationState.FAILED, ImageGenerationState.INTERRUPTED}:
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

    async def _persist_references(
        self,
        run_id: str,
        inputs: tuple[ImageReferenceInput, ...],
    ) -> tuple[tuple[ImageReference, ...], tuple[ImageBinary, ...], str | None]:
        references: list[ImageReference] = []
        materials: list[ImageBinary] = []
        parent_run_id = None
        for item in inputs:
            reference_id = uuid4().hex
            image, source_run_id = await self._resolve_input(item)
            artifact_ref, checksum = self._artifacts.write_source(run_id, reference_id, image)
            references.append(
                ImageReference(
                    reference_id=reference_id,
                    role=item.role,
                    priority=item.priority,
                    must_preserve=item.must_preserve,
                    allowed_changes=item.allowed_changes,
                    source_origin=item.source_origin,
                    source_checksum_sha256=checksum,
                    artifact_ref=artifact_ref,
                    content_type=image.content_type,
                    source_run_id=source_run_id,
                    asset_id=item.asset_id,
                    identity_group=item.identity_group,
                )
            )
            materials.append(image)
            if item.role == ImageReferenceRole.PREVIOUS_OUTPUT:
                parent_run_id = source_run_id
        return tuple(references), tuple(materials), parent_run_id

    async def _resolve_input(
        self,
        item: ImageReferenceInput,
    ) -> tuple[ImageBinary, str | None]:
        if item.source_origin == ImageSourceOrigin.UPLOAD:
            if item.binary is None or item.source_run_id is not None:
                raise MediaLabImageError(
                    "Uploaded image source is invalid", code="invalid_reference"
                )
            return item.binary, None
        if item.source_origin != ImageSourceOrigin.MEDIA_LAB_OUTPUT:
            raise MediaLabImageError("Image source origin is invalid", code="invalid_reference")
        if item.role != ImageReferenceRole.PREVIOUS_OUTPUT or item.source_run_id is None:
            raise MediaLabImageError(
                "Only a previous output can reference a persisted Media Lab output",
                code="invalid_reference",
            )
        if item.binary is not None:
            return item.binary, item.source_run_id
        source_run = await self.get(item.source_run_id)
        if source_run.generation_state != ImageGenerationState.SUCCEEDED:
            raise MediaLabImageError(
                "The selected previous output is not ready",
                status_code=409,
                code="source_not_ready",
            )
        if source_run.output_ref is None or source_run.output_content_type is None:
            raise MediaLabImageError(
                "The selected previous output is unavailable", code="source_missing"
            )
        try:
            content = self._artifacts.read(source_run.output_ref)
        except FileNotFoundError as error:
            raise MediaLabImageError(
                "The selected previous output is unavailable", code="source_missing"
            ) from error
        extension = ".png" if source_run.output_content_type == "image/png" else ".jpg"
        return ImageBinary(content, extension, source_run.output_content_type), source_run.run_id

    async def _complete_output(self, run: ImageRun, update: ImageBackendUpdate) -> ImageRun:
        if update.output_path is None or update.output_content_type is None:
            return replace(
                run,
                generation_state=ImageGenerationState.FAILED,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                error_code="output_missing",
            )
        try:
            content = await asyncio.to_thread(update.output_path.read_bytes)
        except OSError:
            return replace(
                run,
                generation_state=ImageGenerationState.FAILED,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                error_code="output_missing",
            )
        extension = ".png" if update.output_content_type == "image/png" else ".jpg"
        output_ref, checksum = self._artifacts.write_output(run.run_id, content, extension)
        try:
            delivery_ref, delivery_checksum, delivery_content_type = self._artifacts.write_delivery(
                run.run_id,
                content,
                update.output_content_type,
                run.output_spec.delivery_format,
            )
        except (OSError, ValueError):
            failed = replace(
                run,
                generation_state=ImageGenerationState.FAILED,
                completed_at=update.completed_at or datetime.now(UTC),
                provider_job_id=update.provider_job_id,
                output_ref=output_ref,
                output_checksum_sha256=checksum,
                output_content_type=update.output_content_type,
                error_code="delivery_persistence_failed",
            )
            return replace(failed, manifest_ref=self._artifacts.write_manifest(failed))
        output_asset_id = None
        if self._media_assets is not None:
            try:
                output_asset = await self._media_assets.register_generated_image(
                    content,
                    source_run_id=run.run_id,
                    parent_asset_ids=tuple(
                        dict.fromkeys(
                            reference.asset_id
                            for reference in run.references
                            if reference.asset_id is not None
                        )
                    ),
                )
            except (MediaAssetError, OSError):
                failed = replace(
                    run,
                    generation_state=ImageGenerationState.FAILED,
                    completed_at=update.completed_at or datetime.now(UTC),
                    provider_job_id=update.provider_job_id,
                    output_ref=output_ref,
                    output_checksum_sha256=checksum,
                    output_content_type=update.output_content_type,
                    error_code="asset_persistence_failed",
                )
                return replace(failed, manifest_ref=self._artifacts.write_manifest(failed))
            output_asset_id = output_asset.asset_id
        quality_review_state = (
            ImageQualityReviewState.REVIEWING
            if self._quality_reviewer is not None
            else ImageQualityReviewState.NOT_REQUESTED
        )
        review_state = (
            ImageReviewState.NOT_READY
            if self._quality_reviewer is not None
            else ImageReviewState.AWAITING_HUMAN_REVIEW
        )
        updated = replace(
            run,
            generation_state=ImageGenerationState.SUCCEEDED,
            review_state=review_state,
            quality_review_state=quality_review_state,
            started_at=update.started_at or run.started_at,
            completed_at=update.completed_at or datetime.now(UTC),
            provider_job_id=update.provider_job_id,
            output_ref=output_ref,
            output_checksum_sha256=checksum,
            output_content_type=update.output_content_type,
            output_asset_id=output_asset_id,
            delivery_ref=delivery_ref,
            delivery_checksum_sha256=delivery_checksum,
            delivery_content_type=delivery_content_type,
            error_code=None,
        )
        return replace(updated, manifest_ref=self._artifacts.write_manifest(updated))

    async def _run_quality_review(self, run: ImageRun) -> ImageRun:
        reviewer = self._quality_reviewer
        if reviewer is None:
            return self._write_manifest(
                replace(
                    run,
                    quality_review_state=ImageQualityReviewState.NOT_REQUESTED,
                    review_state=ImageReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        try:
            request = self._quality_review_request(run)
            review = await reviewer.review(request)
        except (
            FileNotFoundError,
            MediaLabImageOrchestrationError,
            MediaLabImageQualityReviewError,
            OSError,
        ) as error:
            logger.warning(
                "Media Lab image quality review unavailable for {}: type={}",
                run.run_id,
                type(error).__name__,
            )
            return self._write_manifest(
                replace(
                    run,
                    quality_review_state=ImageQualityReviewState.UNAVAILABLE,
                    quality_review_error_code=_quality_error_code(error),
                    review_state=ImageReviewState.AWAITING_HUMAN_REVIEW,
                )
            )

        reviewed = self._write_manifest(replace(run, quality_review=review))
        await self._repository.save(reviewed)
        if review.decision == ImageQualityDecision.PASS:
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=ImageQualityReviewState.PASSED,
                    review_state=ImageReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        if review.decision == ImageQualityDecision.HUMAN_REVIEW:
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=ImageQualityReviewState.REQUIRES_HUMAN_REVIEW,
                    review_state=ImageReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        if run.regeneration_count >= reviewer.max_regenerations:
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=ImageQualityReviewState.REQUIRES_HUMAN_REVIEW,
                    quality_review_error_code="retry_budget_exhausted",
                    review_state=ImageReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        try:
            repaired = await reviewer.repair_prompt(request, review)
            if repaired.repair_prompt is None:
                raise MediaLabImageQualityReviewError(
                    "Terra did not return a replacement Media Lab image prompt",
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
        except Exception as error:
            logger.warning(
                "Media Lab image regeneration unavailable for {}: type={}",
                run.run_id,
                type(error).__name__,
            )
            return self._write_manifest(
                replace(
                    reviewed,
                    quality_review_state=ImageQualityReviewState.REQUIRES_HUMAN_REVIEW,
                    quality_review_error_code=_quality_error_code(error),
                    review_state=ImageReviewState.AWAITING_HUMAN_REVIEW,
                )
            )
        return self._write_manifest(
            replace(
                reviewed,
                quality_review=repaired,
                quality_review_state=ImageQualityReviewState.REGENERATING,
                regenerated_run_id=child.run_id,
            )
        )

    def _quality_review_request(self, run: ImageRun) -> ImageQualityReviewRequest:
        if run.output_ref is None or run.output_content_type is None:
            raise FileNotFoundError(run.run_id)
        candidate = ImageBinary(
            self._artifacts.read(run.output_ref),
            _image_extension(run.output_content_type),
            run.output_content_type,
        )
        sources = tuple(
            ImageQualityReviewSource(
                label=f"{reference.role.value}:{index}",
                role=reference.role,
                must_preserve=reference.must_preserve,
                allowed_changes=reference.allowed_changes,
                image=ImageBinary(
                    self._artifacts.read(reference.artifact_ref),
                    _image_extension(reference.content_type),
                    reference.content_type,
                ),
                identity_group=reference.identity_group,
            )
            for index, reference in enumerate(run.references)
        )
        return ImageQualityReviewRequest(
            run_id=run.run_id,
            user_request=run.orchestration.user_request if run.orchestration else None,
            production_prompt=run.prompt,
            candidate=candidate,
            sources=sources,
            retry_memory=run.retry_memory,
        )

    async def _regeneration_command(
        self,
        run: ImageRun,
        prompt: str,
        retry_memory: ImageRetryMemory,
    ) -> CreateImageCommand:
        references: list[ImageReferenceInput] = []
        for reference in run.references:
            if reference.role == ImageReferenceRole.PREVIOUS_OUTPUT:
                references.append(
                    ImageReferenceInput(
                        role=reference.role,
                        priority=reference.priority,
                        must_preserve=reference.must_preserve,
                        allowed_changes=reference.allowed_changes,
                        source_origin=ImageSourceOrigin.MEDIA_LAB_OUTPUT,
                        source_run_id=reference.source_run_id,
                        asset_id=reference.asset_id,
                        identity_group=reference.identity_group,
                    )
                )
                continue
            references.append(
                ImageReferenceInput(
                    role=reference.role,
                    priority=reference.priority,
                    must_preserve=reference.must_preserve,
                    allowed_changes=reference.allowed_changes,
                    source_origin=ImageSourceOrigin.UPLOAD,
                    binary=ImageBinary(
                        self._artifacts.read(reference.artifact_ref),
                        _image_extension(reference.content_type),
                        reference.content_type,
                    ),
                    asset_id=reference.asset_id,
                    identity_group=reference.identity_group,
                )
            )
        return CreateImageCommand(
            intent=run.intent,
            prompt=prompt,
            references=tuple(references),
            width=(run.output_spec.width if run.output_spec.preset_id is None else None),
            height=(run.output_spec.height if run.output_spec.preset_id is None else None),
            # A fresh seed avoids repeating the rejected candidate deterministically.
            seed=None,
            orchestration=run.orchestration,
            output_preset_id=run.output_spec.preset_id,
            output_format=run.output_spec.delivery_format,
            retry_memory=retry_memory,
        )

    def _write_manifest(self, run: ImageRun) -> ImageRun:
        return replace(run, manifest_ref=self._artifacts.write_manifest(run))


def _resolve_capability(
    command: CreateImageCommand,
    capabilities: tuple[ImageCapability, ...],
) -> ImageCapability:
    if any(item.priority < 1 or item.priority > 100 for item in command.references):
        raise MediaLabImageError(
            "Reference priority must be between 1 and 100", code="invalid_priority"
        )
    product_references = tuple(
        item for item in command.references if item.role == ImageReferenceRole.PRODUCT_SOURCE
    )
    for item in product_references:
        if not item.must_preserve:
            raise MediaLabImageError(
                "A product source requires at least one confirmed preservation constraint",
                code="missing_preservation_constraint",
            )
        if not item.identity_group or not item.identity_group.strip():
            raise MediaLabImageError(
                "A product source requires the Terra-resolved identity group",
                code="missing_identity_group",
            )
    if len({item.identity_group for item in product_references}) > 1:
        raise MediaLabImageError(
            "Multiple product sources must belong to the same identity group",
            code="conflicting_identity_group",
        )
    if any(
        item.role != ImageReferenceRole.PRODUCT_SOURCE and item.identity_group is not None
        for item in command.references
    ):
        raise MediaLabImageError(
            "Only product sources can carry an identity group", code="invalid_identity_group"
        )
    roles = tuple(item.role for item in command.references)
    for capability in capabilities:
        if _matches_capability(command.intent, roles, capability):
            if (
                command.orchestration is not None
                and command.orchestration.capability_id != capability.capability_id
            ):
                raise MediaLabImageError(
                    "The orchestration plan does not match the submitted image capability",
                    code="orchestration_mismatch",
                )
            return capability
    raise MediaLabImageError(
        "This intent and reference-role combination is not supported by the pinned ML1 graphs",
        code="unsupported_capability",
    )


def _matches_capability(
    intent: ImageIntent,
    roles: tuple[ImageReferenceRole, ...],
    capability: ImageCapability,
) -> bool:
    if intent != capability.intent:
        return False
    product_count = roles.count(ImageReferenceRole.PRODUCT_SOURCE)
    style_count = roles.count(ImageReferenceRole.STYLE_REFERENCE)
    previous_count = roles.count(ImageReferenceRole.PREVIOUS_OUTPUT)
    allowed_roles = set(capability.required_roles)
    if any(role not in allowed_roles for role in roles):
        return False
    if not (
        capability.minimum_product_source_count
        <= product_count
        <= capability.maximum_product_source_count
    ):
        return False
    if not (
        capability.minimum_style_reference_count
        <= style_count
        <= capability.maximum_style_reference_count
    ):
        return False
    expected_previous_count = int(ImageReferenceRole.PREVIOUS_OUTPUT in allowed_roles)
    if previous_count != expected_previous_count:
        return False
    return capability.minimum_reference_count <= len(roles) <= capability.maximum_reference_count


def _ordered_reference_inputs(
    inputs: tuple[ImageReferenceInput, ...],
    capability: ImageCapability,
) -> tuple[ImageReferenceInput, ...]:
    ordered: list[ImageReferenceInput] = []
    for role in capability.required_roles:
        matching = [item for item in inputs if item.role == role]
        ordered.extend(matching)
    return tuple(ordered)


def _resolve_output_spec(
    command: CreateImageCommand, capability: ImageCapability
) -> ImageOutputSpec:
    if command.output_format not in capability.supported_output_formats:
        raise MediaLabImageError(
            "This pinned graph does not support the requested delivery format",
            code="format_not_supported",
        )
    if not capability.supports_output_size:
        if (
            command.width is not None
            or command.height is not None
            or command.output_preset_id is not None
        ):
            raise MediaLabImageError(
                "This pinned graph uses the product source dimensions", code="size_not_supported"
            )
        return ImageOutputSpec(
            width=None,
            height=None,
            delivery_format=command.output_format,
        )
    if command.output_preset_id is not None and (
        command.width is not None or command.height is not None
    ):
        raise MediaLabImageError(
            "Choose either an output preset or legacy dimensions, not both",
            code="invalid_output_spec",
        )
    accepted_presets = (*capability.output_presets, *_LEGACY_IMAGE_OUTPUT_PRESETS)
    preset = next(
        (item for item in accepted_presets if item.preset_id == command.output_preset_id), None
    )
    if (
        command.output_preset_id is None
        and command.width is not None
        and command.height is not None
    ):
        preset = next(
            (
                item
                for item in accepted_presets
                if item.width == command.width and item.height == command.height
            ),
            None,
        )
    if preset is None:
        if command.output_preset_id is not None:
            raise MediaLabImageError(
                "The requested image output preset is not supported by the pinned graph",
                code="output_preset_not_supported",
            )
        preset = capability.output_presets[0]
    return ImageOutputSpec(
        width=preset.width,
        height=preset.height,
        preset_id=preset.preset_id,
        aspect_ratio=preset.aspect_ratio,
        delivery_format=command.output_format,
    )


def _next_retry_memory(
    run: ImageRun,
    review: ImageQualityReview,
) -> ImageRetryMemory:
    prior_attempts = run.retry_memory.attempts if run.retry_memory is not None else ()
    attempt = ImageRetryAttempt(
        run_id=run.run_id,
        seed=run.seed,
        production_prompt=run.prompt,
        output_asset_id=run.output_asset_id,
        output_checksum_sha256=run.output_checksum_sha256,
        review_decision=review.decision,
        review_summary=review.summary,
        repair_instructions=review.repair_instructions,
        repair_prompt=review.repair_prompt,
    )
    return ImageRetryMemory(
        root_run_id=(run.retry_memory.root_run_id if run.retry_memory is not None else run.run_id),
        attempts=(*prior_attempts, attempt),
    )


def _retry_root(run: ImageRun, runs: dict[str, ImageRun]) -> ImageRun:
    current = run
    visited: set[str] = set()
    while current.retry_of_run_id is not None:
        if current.run_id in visited:
            raise MediaLabImageError(
                "Image regeneration lineage contains a cycle",
                status_code=409,
                code="invalid_retry_lineage",
            )
        visited.add(current.run_id)
        parent = runs.get(current.retry_of_run_id)
        if parent is None:
            raise MediaLabImageError(
                "Image regeneration lineage is incomplete",
                status_code=409,
                code="invalid_retry_lineage",
            )
        current = parent
    return current


def _render_prompt(prompt: str, references: tuple[ImageReference, ...]) -> str:
    lines = [prompt.strip()]
    if references:
        lines.append("Resolved reference contract:")
    for reference in references:
        line = f"- {reference.role.value} (priority {reference.priority})"
        if reference.identity_group:
            line += f"; identity group: {reference.identity_group}"
        if reference.must_preserve:
            line += f"; must preserve: {', '.join(reference.must_preserve)}"
        if reference.allowed_changes:
            line += f"; allowed changes: {', '.join(reference.allowed_changes)}"
        lines.append(line)
    return "\n".join(lines)


def _image_extension(content_type: str) -> str:
    return ".png" if content_type == "image/png" else ".jpg"


def _quality_error_code(error: Exception) -> str:
    if isinstance(error, MediaLabImageQualityReviewError):
        return error.code
    if isinstance(error, MediaLabImageError):
        return error.code
    if isinstance(error, FileNotFoundError):
        return "artifact_missing"
    if isinstance(error, OSError):
        return "artifact_unavailable"
    return "regeneration_failed"


__all__ = ["MediaLabImageService", "build_image_capabilities"]
