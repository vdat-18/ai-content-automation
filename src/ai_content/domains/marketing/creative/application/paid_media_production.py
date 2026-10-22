"""Bounded generate-once paid media production with human review."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from ai_content.domains.marketing.creative.application.provider_registry import (
    ManagedMediaProviderRegistry,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    PaidAssembledVideoRequest,
    PaidImageGenerationRequest,
    PaidMediaArtifact,
    PaidMediaGenerationLimits,
    PaidMediaQualityEvaluation,
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
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("Paid media concurrency must be positive")
        self._providers = providers
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def produce_image(
        self,
        request: PaidImageGenerationRequest,
    ) -> PaidMediaProductionResult:
        provider = self._providers.require_image(request.provider_id)
        _validate_provider_image_capability(provider.descriptor, request)
        async with self._semaphore:
            artifact = await asyncio.wait_for(
                provider.generate(request),
                timeout=request.limits.timeout_seconds,
            )
        return _result(request.limits, artifact)

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


__all__ = [
    "PaidMediaAttempt",
    "PaidMediaProductionResult",
    "PaidMediaProductionService",
]
