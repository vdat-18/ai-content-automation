"""Run provider-neutral paid production for one durable Marketing automation state."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from ai_content.domains.marketing.creative.application.final_review import (
    build_final_creative_review,
)
from ai_content.domains.marketing.creative.application.paid_media_production import (
    PaidMediaAttempt,
    PaidMediaProductionResult,
    PaidMediaProductionService,
)
from ai_content.domains.marketing.creative.application.provider_registry import (
    ManagedMediaProviderRegistry,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    IMarketingCreativeAutomationStateRepository,
    MarketingCreativeAutomationState,
    MarketingCreativeAutomationStatus,
    PaidMediaAttemptRecord,
    ProducedCreativeAssetRecord,
    resolve_state_repository_call,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    IPaidImageQualityEvaluator,
    IPaidMediaSourceResolver,
    PaidAssembledVideoRequest,
    PaidImageGenerationRequest,
    PaidMediaGenerationLimits,
    PaidMediaProviderUnavailableError,
    PaidMediaSource,
    PaidVideoGenerationRequest,
    ProductMediaSourceRef,
)
from ai_content.domains.marketing.creative.ports.preparation_store import (
    ProductionReadyCreativePackage,
)

from .automation_workflow import record_final_review, record_production_outcome


class MarketingCreativeAutomationProducer:
    def __init__(
        self,
        state_repository: IMarketingCreativeAutomationStateRepository,
        providers: ManagedMediaProviderRegistry,
        source_resolver: IPaidMediaSourceResolver,
        *,
        image_limits: PaidMediaGenerationLimits,
        video_limits: PaidMediaGenerationLimits,
        max_concurrency: int = 10,
        image_evaluator: IPaidImageQualityEvaluator | None = None,
        max_image_attempts: int = 1,
    ) -> None:
        self._states = state_repository
        self._providers = providers
        self._source_resolver = source_resolver
        self._production = PaidMediaProductionService(
            providers,
            max_concurrency=max_concurrency,
            image_evaluator=image_evaluator,
            max_image_attempts=max_image_attempts,
        )
        self._image_limits = image_limits
        self._video_limits = video_limits

    async def produce(
        self,
        package: ProductionReadyCreativePackage,
    ) -> MarketingCreativeAutomationState:
        state = await resolve_state_repository_call(self._states.get(package.request.request_id))
        if state is None:
            raise ValueError("Creative automation state is missing")
        if state.package_id != package.package_id:
            raise ValueError("Creative package does not match the automation state")
        if state.route != "automated":
            raise ValueError("Only the automated route can call paid media providers")
        if state.status != MarketingCreativeAutomationStatus.AWAITING_GENERATION_PROVIDER:
            raise ValueError("Creative automation is not ready for paid production")
        brief = package.brief
        idea = package.selected_idea
        plan = package.automation_plan
        if brief is None or idea is None or package.strategy is None or plan is None:
            raise ValueError("Production-ready Creative package is incomplete")
        if package.request.execution_mode.value != "generate_once":
            raise ValueError("Brief-only Creative automation cannot call media providers")
        if plan.readiness.value != "ready":
            raise ValueError("Creative automation plan is not ready for generation")
        self._require_ready_providers(package)
        revision_request = state.generation_requests[-1] if state.generation_requests else None
        latest_records = _latest_records_by_slot(state.production_assets)
        target_slots = _target_slots(revision_request)
        producing = replace(
            state,
            status=MarketingCreativeAutomationStatus.PRODUCING,
            production_error_code=None,
            production_error_detail=None,
            revision=state.revision + 1,
            updated_at=datetime.now(UTC),
        )
        await resolve_state_repository_call(self._states.save(producing))
        current = producing
        try:
            source_refs = _selected_source_refs(package)
            sources = await self._source_resolver.resolve_product_sources(
                request_id=package.request.request_id,
                sku_id=package.request.sku_id,
                source_refs=source_refs,
            )
            if not sources:
                raise ValueError("No immutable product source is available for production")
            reference_sources: dict[str, PaidMediaSource] = {}
            selected_reference_ids = _selected_plan_reference_ids(
                package.automation_plan,
                package.request,
            )
            selected_reference_candidates = tuple(
                item
                for item in package.request.reference_candidates
                if item.reference_id in selected_reference_ids
            )
            if selected_reference_candidates:
                resolver = getattr(self._source_resolver, "resolve_reference_asset", None)
                if resolver is None:
                    raise ValueError("Configured media resolver cannot materialize references")
                resolved_references = await asyncio.gather(
                    *(
                        resolver(
                            reference_id=item.reference_id,
                            artifact_ref=item.artifact_ref,
                            checksum_sha256=item.checksum_sha256,
                        )
                        for item in selected_reference_candidates
                    )
                )
                reference_sources = {
                    candidate.reference_id: source
                    for candidate, source in zip(
                        selected_reference_candidates,
                        resolved_references,
                        strict=True,
                    )
                }
            logo_source = None
            if (
                package.request.include_logo
                and package.request.logo_artifact_ref is not None
                and package.request.logo_checksum_sha256 is not None
            ):
                resolver = getattr(self._source_resolver, "resolve_brand_asset", None)
                if resolver is None:
                    raise ValueError("Configured media resolver cannot materialize the logo")
                logo_source = await resolver(
                    artifact_ref=package.request.logo_artifact_ref,
                    checksum_sha256=package.request.logo_checksum_sha256,
                )
            image_requests, video_groups = self._requests(
                package,
                sources,
                reference_sources=reference_sources,
                logo_source=logo_source,
                version=_next_asset_version(producing),
                revision_request=revision_request,
                target_slots=target_slots,
                latest_records=latest_records,
            )
            ordered_slots = tuple(item[0] for item in image_requests) + tuple(
                item[0] for item in video_groups
            )
            review_results: dict[
                str, tuple[str, Literal["image", "video"], PaidMediaProductionResult]
            ] = {}
            review_records: dict[str, ProducedCreativeAssetRecord] = {}
            records: list[ProducedCreativeAssetRecord] = []
            provider_call_failed = False

            for slot, _asset_version_id, _variation_key, request, parent in image_requests:
                if request is not None:
                    continue
                if parent is not None and parent.success:
                    review_results[slot] = (
                        parent.asset_version_id,
                        "image",
                        _result_from_record(parent),
                    )
                    review_records[slot] = parent

            selected_images = tuple(item for item in image_requests if item[3] is not None)
            video_tasks = {
                slot: asyncio.create_task(
                    self._produce_video(
                        asset_version_id,
                        aspect_ratio,
                        video_plan,
                        scene_requests,
                        keyframe_requests,
                        (
                            package.request.video_generate_audio
                            if package.request.video_generate_audio is not None
                            else video_plan.audio_plan.expects_audio
                        ),
                    )
                )
                for (
                    slot,
                    asset_version_id,
                    _variation_key,
                    aspect_ratio,
                    video_plan,
                    scene_requests,
                    keyframe_requests,
                    _parent,
                ) in video_groups
                if scene_requests is not None
            }
            image_outcomes = await asyncio.gather(
                *(self._produce("image", item[3]) for item in selected_images),
                return_exceptions=True,
            )
            for (slot, asset_version_id, variation_key, _request, parent), outcome in zip(
                selected_images, image_outcomes, strict=True
            ):
                result = _provider_result(outcome)
                provider_call_failed = (
                    provider_call_failed or result.outcome == "provider_call_failed"
                )
                record = _record(
                    asset_version_id,
                    "image",
                    variation_key,
                    result,
                    parent_asset_version_id=(
                        parent.asset_version_id if parent is not None else None
                    ),
                    revision_request=revision_request,
                )
                records.append(record)
                review_results[slot] = (asset_version_id, "image", result)
                review_records[slot] = record

            for (
                slot,
                asset_version_id,
                variation_key,
                _aspect_ratio,
                _video_plan,
                scene_requests,
                _keyframe_requests,
                parent,
            ) in video_groups:
                if scene_requests is None:
                    if parent is not None and parent.success:
                        review_results[slot] = (
                            parent.asset_version_id,
                            "video",
                            _result_from_record(parent),
                        )
                        review_records[slot] = parent
                    continue
                final_result, intermediate_artifacts, additional_cost = await video_tasks[slot]
                provider_call_failed = (
                    provider_call_failed or final_result.outcome == "provider_call_failed"
                )
                record = _record(
                    asset_version_id,
                    "video",
                    variation_key,
                    final_result,
                    intermediate_artifacts=intermediate_artifacts,
                    additional_cost=additional_cost,
                    parent_asset_version_id=(
                        parent.asset_version_id if parent is not None else None
                    ),
                    revision_request=revision_request,
                )
                records.append(record)
                review_results[slot] = (asset_version_id, "video", final_result)
                review_records[slot] = record

            current = record_production_outcome(
                producing,
                tuple(records),
                error_code="provider_call_failed" if provider_call_failed else None,
                error_detail=(
                    "One or more provider calls failed. Completed artifacts and their recorded "
                    "costs were preserved."
                    if provider_call_failed
                    else None
                ),
            )
            await resolve_state_repository_call(self._states.save(current))
            complete_results = tuple(
                review_results[slot] for slot in ordered_slots if slot in review_results
            )
            if len(complete_results) != len(ordered_slots) or any(
                not result.success for _, _, result in complete_results
            ):
                return current
            exact_records = tuple(review_records[slot] for slot in ordered_slots)
            final_review = build_final_creative_review(
                review_id=_review_id(package.request.request_id, exact_records),
                request_id=package.request.request_id,
                package_id=package.package_id,
                brand_id=package.request.brand,
                sku_id=package.request.sku_id,
                objective=package.request.objective,
                platform=package.request.platform,
                direction_summary=_review_direction_summary(plan.strategy_summary, exact_records),
                expected_image_count=package.request.output.image_output_count,
                expected_video_count=package.request.output.video_output_count,
                results=complete_results,
                review_checklist=package.review_checklist,
            )
            ready = record_final_review(current, final_review)
            await resolve_state_repository_call(self._states.save(ready))
            return ready
        except Exception as error:
            failed = record_production_outcome(
                current,
                (),
                error_code=type(error).__name__,
                error_detail="Paid media production failed before a reviewable output set was ready.",
            )
            await resolve_state_repository_call(self._states.save(failed))
            raise

    def _require_ready_providers(
        self,
        package: ProductionReadyCreativePackage,
    ) -> None:
        if package.request.output.image_output_count and self._providers.image_status() != "ready":
            raise PaidMediaProviderUnavailableError("No approved paid image provider is ready")
        if package.request.output.video_output_count and self._providers.video_status() != "ready":
            raise PaidMediaProviderUnavailableError("No approved paid video provider is ready")

    def _requests(
        self,
        package,
        sources,
        *,
        reference_sources,
        logo_source=None,
        version: int,
        revision_request,
        target_slots,
        latest_records,
    ):
        image_profiles = tuple(
            profile
            for profile in package.request.output.output_profiles
            if profile.media_kind == "image"
            for _ in range(profile.count)
        )
        video_profiles = tuple(
            profile
            for profile in package.request.output.output_profiles
            if profile.media_kind == "video"
            for _ in range(profile.count)
        )
        plans = package.automation_plan.image_plans
        if len(plans) != len(image_profiles):
            raise ValueError("Creative automation plan does not contain every requested image")
        sources_by_media_id = {
            source.media_id: source for source in sources if source.media_id is not None
        }
        family_aware = package.request.product_family is not None
        image_provider = (
            self._providers.require_image(package.request.image_provider_id)
            if image_profiles
            else None
        )
        image_uses_exact_source_transform = bool(
            image_provider is not None
            and image_provider.descriptor.fidelity_mode == "exact_source_transform"
        )
        image_requests = []
        for index, (plan, profile) in enumerate(zip(plans, image_profiles, strict=True), start=1):
            slot = f"image:{index}"
            parent = latest_records.get(slot)
            should_generate = _should_generate(slot, revision_request, target_slots)
            request = None
            if should_generate:
                width, height = (
                    tuple(map(int, profile.image_size.split("x")))
                    if profile.image_size
                    else _profile_dimensions(profile.aspect_ratio)
                )
                plan_sources = _plan_sources(
                    plan.selected_media_ids,
                    sources,
                    sources_by_media_id,
                    family_aware=family_aware,
                )
                selected_references = _selected_reference_sources(
                    _reference_ids_for_output(
                        package.request,
                        slot,
                        plan.reference_ids,
                    ),
                    reference_sources,
                )
                if image_uses_exact_source_transform and selected_references:
                    raise ValueError(
                        "Exact Shopify image production does not support Research references"
                    )
                plan_sources += selected_references
                if image_uses_exact_source_transform:
                    plan_sources = _single_product_source(plan_sources)
                headline, subtext, cta_text = _resolved_image_copy(
                    package,
                    plan.variation_key,
                )
                request = PaidImageGenerationRequest(
                    request_id=f"{package.request.request_id}:image:{index}:v{version}",
                    package_id=package.package_id,
                    sku_id=package.request.sku_id,
                    variation_key=plan.variation_key,
                    visual_direction=_revision_direction(plan.visual_direction, revision_request),
                    width=width,
                    height=height,
                    sources=plan_sources,
                    limits=self._image_limits,
                    aspect_ratio=profile.aspect_ratio,
                    provider_id=package.request.image_provider_id,
                    model_id=package.request.image_model_id,
                    resolution=package.request.image_resolution,
                    quality=package.request.image_quality,
                    image_size=profile.image_size,
                    background=package.request.image_background,
                    moderation=package.request.image_moderation,
                    output_compression=package.request.image_output_compression,
                    input_fidelity=package.request.image_input_fidelity,
                    generation_mode=(
                        "multi_image_edit"
                        if selected_references
                        else package.request.image_generation_mode or "single_image_edit"
                    ),
                    file_format=profile.file_format,
                    include_text=package.request.include_text,
                    include_logo=package.request.include_logo,
                    headline=headline,
                    subtext=subtext,
                    cta_text=cta_text,
                    logo_source=logo_source,
                )
            image_requests.append(
                (
                    slot,
                    f"{package.request.request_id}:image:{index}:v{version}",
                    f"{plan.variation_key}:{profile.profile_id}",
                    request,
                    parent,
                )
            )
        video_plans = package.automation_plan.resolved_video_plans
        if len(video_plans) != len(video_profiles):
            raise ValueError("Creative automation plan does not contain every requested video")
        video_provider = self._providers.require_video() if video_profiles else None
        video_uses_exact_source_transform = bool(
            video_provider is not None
            and video_provider.descriptor.fidelity_mode == "exact_source_transform"
        )
        video_groups = []
        for index, (video_plan, profile) in enumerate(
            zip(video_plans, video_profiles, strict=True),
            start=1,
        ):
            slot = f"video:{index}"
            parent = latest_records.get(slot)
            should_generate = _should_generate(slot, revision_request, target_slots)
            scene_requests = None
            keyframe_requests = None
            if should_generate:
                assert video_provider is not None
                selected_model = next(
                    (
                        item
                        for item in video_provider.descriptor.video_models
                        if item.model_id == package.request.video_model_id
                    ),
                    None,
                )
                supported_durations = (
                    selected_model.supported_generation_durations_seconds
                    if selected_model is not None
                    else video_provider.descriptor.supported_generation_durations_seconds
                )
                native_audio_enabled = (
                    not video_uses_exact_source_transform
                    and package.request.video_generate_audio is not False
                )
                scene_requests = tuple(
                    PaidVideoGenerationRequest(
                        request_id=(
                            f"{package.request.request_id}:video:{index}:{scene.scene_id}:v{version}"
                        ),
                        package_id=package.package_id,
                        sku_id=package.request.sku_id,
                        visual_direction=_revision_direction(
                            scene.visual_direction, revision_request
                        ),
                        aspect_ratio=profile.aspect_ratio,
                        sources=_video_request_sources(
                            _plan_sources(
                                scene.selected_media_ids,
                                sources,
                                sources_by_media_id,
                                family_aware=family_aware,
                            ),
                            _selected_reference_sources(
                                _reference_ids_for_output(
                                    package.request,
                                    slot,
                                    video_plan.reference_ids,
                                ),
                                reference_sources,
                            ),
                            exact_source_transform=video_uses_exact_source_transform,
                        ),
                        limits=self._video_limits,
                        duration_seconds=_generation_duration(
                            scene.resolved_generation_duration_seconds,
                            scene.usable_duration_seconds,
                            supported_durations,
                        ),
                        model_id=package.request.video_model_id,
                        resolution=package.request.video_resolution,
                        generate_audio=(
                            False
                            if video_uses_exact_source_transform
                            else package.request.video_generate_audio
                        ),
                        usable_duration_seconds=scene.usable_duration_seconds,
                        duration_min_seconds=1,
                        duration_max_seconds=(
                            package.request.output.video_scene_duration_max_seconds
                        ),
                        voice_mode=(
                            video_plan.audio_plan.voice_mode.value
                            if native_audio_enabled
                            else "none"
                        ),
                        music_mode=(
                            video_plan.audio_plan.music_mode.value
                            if native_audio_enabled
                            else "none"
                        ),
                        voice_direction=(
                            video_plan.audio_plan.voice_direction if native_audio_enabled else None
                        ),
                        music_direction=(
                            video_plan.audio_plan.music_direction if native_audio_enabled else None
                        ),
                        audio_direction=scene.audio_direction if native_audio_enabled else None,
                        continuity_direction=(
                            f"{video_plan.continuity_plan} {scene.transition_direction}".strip()
                        ),
                    )
                    for scene in video_plan.scenes
                )
                keyframe_requests = self._keyframe_requests(
                    package,
                    video_plan,
                    scene_requests,
                    profile.aspect_ratio,
                )
            video_groups.append(
                (
                    slot,
                    f"{package.request.request_id}:video:{index}:v{version}",
                    f"{video_plan.variation_key}:{profile.profile_id}",
                    profile.aspect_ratio,
                    video_plan,
                    scene_requests,
                    keyframe_requests,
                    parent,
                )
            )
        return tuple(image_requests), tuple(video_groups)

    def _keyframe_requests(
        self,
        package,
        video_plan,
        scene_requests: tuple[PaidVideoGenerationRequest, ...],
        aspect_ratio: str,
    ) -> tuple[PaidImageGenerationRequest, ...]:
        """Plan one product-faithful still per scene; each scene video starts from it."""
        descriptor = self._providers.require_image().descriptor
        model = next(
            (
                item
                for item in descriptor.image_models
                if item.model_id == package.request.image_model_id
            ),
            descriptor.image_models[0],
        )
        width, height = _profile_dimensions(aspect_ratio)
        return tuple(
            PaidImageGenerationRequest(
                request_id=f"{scene_request.request_id}:keyframe",
                package_id=package.package_id,
                sku_id=package.request.sku_id,
                variation_key=f"{video_plan.variation_key}:{scene.scene_id}:keyframe",
                visual_direction=(
                    f"Opening frame of this video scene: {scene.visual_direction} "
                    f"{video_plan.continuity_plan}"
                ).strip(),
                width=width,
                height=height,
                sources=tuple(
                    source for source in scene_request.sources if source.role == "product"
                )[: model.max_reference_images],
                limits=self._image_limits,
                aspect_ratio=aspect_ratio,
                provider_id=descriptor.provider_id,
                model_id=model.model_id,
                resolution=model.supported_resolutions[0],
            )
            for scene, scene_request in zip(video_plan.scenes, scene_requests, strict=True)
        )

    async def _produce(self, kind, request) -> PaidMediaProductionResult:
        if kind == "image":
            assert isinstance(request, PaidImageGenerationRequest)
            return await self._production.produce_image(request)
        assert isinstance(request, PaidVideoGenerationRequest)
        return await self._production.produce_video(request)

    async def _produce_video(
        self,
        asset_version_id: str,
        aspect_ratio: str,
        video_plan,
        scene_requests: tuple[PaidVideoGenerationRequest, ...],
        keyframe_requests: tuple[PaidImageGenerationRequest, ...],
        expects_audio: bool,
    ) -> tuple[PaidMediaProductionResult, tuple, Decimal]:
        keyframe_outcomes = await asyncio.gather(
            *(self._produce("image", request) for request in keyframe_requests),
            return_exceptions=True,
        )
        keyframe_results = tuple(_provider_result(outcome) for outcome in keyframe_outcomes)
        keyframe_cost = sum((result.total_cost for result in keyframe_results), start=Decimal("0"))
        if not all(
            result.success and result.selected_artifact is not None for result in keyframe_results
        ):
            return _failed_scene_result(keyframe_results), (), keyframe_cost
        scene_requests = tuple(
            replace(
                request,
                sources=(
                    PaidMediaSource(
                        asset_ref=keyframe.selected_artifact.artifact_ref,
                        checksum_sha256=keyframe.selected_artifact.checksum_sha256,
                        role="keyframe",
                    ),
                ),
            )
            for request, keyframe in zip(scene_requests, keyframe_results, strict=True)
        )
        scene_outcomes = await asyncio.gather(
            *(self._produce("video", request) for request in scene_requests),
            return_exceptions=True,
        )
        scene_results = tuple(_provider_result(outcome) for outcome in scene_outcomes)
        scene_artifacts = tuple(
            result.selected_artifact
            for result in scene_results
            if result.selected_artifact is not None
        )
        if (
            video_plan.generation_strategy.value == "one_shot"
            and scene_results[0].selected_artifact is not None
            and scene_results[0].selected_artifact.duration_seconds
            == video_plan.final_duration_seconds
        ):
            return scene_results[0], (), keyframe_cost
        if not all(
            result.success and result.selected_artifact is not None for result in scene_results
        ):
            return _failed_scene_result(scene_results), scene_artifacts, keyframe_cost
        scene_cost = keyframe_cost + sum(
            (result.total_cost for result in scene_results),
            start=Decimal("0"),
        )
        assembled_request = PaidAssembledVideoRequest(
            request_id=f"{asset_version_id}:assembled",
            package_id=scene_requests[0].package_id,
            sku_id=scene_requests[0].sku_id,
            aspect_ratio=aspect_ratio,
            scene_artifacts=scene_artifacts,
            final_duration_seconds=video_plan.final_duration_seconds,
            expects_audio=expects_audio,
            audio_continuity_direction=video_plan.audio_plan.continuity_direction,
            limits=self._video_limits,
            scene_usable_durations_seconds=tuple(
                scene.usable_duration_seconds for scene in video_plan.scenes
            ),
        )
        try:
            final_result = await self._production.assemble_video(assembled_request)
        except Exception:
            final_result = _provider_failure_result()
        return final_result, scene_artifacts, scene_cost


def _selected_source_refs(package) -> tuple[ProductMediaSourceRef, ...]:
    family = package.sku.product_family
    if package.request.product_family is None or family is None:
        return tuple(
            ProductMediaSourceRef(
                source_id="legacy",
                product_id=package.request.sku_id,
                media_id=f"legacy-media:{index}",
                url=url,
            )
            for index, url in enumerate(package.sku.product_metadata.image_refs, 1)
        )
    selected_ids = {
        media_id
        for plan in package.automation_plan.image_plans
        for media_id in plan.selected_media_ids
    }
    selected_ids.update(
        media_id
        for plan in package.automation_plan.resolved_video_plans
        for scene in plan.scenes
        for media_id in scene.selected_media_ids
    )
    if not selected_ids:
        raise ValueError("Product Family production plan selected no product media")
    known_ids = {item.media_id for item in family.media}
    unknown = selected_ids - known_ids
    if unknown:
        raise ValueError("Product Family production plan references unknown product media")
    return tuple(
        ProductMediaSourceRef(
            source_id=family.ref.source_id,
            product_id=family.ref.product_id,
            media_id=item.media_id,
            url=item.url,
            variant_ids=item.variant_ids,
            artifact_ref=item.artifact_ref,
            checksum_sha256=item.checksum_sha256,
        )
        for item in family.media
        if item.media_id in selected_ids
    )


def _plan_sources(
    media_ids: tuple[str, ...],
    all_sources,
    sources_by_media_id,
    *,
    family_aware: bool,
):
    if not family_aware:
        return all_sources
    if not media_ids:
        raise ValueError("Product Family output selected no product media")
    missing = [media_id for media_id in media_ids if media_id not in sources_by_media_id]
    if missing:
        raise ValueError("Selected product media could not be resolved immutably")
    return tuple(sources_by_media_id[media_id] for media_id in media_ids)


def _single_product_source(sources: tuple[PaidMediaSource, ...]) -> tuple[PaidMediaSource, ...]:
    product_sources = tuple(item for item in sources if item.role == "product")
    if not product_sources or len(product_sources) != len(sources):
        raise ValueError("Exact Shopify production requires only a product source")
    return (product_sources[0],)


def _video_request_sources(
    product_sources: tuple[PaidMediaSource, ...],
    reference_sources: tuple[PaidMediaSource, ...],
    *,
    exact_source_transform: bool,
) -> tuple[PaidMediaSource, ...]:
    if exact_source_transform:
        if reference_sources:
            raise ValueError("Exact Shopify video production does not support Research references")
        return _single_product_source(product_sources)
    return product_sources + reference_sources


def _review_direction_summary(
    planned_summary: str,
    records: tuple[ProducedCreativeAssetRecord, ...],
) -> str:
    """Keep Marketing's review description aligned with what was actually rendered."""
    artifacts = tuple(record.selected_artifact for record in records)
    if artifacts and all(
        artifact is not None and artifact.fidelity_mode == "exact_source_transform"
        for artifact in artifacts
    ):
        return (
            "Exact Shopify source transforms only: each image is a crop and resize of one "
            "frozen Shopify product image, and each video is a silent gentle motion clip of "
            "that same source. The Agent strategy remains a marketing hypothesis; no new "
            "background, person, copy, logo, audio, or product geometry was generated."
        )
    return planned_summary


