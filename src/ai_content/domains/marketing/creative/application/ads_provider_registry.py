"""Fail-closed registry for approved least-privilege Ads activation providers."""

from __future__ import annotations

from ai_content.domains.marketing.creative.ports.ads_activation import (
    AdsActivationDisabledError,
    IAdsActivationProvider,
)


class AdsActivationProviderRegistry:
    def __init__(
        self,
        providers: tuple[IAdsActivationProvider, ...] = (),
        *,
        default_provider_ids: dict[str, str] | None = None,
    ) -> None:
        self._providers: dict[str, IAdsActivationProvider] = {}
        for provider in providers:
            provider_id = provider.descriptor.provider_id
            if provider_id in self._providers:
                raise ValueError(f"Duplicate Ads activation provider: {provider_id}")
            self._providers[provider_id] = provider
        self._defaults = dict(default_provider_ids or {})

    def status(self, platform: str) -> str:
        provider_id = self._defaults.get(platform)
        if provider_id is None:
            return "not_configured"
        provider = self._providers.get(provider_id)
        if provider is None or not provider.descriptor.approved:
            return "not_approved"
        if not provider.descriptor.least_privilege:
            return "permissions_too_broad"
        if provider.descriptor.platform != platform:
            return "platform_mismatch"
        return "ready"

    def require(self, platform: str) -> IAdsActivationProvider:
        status = self.status(platform)
        if status != "ready":
            raise AdsActivationDisabledError(f"Ads activation for {platform} is disabled: {status}")
        provider_id = self._defaults[platform]
        return self._providers[provider_id]


__all__ = ["AdsActivationProviderRegistry"]
