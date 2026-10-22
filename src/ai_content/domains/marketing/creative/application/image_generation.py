"""Bridge binary generation and artifact persistence to the existing workflow."""

from dataclasses import replace

from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)
from ai_content.platform.observability import observe_ai_call

from ..domain.entities import AssetVersion, VersionId
from ..ports.contracts import RevisionRequest, StaticCreativeInput
from ..ports.images import (
    IGeneratedImageStore,
    IImageBackend,
    ImageGenerationError,
    ImageGenerationRequest,
    IProductSegmenter,
    IStaticRenderer,
)
from .use_cases import compute_input_hash


class StoredImageGenerator:
    def __init__(
        self,
        backend: IImageBackend,
        store: IGeneratedImageStore,
        seed: int,
        *,
        source_input_hash: str | None = None,
        usage_tracker: AIUsageTracker | None = None,
        backend_name: str | None = None,
        model: str | None = None,
        model_revision: str | None = None,
        renderer: IStaticRenderer | None = None,
        product_segmenter: IProductSegmenter | None = None,
    ) -> None:
        self._backend = backend
        self._store = store
        self._seed = seed
        self._source_input_hash = source_input_hash
        self._usage_tracker = usage_tracker
        self._backend_name = backend_name or type(backend).__name__
        self._model = model or "unknown"
        self._model_revision = model_revision
        self._renderer = renderer
        self._product_segmenter = product_segmenter

    async def generate(
        self,
        input_data: StaticCreativeInput,
        version_id: VersionId,
        revision: RevisionRequest | None = None,
    ) -> AssetVersion:
        request = ImageGenerationRequest(
            input=input_data,
            seed=self._seed,
            input_hash=self._source_input_hash or compute_input_hash(input_data, revision),
            revision=revision,
        )
        request = self._store.prepare(version_id.value, request)
        product_cutout = None
        preservation = (
            request.input.composition.product_preservation
            if request.input.composition is not None
            else None
        )
        if preservation is not None:
            if self._product_segmenter is None:
                raise ImageGenerationError(
                    "Product preservation requires a configured segmenter",
                    code="product_segmenter_missing",
                )
            if preservation.source_index >= len(request.input.product_assets):
                raise ImageGenerationError(
                    "Selected product source is outside the frozen input set",
                    code="product_source_invalid",
                )
            source = request.input.product_assets[preservation.source_index]
            product_cutout = await self._product_segmenter.extract(
                source.url, preservation.segmentation_prompt
            )
            self._store.save_product_cutout(version_id.value, product_cutout)
            request = replace(
                request,
                generation_target="background",
                revision_image_ref=None,
            )
        event_id = None
        if self._usage_tracker is not None:
            event_id = await self._usage_tracker.start(
                AIUsageStart(
                    workstream="creative",
                    operation="image.revise" if revision else "image.generate",
                    backend=self._backend_name,
                    model=self._model,
                    model_revision=self._model_revision,
                    job_id=version_id.job_id.value,
                    version_id=version_id.value,
                    brand_id=input_data.brand,
                    attempt_number=version_id.version_number,
                )
            )
        with observe_ai_call(
            "image.revise" if revision else "image.generate",
            type(self._backend).__name__,
            "unknown",
            job_id=version_id.job_id.value,
            version_id=version_id.value,
            creative_set_id=input_data.creative_set_id,
            variation_id=input_data.variation_id,
            attempt_number=version_id.version_number,
            input_hash=request.input_hash,
            revision_of=revision.previous_version_ref if revision else None,
            output_width=input_data.output_spec.width,
            output_height=input_data.output_spec.height,
            input_image_count=(
                len(input_data.product_assets)
                + len(input_data.reference_assets)
                + (1 if input_data.logo_asset else 0)
                + (1 if request.revision_image_ref else 0)
            ),
        ) as observation:
            try:
                generated = await self._backend.generate(request)
            except ImageGenerationError as error:
                if event_id is not None:
                    await self._usage_tracker.fail(event_id, AIUsageFailure(error_code=error.code))
                observation.fail(error.code)
                raise
            if event_id is not None:
                await self._usage_tracker.succeed(
                    event_id,
                    AIUsageCompletion(
                        model=generated.model,
                        model_revision=generated.model_revision,
                        output_count=1,
                        output_bytes=len(generated.content),
                    ),
                )
            if self._renderer is None and request.input.composition is not None:
                raise ImageGenerationError(
                    "Composition input requires a deterministic renderer",
                    code="renderer_missing",
                )
            if self._renderer is not None:
                try:
                    finished = self._renderer.render(generated, request.input, product_cutout)
                except ImageGenerationError:
                    self._store.save_raw(version_id.value, generated)
                    raise
                if finished.content != generated.content:
                    self._store.save_raw(version_id.value, generated)
                generated = finished
            stored = self._store.save(version_id.value, generated)
            observation.update(
                model=generated.model,
                model_revision=generated.model_revision,
                runtime_version=generated.runtime_version,
                workflow_hash=generated.workflow_hash,
                provider_request_id=generated.service_job_id,
                provider_elapsed_seconds=generated.elapsed_seconds,
            )
            observation.generated(len(generated.content))
            observation.succeed()
        return AssetVersion(
            version_id=version_id,
            attempt_number=version_id.version_number,
            input_ref=f"idea:{input_data.idea_id}",
            artifact_path=stored.path,
            generator_version=f"{generated.model}@{generated.model_revision}",
            seed=generated.seed,
            # Local compute cost is unknown, not zero or the fake USD charge.
            cost=None,
            creative_set_id=input_data.creative_set_id,
            variation_id=input_data.variation_id,
        )