def _selected_plan_reference_ids(plan, request) -> set[str]:
    selected: set[str] = set()
    for index, item in enumerate(plan.image_plans, start=1):
        selected.update(_reference_ids_for_output(request, f"image:{index}", item.reference_ids))
    for index, item in enumerate(plan.resolved_video_plans, start=1):
        selected.update(_reference_ids_for_output(request, f"video:{index}", item.reference_ids))
    return selected


def _reference_ids_for_output(request, output_key, plan_reference_ids):
    if plan_reference_ids:
        return plan_reference_ids
    assignment = next(
        (item for item in request.reference_assignments if item.output_key == output_key),
        None,
    )
    return assignment.reference_ids if assignment is not None else ()


def _selected_reference_sources(reference_ids, reference_sources):
    missing = [
        reference_id for reference_id in reference_ids if reference_id not in reference_sources
    ]
    if missing:
        raise ValueError("Selected Research reference could not be resolved immutably")
    return tuple(reference_sources[reference_id] for reference_id in reference_ids)


def _resolved_image_copy(
    package: ProductionReadyCreativePackage,
    variation_key: str,
) -> tuple[str | None, str | None, str | None]:
    request = package.request
    if not request.include_text:
        return None, None, None
    if any((request.headline, request.subtext, request.cta_text)):
        return request.headline, request.subtext, request.cta_text
    if package.brief is None:
        raise ValueError("Agent-written image text requires a prepared Creative brief")
    variation = next(
        (item for item in package.brief.variation_plans if item.variation_key == variation_key),
        None,
    )
    if variation is not None:
        return variation.heading, variation.subtext, None
    return package.brief.heading, package.brief.subtext, None


