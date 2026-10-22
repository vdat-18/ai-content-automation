"""Exact-version contracts for Ads drafts and activation approval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class AdsDraftStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    ACTIVATED = "activated"


@dataclass(frozen=True)
class ExactCreativeAsset:
    asset_version_id: str
    artifact_ref: str
    checksum_sha256: str
    media_kind: str

    def __post_init__(self) -> None:
        if not self.asset_version_id.strip() or not self.artifact_ref.strip():
            raise ValueError("Exact Creative asset identity is required")
        if len(self.checksum_sha256) != 64:
            raise ValueError("Exact Creative asset checksum must be SHA-256")
        if self.media_kind not in {"image", "video"}:
            raise ValueError("Exact Creative asset kind must be image or video")


@dataclass(frozen=True)
class AdsDraft:
    draft_id: str
    request_id: str
    brand_id: str
    sku_id: str
    platform: str
    objective: str
    destination_ref: str
    daily_budget: Decimal
    currency: str
    assets: tuple[ExactCreativeAsset, ...]
    draft_fingerprint: str
    status: AdsDraftStatus
    created_at: datetime

    def __post_init__(self) -> None:
        required = (
            self.draft_id,
            self.request_id,
            self.brand_id,
            self.sku_id,
            self.platform,
            self.objective,
            self.destination_ref,
        )
        if not all(value.strip() for value in required):
            raise ValueError("Ads Draft identity and destination are required")
        if self.daily_budget <= 0 or len(self.currency) != 3:
            raise ValueError("Ads Draft requires a positive budget and ISO currency")
        if not self.assets:
            raise ValueError("Ads Draft requires at least one exact Creative asset")
        if len({item.asset_version_id for item in self.assets}) != len(self.assets):
            raise ValueError("Ads Draft assets must be unique")
        if len(self.draft_fingerprint) != 64:
            raise ValueError("Ads Draft fingerprint must be SHA-256")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Ads Draft timestamp must include timezone information")


@dataclass(frozen=True)
class AdsActivationApproval:
    approval_id: str
    draft_id: str
    draft_fingerprint: str
    asset_version_ids: tuple[str, ...]
    asset_checksums: tuple[str, ...]
    reviewer_alias: str
    reason: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.approval_id,
                self.draft_id,
                self.reviewer_alias,
                self.reason,
            )
        ):
            raise ValueError("Ads activation approval identity and reason are required")
        if len(self.draft_fingerprint) != 64:
            raise ValueError("Ads activation approval must pin the draft fingerprint")
        if not self.asset_version_ids or len(self.asset_version_ids) != len(self.asset_checksums):
            raise ValueError("Ads activation approval must pin every exact asset")
        if any(len(value) != 64 for value in self.asset_checksums):
            raise ValueError("Ads activation approval asset checksums must be SHA-256")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("Ads activation approval timestamp must include timezone information")


@dataclass(frozen=True)
class AdsActivationReceipt:
    draft_id: str
    platform: str
    account_id: str
    campaign_id: str
    ad_ids: tuple[str, ...]
    activated_at: datetime


@dataclass(frozen=True)
class AdsActivationProviderDescriptor:
    provider_id: str
    platform: str
    approved: bool
    least_privilege: bool
    configuration_version: str

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.provider_id, self.platform, self.configuration_version)
        ):
            raise ValueError("Ads activation provider identity is required")


class IAdsActivationProvider(Protocol):
    descriptor: AdsActivationProviderDescriptor

    async def activate(
        self,
        draft: AdsDraft,
        approval: AdsActivationApproval,
    ) -> AdsActivationReceipt: ...


class AdsActivationDisabledError(Exception):
    """Paid Ads mutation is unavailable until an approved adapter is configured."""


__all__ = [
    "AdsActivationApproval",
    "AdsActivationDisabledError",
    "AdsActivationReceipt",
    "AdsActivationProviderDescriptor",
    "AdsDraft",
    "AdsDraftStatus",
    "ExactCreativeAsset",
    "IAdsActivationProvider",
]
