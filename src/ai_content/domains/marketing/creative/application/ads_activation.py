"""Activate an exact approved Ads Draft through one approved provider."""

from __future__ import annotations

from dataclasses import replace

from ai_content.domains.marketing.creative.application.ads_drafts import (
    validate_activation_approval,
)
from ai_content.domains.marketing.creative.application.ads_provider_registry import (
    AdsActivationProviderRegistry,
)
from ai_content.domains.marketing.creative.ports.ads_activation import (
    AdsActivationReceipt,
    AdsDraft,
    AdsDraftStatus,
)


class AdsActivationService:
    def __init__(self, providers: AdsActivationProviderRegistry) -> None:
        self._providers = providers

    async def activate(self, draft, approval) -> tuple[AdsDraft, AdsActivationReceipt]:
        validate_activation_approval(draft, approval)
        provider = self._providers.require(draft.platform)
        receipt = await provider.activate(draft, approval)
        if receipt.draft_id != draft.draft_id or receipt.platform != draft.platform:
            raise ValueError("Ads activation receipt does not match the approved draft")
        if not receipt.account_id.strip() or not receipt.campaign_id.strip() or not receipt.ad_ids:
            raise ValueError("Ads activation receipt is incomplete")
        if receipt.activated_at.tzinfo is None or receipt.activated_at.utcoffset() is None:
            raise ValueError("Ads activation receipt timestamp must include timezone")
        return replace(draft, status=AdsDraftStatus.ACTIVATED), receipt


__all__ = ["AdsActivationService"]