def _generation_duration(
    planned_generation_seconds: int,
    usable_seconds: int,
    supported_durations: tuple[int, ...],
) -> int:
    minimum = max(planned_generation_seconds, usable_seconds)
    candidates = sorted(value for value in supported_durations if value >= minimum)
    if not candidates:
        raise ValueError("No provider generation duration can satisfy the planned usable scene")
    return candidates[0]


def _profile_dimensions(aspect_ratio: str) -> tuple[int, int]:
    return {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "4:3": (1440, 1080),
        "3:4": (1080, 1440),
        "3:2": (1620, 1080),
        "2:3": (1080, 1620),
    }[aspect_ratio]


def _record(
    asset_version_id: str,
    media_kind: Literal["image", "video"],
    variation_key: str,
    result: PaidMediaProductionResult,
    *,
    intermediate_artifacts=(),
    additional_cost=0,
    parent_asset_version_id: str | None = None,
    revision_request=None,
) -> ProducedCreativeAssetRecord:
    return ProducedCreativeAssetRecord(
        asset_version_id=asset_version_id,
        media_kind=media_kind,
        variation_key=variation_key,
        success=result.success,
        attempts=tuple(
            PaidMediaAttemptRecord(item.attempt_number, item.artifact, item.evaluation)
            for item in result.attempts
        ),
        selected_artifact=result.selected_artifact,
        total_cost=result.total_cost + additional_cost,
        outcome=result.outcome,
        intermediate_artifacts=intermediate_artifacts,
        parent_asset_version_id=parent_asset_version_id,
        generation_request_id=(
            revision_request.generation_request_id if revision_request is not None else None
        ),
        revision_feedback=(revision_request.reason if revision_request is not None else None),
    )


