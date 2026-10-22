"""Demo Meta Ads activation provider: confirms an approved draft without calling Meta."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from ai_content.domains.marketing.creative.ports.ads_activation import (
    AdsActivationApproval,
    AdsActivationProviderDescriptor,
    AdsActivationReceipt,
    AdsDraft,
)

MOCK_META_PROVIDER_ID = "mock-meta-ads"


class MockMetaAdsActivationProvider:
    """Returns a deterministic receipt shaped like a Meta campaign with one ad per asset."""

    descriptor = AdsActivationProviderDescriptor(
        provider_id=MOCK_META_PROVIDER_ID,
        platform="meta",
        approved=True,
        least_privilege=True,
        configuration_version="mock-1",
    )

    async def activate(
        self, draft: AdsDraft, approval: AdsActivationApproval
    ) -> AdsActivationReceipt:
        digest = hashlib.sha256(f"{draft.draft_id}:{approval.approval_id}".encode()).hexdigest()
        return AdsActivationReceipt(
            draft_id=draft.draft_id,
            platform=draft.platform,
            account_id=f"act_{draft.brand_id.lower()}",
            campaign_id=f"mock-cmp-{digest[:12]}",
            ad_ids=tuple(
                f"mock-ad-{digest[:8]}-{index}" for index, _ in enumerate(draft.assets, 1)
            ),
            activated_at=datetime.now(UTC),
        )
