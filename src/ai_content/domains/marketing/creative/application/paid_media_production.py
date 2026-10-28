"""Bounded generate-once paid media production with human review."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from decimal import Decimal

from ai_content.domains.marketing.creative.application.provider_registry import (
    ManagedMediaProviderRegistry,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    IPaidImageQualityEvaluator,
    PaidAssembledVideoRequest,
    PaidImageGenerationRequest,
    PaidMediaArtifact,
    PaidMediaGenerationLimits,
    PaidMediaQualityEvaluation,
    PaidMediaSource,
    PaidVideoGenerationRequest,
)


@dataclass(frozen=True)
class PaidMediaAttempt:
    attempt_number: int
    artifact: PaidMediaArtifact
    evaluation: PaidMediaQualityEvaluation


@dataclass(frozen=True)
class PaidMediaProductionResult:
    success: bool
    attempts: tuple[PaidMediaAttempt, ...]
    selected_artifact: PaidMediaArtifact | None
    total_cost: Decimal
    outcome: str


class PaidMediaProductionService:
    def __init__(
        self,
        providers: ManagedMediaProviderRegistry,
        *,
        max_concurrency: int = 10,
        image_evaluator: IPaidImageQualityEvaluator | None = None,
        max_image_attempts: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("Paid media concurrency must be positive")
        if max_image_attempts < 1:
            raise ValueError("Paid image attempts must be positive")
        self._providers = providers
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._image_evaluator = image_evaluator
        self._max_image_attempts = max_image_attempts

    async def produce_image(
        self,
        request: PaidImageGenerationRequest,
    ) -> PaidMediaProductionResult:
        provider = self._providers.require_image(request.provider_id)
        _validate_provider_image_capability(provider.descriptor, request)
        if self._image_evaluator is None or provider.descriptor.fidelity_mode != "generative":
            return _result(request.limits, await self._generate_image(provider, request))
        attempts: list[PaidMediaAttempt] = []
        attempt_request = request
        for attempt_number in range(1, self._max_image_attempts + 1):
            artifact = await self._generate_image(provider, attempt_request)
            evaluation = await self._image_evaluator.evaluate_image(attempt_request, artifact)
            if evaluation.outcome == "revise" and attempt_number == self._max_image_attempts:
                evaluation = replace(
                    evaluation,
                    outcome="human_review",
                    summary=f"Product fidelity still failing after {attempt_number} attempts. "
                    f"{evaluation.summary}",
                    issues=tuple(
                        replace(item, repair_instruction=None) for item in evaluation.issues
                    ),
                )
            attempts.append(PaidMediaAttempt(attempt_number, artifact, evaluation))
            if evaluation.outcome != "revise":
                break
            repairs = " ".join(
                item.repair_instruction for item in evaluation.issues if item.repair_instruction
            )
            attempt_request = _repair_request(
                provider.descriptor, request, artifact, attempt_number + 1, repairs
            )
        total_cost = sum((item.artifact.cost for item in attempts), start=Decimal("0"))
        return PaidMediaProductionResult(
            True,
            tuple(attempts),
            attempts[-1].artifact,
            total_cost,
            "ready_for_review",
        )

    async def _generate_image(self, provider, request: PaidImageGenerationRequest):
        async with self._semaphore:
            return await asyncio.wait_for(
                provider.generate(request),
                timeout=request.limits.timeout_seconds,
            )

    async def assemble_video(
        self,
        request: PaidAssembledVideoRequest,
    ) -> PaidMediaProductionResult:
        if not request.scene_artifacts:
            raise ValueError("Assembled video requires generated scene artifacts")
        provider = self._providers.require_video()
        if request.aspect_ratio not in provider.descriptor.supported_aspect_ratios:
            raise ValueError("Paid video provider does not support the requested aspect ratio")
        async with self._semaphore:
            artifact = await asyncio.wait_for(
                provider.assemble(request),
                timeout=request.limits.timeout_seconds,
            )
        return _result(request.limits, artifact)

    async def still_frame(
        self, clip: PaidMediaArtifact, at_seconds: float, request_id: str
    ) -> PaidMediaArtifact:
        return await self._providers.require_video().still_frame(clip, at_seconds, request_id)

    async def produce_video(
        self,
        request: PaidVideoGenerationRequest,
    ) -> PaidMediaProductionResult:
        provider = self._providers.require_video()
        _validate_provider_video_capability(provider.descriptor, request)
        async with self._semaphore:
            artifact = await asyncio.wait_for(
                provider.generate(request),
                timeout=request.limits.timeout_seconds,
            )
        return _result(request.limits, artifact)


def _result(
    limits: PaidMediaGenerationLimits,
    artifact: PaidMediaArtifact,
) -> PaidMediaProductionResult:
    if limits.enforce_cost_limit and artifact.cost > limits.max_cost:
        attempt = PaidMediaAttempt(
            1,
            artifact,
            PaidMediaQualityEvaluation(
                "human_review",
                "Provider output exceeded the configured cost limit.",
            ),
        )
        return PaidMediaProductionResult(
            False,
            (attempt,),
            None,
            artifact.cost,
            "cost_limit_exceeded",
        )
    evaluation = PaidMediaQualityEvaluation("pass", _review_summary(artifact))
    attempt = PaidMediaAttempt(1, artifact, evaluation)
    return PaidMediaProductionResult(
        True,
        (attempt,),
        artifact,
        artifact.cost,
        "ready_for_review",
    )


def _review_summary(artifact: PaidMediaArtifact) -> str:
    if artifact.fidelity_mode == "exact_source_transform":
        return (
            "Exact Shopify source transform received from the provider. "
            "Automated output validation is disabled; human review is required."
        )
    return "Provider output received. Automated output validation is disabled; human review is required."


def _validate_provider_image_capability(descriptor, request: PaidImageGenerationRequest) -> None:
    ratio = _aspect_ratio(request.width, request.height)
    selected_model = next(
        (item for item in descriptor.image_models if item.model_id == request.model_id),
        None,
    )
    if descriptor.image_models and selected_model is None:
        raise ValueError("Paid image provider does not support the selected model")
    supported_ratios = (
        selected_model.supported_aspect_ratios
        if selected_model is not None
        else descriptor.supported_aspect_ratios
    )
    if ratio not in supported_ratios:
        raise ValueError("Paid image provider does not support the requested aspect ratio")
    maximum_sources = (
        selected_model.max_reference_images
        if selected_model is not None
        else descriptor.max_reference_images
    )
    source_count = len(request.sources) + int(request.logo_source is not None)
    if source_count > maximum_sources:
        raise ValueError("Paid image provider does not support the selected source count")
    if selected_model is None:
        return
    if request.resolution not in selected_model.supported_resolutions:
        raise ValueError("Paid image provider does not support the selected resolution")
    if selected_model.supported_qualities:
        if request.quality not in selected_model.supported_qualities:
            raise ValueError("Paid image provider does not support the selected quality")
    elif request.quality is not None:
        raise ValueError("Paid image provider does not accept a quality setting")
    if request.generation_mode not in selected_model.supported_modes:
        raise ValueError("Paid image provider does not support the selected edit mode")
    if request.include_text and not selected_model.supports_text_rendering:
        raise ValueError("Paid image provider does not support generated text")
    if request.include_logo and not selected_model.supports_logo_input:
        raise ValueError("Paid image provider does not support logo input")


def _validate_provider_video_capability(
    descriptor,
    request: PaidVideoGenerationRequest,
) -> None:
    if request.aspect_ratio not in descriptor.supported_aspect_ratios:
        raise ValueError("Paid video provider does not support the requested aspect ratio")
    if len(request.sources) > descriptor.max_reference_images:
        raise ValueError("Paid video provider does not support the selected source count")
    if descriptor.duration_min_seconds is None or descriptor.duration_max_seconds is None:
        raise ValueError("Paid video provider did not declare duration capabilities")
    if request.duration_seconds not in descriptor.supported_generation_durations_seconds:
        raise ValueError("Paid video provider cannot produce the selected generation duration")
    if request.voice_mode != "none" and not descriptor.supports_native_voice:
        raise ValueError("Paid video provider does not support the planned native voice")
    if request.music_mode != "none" and not descriptor.supports_native_music:
        raise ValueError("Paid video provider does not support the planned native music")


def _aspect_ratio(width: int, height: int) -> str:
    divisor = _greatest_common_divisor(width, height)
    return f"{width // divisor}:{height // divisor}"


def _greatest_common_divisor(left: int, right: int) -> int:
    while right:
        left, right = right, left % right
    return left


def _repair_request(
    descriptor,
    request: PaidImageGenerationRequest,
    artifact: PaidMediaArtifact,
    attempt_number: int,
    repairs: str,
) -> PaidImageGenerationRequest:
    """Fix only what failed by editing the generated image, not by redrawing the scene."""

    request_id = f"{request.request_id}:attempt-{attempt_number}"
    model = next(
        (item for item in descriptor.image_models if item.model_id == request.model_id),
        None,
    )
    limit = model.max_reference_images if model is not None else descriptor.max_reference_images
    can_edit = model is not None and "multi_image_edit" in model.supported_modes
    slots = limit - 1 - (1 if request.logo_source else 0)
    products = tuple(item for item in request.sources if item.role == "product")[:slots]
    if not can_edit or not products or not repairs:
        return replace(
            request,
            request_id=request_id,
            visual_direction=f"{request.visual_direction} Product corrections: {repairs}",
        )
    draft = PaidMediaSource(artifact.artifact_ref, artifact.checksum_sha256, "draft")
    return replace(
        request,
        request_id=request_id,
        visual_direction=repairs,
        sources=(draft, *products),
        generation_mode="multi_image_edit",
    )


__all__ = [
    "PaidMediaAttempt",
    "PaidMediaProductionResult",
    "PaidMediaProductionService",
]