def _result_from_record(record: ProducedCreativeAssetRecord) -> PaidMediaProductionResult:
    return PaidMediaProductionResult(
        success=record.success,
        attempts=tuple(
            PaidMediaAttempt(item.attempt_number, item.artifact, item.evaluation)
            for item in record.attempts
        ),
        selected_artifact=record.selected_artifact,
        total_cost=record.total_cost,
        outcome=record.outcome,
    )


def _asset_slot(asset_version_id: str) -> str:
    marker = asset_version_id.rsplit(":v", 1)[0]
    parts = marker.split(":")
    if len(parts) >= 3 and parts[-2] in {"image", "video"} and parts[-1].isdigit():
        return f"{parts[-2]}:{int(parts[-1])}"
    for kind in ("image", "video"):
        if asset_version_id.startswith(f"{kind}-v"):
            return f"{kind}:1"
    raise ValueError("Creative asset version ID does not identify an output slot")


def _latest_records_by_slot(
    records: tuple[ProducedCreativeAssetRecord, ...],
) -> dict[str, ProducedCreativeAssetRecord]:
    latest: dict[str, ProducedCreativeAssetRecord] = {}
    for record in records:
        latest[_asset_slot(record.asset_version_id)] = record
    return latest


def _target_slots(revision_request) -> set[str] | None:
    if revision_request is None or not revision_request.target_asset_version_ids:
        return None
    return {_asset_slot(value) for value in revision_request.target_asset_version_ids}


