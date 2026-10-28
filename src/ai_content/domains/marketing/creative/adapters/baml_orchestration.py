"""BAML adapter for one provider-neutral selected-SKU orchestration call."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, fields, is_dataclass, replace
from typing import Protocol

from baml_py import Collector, Image
from baml_py.baml_py import BamlError
from baml_py.logging import set_log_level
from loguru import logger

from ai_content.domains.marketing.creative.application.model_context import (
    preparation_context_for_model,
)
from ai_content.domains.marketing.creative.config.orchestration import (
    OrchestrationConfig,
)
from ai_content.domains.marketing.creative.ports.contracts import (
    CreativeAutomationExecutionMode,
    CreativeReferenceSelectionMode,
    MarketingCreativeAutomationRequest,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    PaidMediaProviderDescriptor,
)
from ai_content.domains.marketing.creative.ports.orchestration import (
    ApprovedCreativeMemory,
    AssembledVideoCreativePlan,
    CreativeAutomationPlan,
    HumanPresenceMode,
    ImageCreativePlan,
    OrchestrationReadiness,
    VideoAudioCreativePlan,
    VideoGenerationStrategy,
    VideoMusicMode,
    VideoSceneCreativePlan,
    VideoVoiceMode,
)
from ai_content.domains.marketing.creative.ports.preparation import PreparationContext
from ai_content.domains.marketing.creative.ports.preparation_store import PreparedBrief
from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)
from ai_content.platform.llm_routing import route_approved_agent_model

from .baml_client import types as baml_types
from .baml_client.async_client import b
from .baml_model_profile import build_creative_orchestrator_registry
from .image_files import inspect_image, read_local_image


class _BamlOrchestrationClient(Protocol):
    async def OrchestrateCreativeAutomation(
        self,
        instructions: str,
        input_json: str,
        product_images: list[baml_types.LabeledReviewImage],
        image_count: int,
        video_count: int,
        duration_min_seconds: int,
        duration_max_seconds: int,
        source_duration_max_seconds: int,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeAutomationPlanDraft: ...


class BamlCreativeAutomationOrchestrator:
    def __init__(
        self,
        config: OrchestrationConfig,
        *,
        api_key: str | None,
        client: _BamlOrchestrationClient | None = None,
        usage_tracker: AIUsageTracker | None = None,
        image_provider_descriptor: PaidMediaProviderDescriptor | None = None,
        video_provider_descriptor: PaidMediaProviderDescriptor | None = None,
        image_reader: Callable[[str], bytes] | None = None,
    ) -> None:
        if config.backend != "baml":
            raise ValueError("BAML orchestrator requires a baml configuration")
        if config.api_key_env is not None and not api_key:
            raise ValueError("Configured orchestration model credential is missing")
        set_log_level("OFF")
        self._config = config
        self._api_key = api_key
        self._custom_client = client is not None
        self._usage_tracker = usage_tracker
        self._image_reader = image_reader or read_local_image
        self._provider_capabilities = {
            "image": _provider_capability(image_provider_descriptor),
            "video": _provider_capability(video_provider_descriptor),
        }
        self._client = client or b.with_options(
            client_registry=build_creative_orchestrator_registry(
                name="CreativeOrchestrator",
                base_url=config.base_url,
                model=config.model,
                api_key=api_key or "no-auth",
                reasoning_effort=config.reasoning_effort,
                temperature=config.temperature,
                max_output_tokens=config.max_output_tokens,
            )
        )

    async def plan(
        self,
        request: MarketingCreativeAutomationRequest,
        context: PreparationContext,
        prepared: PreparedBrief,
        memory: tuple[ApprovedCreativeMemory, ...],
    ) -> CreativeAutomationPlan:
        config = self._config
        client = self._client
        if (
            request.agent_model_id is not None or request.agent_reasoning_effort is not None
        ) and not self._custom_client:
            config = self._config.model_copy(
                update={
                    "model": (
                        route_approved_agent_model(
                            request.agent_model_id,
                            configured_model=self._config.model,
                        )
                        if request.agent_model_id is not None
                        else self._config.model
                    ),
                    "reasoning_effort": (
                        None
                        if request.agent_reasoning_effort in {None, "auto"}
                        else request.agent_reasoning_effort
                    ),
                }
            )
            client = b.with_options(
                client_registry=build_creative_orchestrator_registry(
                    name="CreativeOrchestrator",
                    base_url=config.base_url,
                    model=config.model,
                    api_key=self._api_key or "no-auth",
                    reasoning_effort=config.reasoning_effort,
                    temperature=config.temperature,
                    max_output_tokens=config.max_output_tokens,
                )
            )
        payload = json.dumps(
            {
                "request": asdict(request),
                "context": preparation_context_for_model(context),
                "prepared_brief": asdict(prepared),
                "approved_memory": [asdict(item) for item in memory],
                "provider_capabilities": self._provider_capabilities,
            },
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        if (
            config.max_context_bytes is not None
            and len(payload.encode()) > config.max_context_bytes
        ):
            raise ValueError("Orchestration model input exceeds the configured byte limit")
        collectors: list[Collector] = []
        event_id = None
        if self._usage_tracker is not None:
            event_id = await self._usage_tracker.start(
                AIUsageStart(
                    workstream="creative",
                    operation="automation.orchestration",
                    backend="baml",
                    model=config.model,
                    workflow_run_id=request.request_id,
                    job_id=request.request_id,
                    brand_id=request.brand,
                )
            )
        try:
            product_images = _product_images(context, self._image_reader)
            for attempt in range(config.max_attempts):
                retry_delay_seconds = config.retry_delay_seconds
                collector = Collector(
                    name=f"creative-orchestration-{request.request_id}-attempt-{attempt + 1}"
                )
                collectors.append(collector)
                try:
                    output = await asyncio.wait_for(
                        client.OrchestrateCreativeAutomation(
                            instructions=_retry_instructions(config.instructions, request, attempt),
                            input_json=payload,
                            product_images=product_images,
                            image_count=request.output.image_output_count,
                            video_count=request.output.video_output_count,
                            duration_min_seconds=request.output.video_duration_min_seconds,
                            duration_max_seconds=request.output.video_duration_max_seconds,
                            source_duration_max_seconds=request.output.video_scene_duration_max_seconds,
                            baml_options={"collector": collector},
                        ),
                        timeout=config.timeout_seconds,
                    )
                except (BamlError, TimeoutError) as error:
                    if attempt + 1 == config.max_attempts:
                        raise
                    retry_delay_seconds = _provider_retry_delay_seconds(
                        error, config.retry_delay_seconds
                    )
                    logger.warning(
                        "Creative orchestration model call failed; retrying "
                        "request_id={} attempt={} delay_seconds={} reason={}",
                        request.request_id,
                        attempt + 1,
                        retry_delay_seconds,
                        str(error),
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    continue
                request_count, input_tokens, output_tokens = _collectors_usage(collectors)
                try:
                    plan = _to_plan(
                        request,
                        output,
                        config,
                        memory,
                        product_family=getattr(
                            getattr(context, "sku", None), "product_family", None
                        ),
                        known_evidence_refs=_known_evidence_refs(context, prepared, memory),
                        provider_capabilities=self._provider_capabilities,
                        request_count=request_count,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                except ValueError as error:
                    if attempt + 1 == config.max_attempts:
                        raise
                    logger.warning(
                        "Creative orchestration plan validation failed; retrying "
                        "request_id={} attempt={} readiness={} image_plan_count={} "
                        "video_plan_count={} reason={}",
                        request.request_id,
                        attempt + 1,
                        output.readiness.value,
                        len(output.image_plans),
                        len(output.video_plans),
                        str(error),
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    continue
                break
        except Exception as error:
            if event_id is not None:
                request_count, input_tokens, output_tokens = _collectors_usage(collectors)
                await self._usage_tracker.fail(
                    event_id,
                    AIUsageFailure(
                        error_code=(
                            "orchestration_timeout"
                            if isinstance(error, TimeoutError)
                            else "orchestration_failed"
                        ),
                        request_count=request_count,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    ),
                )
            raise
        if event_id is not None:
            await self._usage_tracker.succeed(
                event_id,
                AIUsageCompletion(
                    request_count=request_count,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    output_count=1,
                ),
            )
        return plan


def _retry_instructions(
    instructions: str,
    request: MarketingCreativeAutomationRequest,
    attempt: int,
) -> str:
    if attempt == 0:
        return instructions
    audio_requirement = ""
    if request.video_generate_audio is False:
        audio_requirement = (
            " The request is silent: every video plan must use NONE for voice and music, "
            "and every voice_direction, music_direction, and scene audio_direction must be null."
        )
    elif request.video_generate_audio is True:
        audio_requirement = (
            " The request requires native audio: every video plan must enable voice or music "
            "and provide the required audio directions."
        )
    return (
        f"{instructions}\n\n"
        "Validation retry: return a complete, internally consistent plan. "
        f"For readiness READY, return exactly {request.output.image_output_count} image "
        f"plan(s) and exactly {request.output.video_output_count} video plan(s). "
        "Each video plan must contain at least one scene. Do not omit a requested "
        f"plan or scene.{audio_requirement}"
    )


def _provider_retry_delay_seconds(error: BaseException, default: float) -> float:
    """Honor a provider retry delay when BAML preserves it in the error message."""
    match = re.search(
        r"(?:retryDelay|retry in|reset after)[^0-9]{0,64}(\d+(?:\.\d+)?)s",
        str(error),
        flags=re.IGNORECASE,
    )
    if match is None:
        return default
    return max(default, min(float(match.group(1)), 60.0))


def _provider_capability(
    descriptor: PaidMediaProviderDescriptor | None,
) -> dict[str, object] | None:
    if descriptor is None:
        return None
    return {
        "provider_id": descriptor.provider_id,
        "media_kind": descriptor.media_kind,
        "supported_aspect_ratios": descriptor.supported_aspect_ratios,
        "supported_image_formats": descriptor.supported_image_formats,
        "max_reference_images": descriptor.max_reference_images,
        "supported_generation_durations_seconds": (
            descriptor.supported_generation_durations_seconds
        ),
        "supports_native_voice": descriptor.supports_native_voice,
        "supports_native_music": descriptor.supports_native_music,
        "image_models": [
            {
                "model_id": item.model_id,
                "supported_modes": item.supported_modes,
                "supported_aspect_ratios": item.supported_aspect_ratios,
                "supported_resolutions": item.supported_resolutions,
                "supported_qualities": item.supported_qualities,
                "supported_formats": item.supported_formats,
                "max_reference_images": item.max_reference_images,
                "supports_text_rendering": item.supports_text_rendering,
                "supports_logo_input": item.supports_logo_input,
            }
            for item in descriptor.image_models
        ],
        "video_models": [
            {
                "model_id": item.model_id,
                "supported_aspect_ratios": item.supported_aspect_ratios,
                "supported_resolutions": item.supported_resolutions,
                "supported_generation_durations_seconds": (
                    item.supported_generation_durations_seconds
                ),
                "max_reference_images": item.max_reference_images,
                "max_product_images": item.max_product_images,
                "reference_to_video_resolutions": item.reference_to_video_resolutions,
                "supports_native_voice": item.supports_native_voice,
                "supports_native_music": item.supports_native_music,
            }
            for item in descriptor.video_models
        ],
    }


def _to_plan(
    request,
    output,
    config: OrchestrationConfig,
    memory: tuple[ApprovedCreativeMemory, ...],
    *,
    product_family,
    known_evidence_refs: set[str],
    provider_capabilities: dict[str, dict[str, object] | None],
    request_count: int,
    input_tokens: int | None,
    output_tokens: int | None,
) -> CreativeAutomationPlan:
    readiness = OrchestrationReadiness(output.readiness.value.lower())
    candidate_ids = {item.reference_id for item in request.reference_candidates}
    image_plans = tuple(
        ImageCreativePlan(
            variation_key=item.variation_key,
            scenario=item.scenario,
            creative_hypothesis=item.creative_hypothesis,
            human_presence=HumanPresenceMode(item.human_presence.value.lower()),
            visual_direction=item.visual_direction,
            product_id=item.product_id or "",
            selected_variant_id=item.selected_variant_id,
            selected_media_ids=tuple(item.selected_media_ids or ()),
            reference_ids=_returned_reference_ids(
                item.reference_ids,
                item.evidence_refs,
                candidate_ids,
            ),
            reference_rationale=_reference_rationale(
                request,
                item.reference_rationale,
                _returned_reference_ids(
                    item.reference_ids,
                    item.evidence_refs,
                    candidate_ids,
                ),
            ),
            evidence_refs=tuple(item.evidence_refs),
        )
        for item in output.image_plans
    )
    if readiness == OrchestrationReadiness.READY:
        if len(image_plans) != request.output.image_output_count:
            raise ValueError("Orchestration model returned an unexpected image plan count")
        if any(
            not item.scenario.strip() or not item.creative_hypothesis.strip()
            for item in image_plans
        ):
            raise ValueError("Orchestration model returned an incomplete image brief")
    image_keys = tuple(item.variation_key for item in image_plans)
    if len(image_keys) != len(set(image_keys)):
        raise ValueError("Orchestration model returned duplicate image variation keys")

    video_plans = tuple(
        _video_plan(request, item, candidate_ids=candidate_ids) for item in output.video_plans
    )
    if (
        readiness == OrchestrationReadiness.READY
        and len(video_plans) != request.output.video_output_count
    ):
        raise ValueError("Orchestration model returned an unexpected video plan count")
    video_keys = tuple(item.variation_key for item in video_plans)
    if len(video_keys) != len(set(video_keys)):
        raise ValueError("Orchestration model returned duplicate video variation keys")

    image_plans, video_plans = _apply_human_references(
        request, candidate_ids, image_plans, video_plans
    )
    _validate_reference_evidence(request, image_plans, video_plans)
    known_evidence_refs.update(item.reference_id for item in request.reference_candidates)

    returned_evidence_refs = {
        *output.evidence_refs,
        *(ref for item in image_plans for ref in item.evidence_refs),
        *(ref for item in video_plans for ref in item.evidence_refs),
        *(ref for plan in video_plans for scene in plan.scenes for ref in scene.evidence_refs),
    }
    unknown_evidence_refs = returned_evidence_refs - known_evidence_refs
    if unknown_evidence_refs:
        raise ValueError("Orchestration model returned unknown evidence references")
    if readiness == OrchestrationReadiness.READY and product_family is not None:
        _validate_product_selections(request, product_family, image_plans, video_plans)
        _validate_product_source_budgets(
            request,
            product_family,
            image_plans,
            video_plans,
            provider_capabilities,
        )
    digest = hashlib.sha256(
        json.dumps(output.model_dump(), sort_keys=True, default=str).encode()
    ).hexdigest()[:20]
    return CreativeAutomationPlan(
        plan_id=f"creative-automation-plan-{digest}",
        readiness=readiness,
        strategy_summary=output.strategy_summary,
        rationale=output.rationale,
        evidence_refs=tuple(output.evidence_refs),
        image_plans=image_plans,
        video_plans=video_plans,
        missing_context=tuple(output.missing_context),
        uncertainties=tuple(output.uncertainties),
        memory_refs=tuple(item.memory_id for item in memory),
        model_profile=config.profile_id,
        prompt_version=config.prompt_version,
        request_count=request_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _assigned_reference_ids(request, output_key: str) -> tuple[str, ...]:
    assignment = next(
        (item for item in request.reference_assignments if item.output_key == output_key),
        None,
    )
    return assignment.reference_ids if assignment is not None else ()


def _returned_reference_ids(explicit, evidence_refs, candidate_ids: set[str]) -> tuple[str, ...]:
    if explicit is not None:
        return tuple(explicit)
    return tuple(item for item in evidence_refs if item in candidate_ids)


def _reference_rationale(request, provided, selected_reference_ids) -> str:
    if provided:
        return provided
    mode = request.reference_selection_mode
    if mode == CreativeReferenceSelectionMode.NONE and request.reference_assignments:
        mode = CreativeReferenceSelectionMode.HUMAN
    if mode == CreativeReferenceSelectionMode.HUMAN and selected_reference_ids:
        return "Human-selected Research references."
    return ""


def _with_references(evidence_refs, reference_ids, candidate_ids) -> tuple[str, ...]:
    others = tuple(item for item in evidence_refs if item not in candidate_ids)
    return (*others, *reference_ids)


def _apply_human_references(request, candidate_ids, image_plans, video_plans):
    """Human assignments are authoritative, so set them in code instead of trusting the model."""

    mode = request.reference_selection_mode
    if mode == CreativeReferenceSelectionMode.NONE and request.reference_assignments:
        mode = CreativeReferenceSelectionMode.HUMAN
    if mode != CreativeReferenceSelectionMode.HUMAN:
        return image_plans, video_plans

    def align(output_key, plan):
        ids = _assigned_reference_ids(request, output_key)
        return replace(
            plan,
            reference_ids=ids,
            reference_rationale=_reference_rationale(request, plan.reference_rationale, ids),
            evidence_refs=_with_references(plan.evidence_refs, ids, candidate_ids),
        )

    images = tuple(align(f"image:{i}", plan) for i, plan in enumerate(image_plans, start=1))
    videos = []
    for index, plan in enumerate(video_plans, start=1):
        aligned = align(f"video:{index}", plan)
        scenes = tuple(
            replace(
                scene,
                evidence_refs=_with_references(
                    scene.evidence_refs, aligned.reference_ids, candidate_ids
                ),
            )
            for scene in aligned.scenes
        )
        videos.append(replace(aligned, scenes=scenes))
    return images, tuple(videos)


def _validate_reference_evidence(request, image_plans, video_plans) -> None:
    candidate_ids = {item.reference_id for item in request.reference_candidates}

    mode = request.reference_selection_mode
    if mode == CreativeReferenceSelectionMode.NONE and request.reference_assignments:
        mode = CreativeReferenceSelectionMode.HUMAN

    def validate(output_key, reference_ids, rationale, evidence_refs, scene_refs=()) -> None:
        if len(reference_ids) != len(set(reference_ids)) or not set(reference_ids).issubset(
            candidate_ids
        ):
            raise ValueError("Orchestration model selected an unavailable Research reference")
        if reference_ids and not rationale.strip():
            raise ValueError("Orchestration model omitted the Research reference rationale")
        selected_evidence = tuple(item for item in evidence_refs if item in candidate_ids)
        if selected_evidence != reference_ids or any(
            tuple(item for item in refs if item in candidate_ids) != reference_ids
            for refs in scene_refs
        ):
            raise ValueError("Orchestration model returned inconsistent Research evidence")
        assigned = _assigned_reference_ids(request, output_key)
        if mode == CreativeReferenceSelectionMode.HUMAN and reference_ids != assigned:
            media_kind = output_key.split(":", maxsplit=1)[0]
            raise ValueError(
                f"Orchestration model changed the human-assigned {media_kind} references"
            )
        if mode == CreativeReferenceSelectionMode.NONE and reference_ids:
            raise ValueError("Orchestration model selected Research when it was disabled")

    for index, plan in enumerate(image_plans, start=1):
        validate(
            f"image:{index}",
            plan.reference_ids,
            plan.reference_rationale,
            plan.evidence_refs,
        )

    for index, plan in enumerate(video_plans, start=1):
        validate(
            f"video:{index}",
            plan.reference_ids,
            plan.reference_rationale,
            plan.evidence_refs,
            tuple(scene.evidence_refs for scene in plan.scenes),
        )


def _selected_model_source_limit(
    capability: dict[str, object] | None,
    *,
    model_id: str | None,
    models_key: str,
) -> int | None:
    if capability is None:
        return None
    models = capability.get(models_key)
    if isinstance(models, list):
        selected = next(
            (
                item
                for item in models
                if isinstance(item, dict) and item.get("model_id") == model_id
            ),
            None,
        )
        if selected is not None:
            value = selected.get("max_reference_images")
            return int(value) if value is not None else None
    value = capability.get("max_reference_images")
    return int(value) if value is not None else None


def _selected_image_model_modes(
    capability: dict[str, object] | None,
    model_id: str | None,
) -> set[str]:
    if capability is None:
        return set()
    models = capability.get("image_models")
    if not isinstance(models, list):
        return set()
    selected = next(
        (item for item in models if isinstance(item, dict) and item.get("model_id") == model_id),
        None,
    )
    modes = selected.get("supported_modes") if selected is not None else None
    return {str(item) for item in modes} if isinstance(modes, (list, tuple)) else set()


def _validate_product_source_budgets(
    request,
    product_family,
    image_plans,
    video_plans,
    provider_capabilities: dict[str, dict[str, object] | None],
) -> None:
    image_limit = _selected_model_source_limit(
        provider_capabilities.get("image"),
        model_id=request.image_model_id,
        models_key="image_models",
    )
    image_modes = _selected_image_model_modes(
        provider_capabilities.get("image"),
        request.image_model_id,
    )
    for plan in image_plans:
        multiple_product_sources_fit = len(product_family.media) >= 2 and (
            image_limit is None
            or 2 + len(plan.reference_ids) + int(request.include_logo) <= image_limit
        )
        if (
            request.image_generation_mode == "single_image_edit"
            and len(plan.selected_media_ids) != 1
        ):
            raise ValueError("Orchestration model must select exactly one Shopify image")
        if (
            request.image_generation_mode == "multi_image_edit"
            and multiple_product_sources_fit
            and len(plan.selected_media_ids) < 2
        ):
            raise ValueError("Orchestration model omitted available multi-image Product context")
        if request.image_generation_mode == "multi_image_edit" and len(plan.selected_media_ids) > 3:
            raise ValueError("Orchestration model selected more than three Shopify images")
        if image_limit is not None and (
            len(plan.selected_media_ids) + len(plan.reference_ids) + int(request.include_logo)
            > image_limit
        ):
            raise ValueError("Orchestration model exceeded the image model source limit")
        if (
            request.execution_mode == CreativeAutomationExecutionMode.GENERATE_ONCE
            and plan.reference_ids
            and "multi_image_edit" not in image_modes
        ):
            raise ValueError("Selected image model cannot receive Research reference images")

    video_limit = _selected_model_source_limit(
        provider_capabilities.get("video"),
        model_id=request.video_model_id,
        models_key="video_models",
    )
    selected_video_model = _selected_video_model_capability(
        provider_capabilities.get("video"), request.video_model_id
    )
    max_product_images = int(selected_video_model.get("max_product_images", 1))
    reference_resolutions = {
        str(item) for item in selected_video_model.get("reference_to_video_resolutions", ())
    }
    reference_to_video = request.video_resolution in reference_resolutions
    available_product_images = len(product_family.media)
    for plan in video_plans:
        reference_count = len(plan.reference_ids)
        if video_limit is not None and any(
            len(scene.selected_media_ids) + reference_count > video_limit for scene in plan.scenes
        ):
            raise ValueError("Orchestration model exceeded the video model source limit")
        for scene in plan.scenes:
            product_count = len(scene.selected_media_ids)
            if reference_to_video and available_product_images >= 2:
                maximum = min(3, max_product_images, (video_limit or 10_000) - reference_count)
                if product_count < 2 or product_count > maximum:
                    raise ValueError(
                        "Reference-to-video requires two or three Shopify product images"
                    )
            elif product_count != 1 or reference_count:
                raise ValueError(
                    "Image-to-video fallback requires one product image and no Research reference"
                )


def _selected_video_model_capability(
    capability: dict[str, object] | None,
    model_id: str | None,
) -> dict[str, object]:
    if capability is None:
        return {}
    models = capability.get("video_models")
    if not isinstance(models, list):
        return {}
    return next(
        (item for item in models if isinstance(item, dict) and item.get("model_id") == model_id),
        {},
    )


def _product_images(
    context: PreparationContext, image_reader: Callable[[str], bytes] = read_local_image
) -> list[baml_types.LabeledReviewImage]:
    family = getattr(getattr(context, "sku", None), "product_family", None)
    if family is None:
        return []
    images: list[baml_types.LabeledReviewImage] = []
    for media in family.media:
        if media.artifact_ref is None:
            continue
        content = image_reader(media.artifact_ref)
        _, _, image_format = inspect_image(content)
        mime = "image/jpeg" if image_format == "jpeg" else f"image/{image_format}"
        images.append(
            baml_types.LabeledReviewImage(
                label=f"shopify_media:{media.media_id}",
                content=Image.from_base64(mime, base64.b64encode(content).decode("ascii")),
            )
        )
    return images


def _video_plan(
    request,
    item,
    *,
    candidate_ids: set[str] | None = None,
) -> AssembledVideoCreativePlan:
    candidate_ids = candidate_ids or set()
    duration = item.final_duration_seconds
    if (
        not request.output.video_duration_min_seconds
        <= duration
        <= request.output.video_duration_max_seconds
    ):
        raise ValueError("Orchestration model selected a final video duration outside the profile")
    scenes = tuple(
        VideoSceneCreativePlan(
            scene_id=scene.scene_id,
            purpose=scene.purpose,
            visual_direction=scene.visual_direction,
            audio_direction=scene.audio_direction,
            transition_direction=scene.transition_direction,
            duration_seconds=scene.usable_duration_seconds,
            evidence_refs=tuple(scene.evidence_refs),
            generation_duration_seconds=scene.generation_duration_seconds,
            selected_variant_id=scene.selected_variant_id,
            selected_media_ids=tuple(scene.selected_media_ids or ()),
        )
        for scene in item.scenes
    )
    if any(
        scene.resolved_generation_duration_seconds > request.output.video_scene_duration_max_seconds
        for scene in scenes
    ):
        raise ValueError("Orchestration model selected a source outside provider capability")
    audio_plan = VideoAudioCreativePlan(
        voice_mode=VideoVoiceMode(item.audio_plan.voice_mode.value.lower()),
        music_mode=VideoMusicMode(item.audio_plan.music_mode.value.lower()),
        voice_direction=item.audio_plan.voice_direction,
        music_direction=item.audio_plan.music_direction,
        continuity_direction=item.audio_plan.continuity_direction,
    )
    plan = AssembledVideoCreativePlan(
        variation_key=item.variation_key,
        scenario=item.scenario,
        creative_hypothesis=item.creative_hypothesis,
        human_presence=HumanPresenceMode(item.human_presence.value.lower()),
        generation_strategy=VideoGenerationStrategy(item.generation_strategy.value.lower()),
        final_duration_seconds=duration,
        continuity_plan=item.continuity_plan,
        product_id=item.product_id or "",
        audio_plan=audio_plan,
        reference_ids=_returned_reference_ids(
            item.reference_ids,
            item.evidence_refs,
            candidate_ids,
        ),
        reference_rationale=_reference_rationale(
            request,
            item.reference_rationale,
            _returned_reference_ids(
                item.reference_ids,
                item.evidence_refs,
                candidate_ids,
            ),
        ),
        scenes=scenes,
        background_music_direction=audio_plan.music_direction,
        evidence_refs=tuple(item.evidence_refs),
    )
    if any(
        not value.strip()
        for value in (
            plan.variation_key,
            plan.scenario,
            plan.creative_hypothesis,
            plan.continuity_plan,
        )
    ):
        raise ValueError("Orchestration model returned an incomplete video brief")
    if (
        plan.generation_strategy == VideoGenerationStrategy.ONE_SHOT
        and plan.final_duration_seconds > request.output.video_scene_duration_max_seconds
    ):
        raise ValueError("Orchestration model selected an impossible one-shot duration")
    if (
        plan.final_duration_seconds <= request.output.video_scene_duration_max_seconds
        and plan.generation_strategy != VideoGenerationStrategy.ONE_SHOT
    ):
        raise ValueError("Orchestration model split a duration supported by one shot")
    if (
        plan.final_duration_seconds > request.output.video_scene_duration_max_seconds
        and plan.generation_strategy != VideoGenerationStrategy.MULTI_SOURCE
    ):
        raise ValueError("Orchestration model did not split a duration beyond one shot")
    if plan.generation_strategy == VideoGenerationStrategy.MULTI_SOURCE and any(
        not scene.transition_direction.strip() for scene in plan.scenes
    ):
        raise ValueError("Orchestration model omitted a multi-source transition plan")
    if request.video_generate_audio is True and not plan.audio_plan.expects_audio:
        raise ValueError("Orchestration model omitted audio enabled by the request")
    if request.video_generate_audio is False and plan.audio_plan.expects_audio:
        raise ValueError("Orchestration model returned audio disabled by the request")
    if plan.audio_plan.expects_audio:
        if not plan.audio_plan.continuity_direction.strip():
            raise ValueError("Orchestration model omitted the audio continuity plan")
        if any(not (scene.audio_direction or "").strip() for scene in plan.scenes):
            raise ValueError("Orchestration model omitted scene audio direction")
    elif any(scene.audio_direction is not None for scene in plan.scenes):
        raise ValueError("Orchestration model returned audio outside the planned audio scope")
    return plan


def _validate_product_selections(request, family, image_plans, video_plans) -> None:
    variants = {item.variant_id: item for item in family.variants}
    media = {item.media_id: item for item in family.media}

    def validate(product_id: str, variant_id: str | None, media_ids: tuple[str, ...]) -> None:
        if product_id != family.ref.product_id:
            raise ValueError("Orchestration model returned an unknown Product Family")
        if not media_ids or not set(media_ids).issubset(media):
            raise ValueError("Orchestration model returned unknown or empty Product media IDs")
        if request.selected_variant_id is not None and variant_id != request.selected_variant_id:
            raise ValueError("Orchestration model changed the pinned Product variant")
        if variant_id is None:
            if any(media[item].variant_ids for item in media_ids):
                raise ValueError("Family-level output selected variant-specific media")
            return
        if variant_id not in variants:
            raise ValueError("Orchestration model returned an unknown Product variant")
        if any(
            media[item].variant_ids and variant_id not in media[item].variant_ids
            for item in media_ids
        ):
            raise ValueError("Orchestration model mixed media from another Product variant")

    for plan in image_plans:
        validate(plan.product_id, plan.selected_variant_id, plan.selected_media_ids)
    for plan in video_plans:
        if plan.product_id != family.ref.product_id:
            raise ValueError("Orchestration model returned an unknown Product Family")
        for scene in plan.scenes:
            validate(plan.product_id, scene.selected_variant_id, scene.selected_media_ids)
        selected_variants = {scene.selected_variant_id for scene in plan.scenes}
        if len(selected_variants) != 1:
            raise ValueError("One video output cannot mix Product variants across scenes")


def _known_evidence_refs(
    context: PreparationContext,
    prepared: PreparedBrief,
    memory: tuple[ApprovedCreativeMemory, ...],
) -> set[str]:
    known: set[str] = set()

    def visit(value: object, field_name: str | None = None) -> None:
        if value is None:
            return
        if field_name in {"source_id", "reference_id", "claim_id"} and isinstance(value, str):
            known.add(value)
            return
        if field_name == "evidence_refs" and isinstance(value, (list, tuple)):
            known.update(item for item in value if isinstance(item, str))
            return
        if is_dataclass(value):
            for item in fields(value):
                visit(getattr(value, item.name), item.name)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, str(key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(context)
    visit(prepared)
    visit(memory)
    return known


def _collector_usage(collector: Collector) -> tuple[int, int | None, int | None]:
    log = collector.last
    usage = collector.usage
    return (
        max(1, len(log.calls)) if log is not None else 1,
        usage.input_tokens,
        usage.output_tokens,
    )


def _collectors_usage(collectors: list[Collector]) -> tuple[int, int | None, int | None]:
    request_count = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for collector in collectors:
        calls, current_input_tokens, current_output_tokens = _collector_usage(collector)
        request_count += calls
        if current_input_tokens is not None:
            input_tokens = (input_tokens or 0) + current_input_tokens
        if current_output_tokens is not None:
            output_tokens = (output_tokens or 0) + current_output_tokens
    return request_count, input_tokens, output_tokens


__all__ = ["BamlCreativeAutomationOrchestrator"]
