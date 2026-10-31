"""Composition root for managed Creative media production."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ai_content.domains.marketing.creative.adapters.managed_media import (
    ImmutableProductSourceResolver,
    ManagedMediaArtifactSink,
    NineRouterImageProvider,
    NineRouterVideoProvider,
    SourcePreservingImageProvider,
)
from ai_content.domains.marketing.creative.adapters.product_fidelity import (
    NineRouterProductFidelityEvaluator,
)
from ai_content.domains.marketing.creative.application.automation_production import (
    MarketingCreativeAutomationProducer,
)
from ai_content.domains.marketing.creative.application.provider_registry import (
    ManagedMediaProviderRegistry,
)
from ai_content.domains.marketing.creative.config.managed_media import (
    ManagedMediaConfig,
    load_managed_media_config,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    IMarketingCreativeAutomationStateRepository,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    PaidMediaGenerationLimits,
)
from ai_content.platform.artifacts import ArtifactService, ArtifactStore


@dataclass(frozen=True)
class ManagedMediaRuntime:
    providers: ManagedMediaProviderRegistry
    producer: MarketingCreativeAutomationProducer | None
    source_resolver: ImmutableProductSourceResolver | None = None


def build_managed_media_runtime(
    *,
    config_path: Path | None,
    api_key: str | None,
    image_api_key: str | None = None,
    video_api_key: str | None = None,
    artifact_store: ArtifactStore,
    artifact_service: ArtifactService | None,
    state_repository: IMarketingCreativeAutomationStateRepository,
) -> ManagedMediaRuntime:
    sink = ManagedMediaArtifactSink(artifact_store, artifact_service)
    source_preserving_image = SourcePreservingImageProvider(sink)
    config = load_managed_media_config(config_path) if config_path is not None else None
    credentials = {
        "ROUTER_API_KEY": api_key,
        "IMAGE_API_KEY": image_api_key,
        "VIDEO_API_KEY": video_api_key,
    }
    configured_image_key = (
        image_api_key
        or (config.resolved_image_api_key if config is not None else None)
        or (
            credentials.get(config.resolved_image_api_key_env)
            if config is not None and config.resolved_image_api_key_env
            else None
        )
        or api_key
    )
    configured_video_key = (
        video_api_key
        or (config.resolved_video_api_key if config is not None else None)
        or (
            credentials.get(config.resolved_video_api_key_env)
            if config is not None and config.resolved_video_api_key_env
            else None
        )
        or api_key
    )
    has_required_keys = bool(
        config is not None
        and (not config.resolved_image_models or configured_image_key)
        and (not config.resolved_video_models or configured_video_key)
    )
    effective = (
        config
        if config is not None and has_required_keys
        else config.model_copy(update={"approved": False})
        if config is not None
        else None
    )

    image_providers = [source_preserving_image]
    if effective is not None and effective.resolved_image_models:
        image_models = effective.resolved_image_models
        image_providers.append(
            NineRouterImageProvider(
                effective,
                image_models[0],
                configured_image_key or "not-configured",
                sink,
                models=image_models,
            )
        )

    video_providers = []
    default_video_provider_id: str | None = None
    if effective is not None and effective.resolved_video_models:
        video_models = effective.resolved_video_models
        video_providers.append(
            NineRouterVideoProvider(
                effective,
                video_models[0],
                configured_video_key or "not-configured",
                sink,
                models=video_models,
            )
        )
        default_video_provider_id = effective.profile_id

    providers = ManagedMediaProviderRegistry(
        image_providers=tuple(image_providers),
        video_providers=tuple(video_providers),
        default_image_provider_id=image_providers[-1].descriptor.provider_id,
        default_video_provider_id=default_video_provider_id,
    )
    active_configs: tuple[ManagedMediaConfig, ...] = (effective,) if effective is not None else ()
    resolver = ImmutableProductSourceResolver(
        sink,
        allowed_hosts=tuple(
            sorted(
                {"cdn.shopify.com"}
                | {host for item in active_configs for host in item.allowed_source_hosts}
            )
        ),
        timeout_seconds=max(
            (item.request_timeout_seconds for item in active_configs),
            default=30,
        ),
        max_bytes=max(
            (item.max_source_bytes for item in active_configs if item.max_source_bytes is not None),
            default=None,
        ),
    )
    image_limits = PaidMediaGenerationLimits(
        timeout_seconds=(effective.generation_timeout_seconds if effective is not None else 120),
        max_cost=Decimal("100000"),
        max_attempts=1,
        enforce_cost_limit=False,
    )
    video_limits = PaidMediaGenerationLimits(
        timeout_seconds=(effective.generation_timeout_seconds if effective is not None else 120),
        max_cost=Decimal("100000"),
        max_attempts=1,
        enforce_cost_limit=False,
    )
    image_evaluator = (
        NineRouterProductFidelityEvaluator(
            base_url=effective.resolved_image_base_url,
            api_key=configured_image_key,
            model=effective.fidelity_check_model,
            sink=sink,
            timeout_seconds=effective.request_timeout_seconds,
        )
        if effective is not None and effective.fidelity_check_model and configured_image_key
        else None
    )
    producer = MarketingCreativeAutomationProducer(
        state_repository,
        providers,
        resolver,
        image_limits=image_limits,
        video_limits=video_limits,
        max_concurrency=effective.max_concurrency if effective is not None else 2,
        image_evaluator=image_evaluator,
        max_image_attempts=effective.max_image_attempts if effective is not None else 1,
    )
    return ManagedMediaRuntime(providers, producer, resolver)


__all__ = ["ManagedMediaRuntime", "build_managed_media_runtime"]