def _should_generate(slot: str, revision_request, target_slots: set[str] | None) -> bool:
    if revision_request is None or target_slots is None:
        return True
    return slot in target_slots


def _revision_direction(base: str, revision_request) -> str:
    if revision_request is None:
        return base
    guidance = ""
    if revision_request.revision_guidance:
        guidance = "\nSecondBrain revision guidance:\n" + "\n".join(
            f"- {item}" for item in revision_request.revision_guidance
        )
    return (
        f"{base}\n\nReviewer revision requirements:\n{revision_request.reason.strip()}\n"
        f"{guidance}\n"
        "Preserve the exact product and Variant identity from the supplied product source."
    )


def _provider_result(
    result: PaidMediaProductionResult | BaseException,
) -> PaidMediaProductionResult:
    if isinstance(result, Exception):
        return _provider_failure_result()
    if isinstance(result, BaseException):
        raise result
    return result


def _provider_failure_result() -> PaidMediaProductionResult:
    return PaidMediaProductionResult(
        success=False,
        attempts=(),
        selected_artifact=None,
        total_cost=Decimal("0"),
        outcome="provider_call_failed",
    )


def _failed_scene_result(
    results: tuple[PaidMediaProductionResult, ...],
) -> PaidMediaProductionResult:
    attempts = tuple(attempt for result in results for attempt in result.attempts)
    return PaidMediaProductionResult(
        success=False,
        attempts=attempts,
        selected_artifact=None,
        total_cost=sum((result.total_cost for result in results), start=Decimal("0")),
        outcome=(
            "provider_call_failed"
            if any(result.outcome == "provider_call_failed" for result in results)
            else "scene_technical_check_failed"
        ),
    )


def _next_asset_version(state: MarketingCreativeAutomationState) -> int:
    versions: list[int] = []
    for asset in state.production_assets:
        marker = asset.asset_version_id.rsplit(":v", 1)
        if len(marker) == 2 and marker[1].isdigit():
            versions.append(int(marker[1]))
    return max(versions, default=0) + 1


def _review_id(
    request_id: str,
    records: tuple[ProducedCreativeAssetRecord, ...],
) -> str:
    exact_versions = ":".join(
        f"{record.asset_version_id}:{record.selected_artifact.checksum_sha256}"
        for record in records
        if record.selected_artifact is not None
    )
    digest = hashlib.sha256(f"{request_id}:{exact_versions}".encode()).hexdigest()[:20]
    return f"creative-review-{digest}"


__all__ = ["MarketingCreativeAutomationProducer"]
