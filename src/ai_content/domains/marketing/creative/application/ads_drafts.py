"""Build and approve Ads drafts while pinning exact Creative asset versions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from ai_content.domains.marketing.creative.ports.ads_activation import (
    AdsActivationApproval,
    AdsDraft,
    AdsDraftStatus,
    ExactCreativeAsset,
)


def build_ads_draft(
    *,
    draft_id: str,
    request_id: str,
    brand_id: str,
    sku_id: str,
    platform: str,
    objective: str,
    destination_ref: str,
    daily_budget: Decimal,
    currency: str,
    assets: tuple[ExactCreativeAsset, ...],
    created_at: datetime | None = None,
) -> AdsDraft:
    timestamp = created_at or datetime.now(UTC)
    fingerprint = _fingerprint(
        draft_id,
        request_id,
        brand_id,
        sku_id,
        platform,
        objective,
        destination_ref,
        str(daily_budget),
        currency,
        tuple(
            (asset.asset_version_id, asset.checksum_sha256, asset.artifact_ref) for asset in assets
        ),
    )
    return AdsDraft(
        draft_id=draft_id,
        request_id=request_id,
        brand_id=brand_id,
        sku_id=sku_id,
        platform=platform,
        objective=objective,
        destination_ref=destination_ref,
        daily_budget=daily_budget,
        currency=currency,
        assets=assets,
        draft_fingerprint=fingerprint,
        status=AdsDraftStatus.AWAITING_APPROVAL,
        created_at=timestamp,
    )


def approve_ads_draft(
    draft: AdsDraft,
    *,
    approval_id: str,
    reviewer_alias: str,
    reason: str,
    approved_at: datetime | None = None,
) -> tuple[AdsDraft, AdsActivationApproval]:
    if draft.status != AdsDraftStatus.AWAITING_APPROVAL:
        raise ValueError("Only an awaiting Ads Draft can be approved")
    approval = AdsActivationApproval(
        approval_id=approval_id,
        draft_id=draft.draft_id,
        draft_fingerprint=draft.draft_fingerprint,
        asset_version_ids=tuple(asset.asset_version_id for asset in draft.assets),
        asset_checksums=tuple(asset.checksum_sha256 for asset in draft.assets),
        reviewer_alias=reviewer_alias,
        reason=reason,
        approved_at=approved_at or datetime.now(UTC),
    )
    return replace(draft, status=AdsDraftStatus.APPROVED), approval


def validate_activation_approval(
    draft: AdsDraft,
    approval: AdsActivationApproval,
) -> None:
    if draft.status != AdsDraftStatus.APPROVED:
        raise ValueError("Ads Draft must be approved before activation")
    if approval.draft_id != draft.draft_id:
        raise ValueError("Ads approval belongs to a different draft")
    if approval.draft_fingerprint != draft.draft_fingerprint:
        raise ValueError("Ads Draft changed after approval")
    if approval.asset_version_ids != tuple(asset.asset_version_id for asset in draft.assets):
        raise ValueError("Ads asset versions changed after approval")
    if approval.asset_checksums != tuple(asset.checksum_sha256 for asset in draft.assets):
        raise ValueError("Ads asset bytes changed after approval")


def _fingerprint(*values: object) -> str:
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["approve_ads_draft", "build_ads_draft", "validate_activation_approval"]
