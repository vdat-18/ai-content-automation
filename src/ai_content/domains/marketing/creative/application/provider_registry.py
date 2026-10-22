"""Fail-closed selection of explicitly approved paid media providers."""

from __future__ import annotations

from typing import TypeVar

from ai_content.domains.marketing.creative.ports.media_production import (
    IManagedImageGenerationProvider,
    IManagedVideoGenerationProvider,
    PaidMediaProviderUnavailableError,
)

ProviderT = TypeVar("ProviderT", IManagedImageGenerationProvider, IManagedVideoGenerationProvider)


class ManagedMediaProviderRegistry:
    def __init__(
        self,
        *,
        image_providers: tuple[IManagedImageGenerationProvider, ...] = (),
        video_providers: tuple[IManagedVideoGenerationProvider, ...] = (),
        default_image_provider_id: str | None = None,
        default_video_provider_id: str | None = None,
    ) -> None:
        self._image_providers = _providers_by_id(image_providers, "image")
        self._video_providers = _providers_by_id(video_providers, "video")
        self._default_image_provider_id = default_image_provider_id
        self._default_video_provider_id = default_video_provider_id

    def image_status(self, provider_id: str | None = None) -> str:
        return self._status(
            self._image_providers,
            provider_id or self._default_image_provider_id,
        )

    def video_status(self) -> str:
        return self._status(self._video_providers, self._default_video_provider_id)

    def image_descriptor(self, provider_id: str | None = None):
        return self._descriptor(
            self._image_providers,
            provider_id or self._default_image_provider_id,
        )

    def image_descriptors(self):
        return tuple(provider.descriptor for provider in self._image_providers.values())

    def video_descriptor(self):
        return self._descriptor(self._video_providers, self._default_video_provider_id)

    @staticmethod
    def _descriptor(providers: dict[str, ProviderT], default_provider_id: str | None):
        provider = providers.get(default_provider_id) if default_provider_id is not None else None
        return provider.descriptor if provider is not None else None

    def require_image(self, provider_id: str | None = None) -> IManagedImageGenerationProvider:
        return self._require(
            self._image_providers,
            provider_id or self._default_image_provider_id,
            "image",
        )

    def require_video(self) -> IManagedVideoGenerationProvider:
        return self._require(
            self._video_providers,
            self._default_video_provider_id,
            "video",
        )

    @staticmethod
    def _status(providers: dict[str, ProviderT], default_provider_id: str | None) -> str:
        if default_provider_id is None:
            return "not_configured"
        provider = providers.get(default_provider_id)
        if provider is None or not provider.descriptor.approved:
            return "not_approved"
        return "ready"

    @staticmethod
    def _require(
        providers: dict[str, ProviderT],
        default_provider_id: str | None,
        media_kind: str,
    ) -> ProviderT:
        if default_provider_id is None:
            raise PaidMediaProviderUnavailableError(
                f"No default paid {media_kind} provider is configured"
            )
        provider = providers.get(default_provider_id)
        if provider is None:
            raise PaidMediaProviderUnavailableError(
                f"Configured paid {media_kind} provider is unavailable"
            )
        if not provider.descriptor.approved:
            raise PaidMediaProviderUnavailableError(
                f"Configured paid {media_kind} provider is not approved"
            )
        return provider


def _providers_by_id(providers: tuple[ProviderT, ...], media_kind: str) -> dict[str, ProviderT]:
    by_id: dict[str, ProviderT] = {}
    for provider in providers:
        descriptor = provider.descriptor
        if descriptor.media_kind != media_kind:
            raise ValueError(f"Provider {descriptor.provider_id} has the wrong media kind")
        if descriptor.provider_id in by_id:
            raise ValueError(f"Duplicate paid media provider: {descriptor.provider_id}")
        by_id[descriptor.provider_id] = provider
    return by_id


__all__ = ["ManagedMediaProviderRegistry"]
