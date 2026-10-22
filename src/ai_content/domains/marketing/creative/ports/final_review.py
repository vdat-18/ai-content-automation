"""Marketing-facing final review projection for exact generated asset versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class ReviewableCreativeAsset:
    asset_version_id: str
    media_kind: Literal["image", "video"]
    artifact_ref: str
    checksum_sha256: str
    content_type: str
    qa_summary: str
    revision_count: int
    provider_id: str
    cost: Decimal
    fidelity_mode: Literal["generative", "exact_source_transform"] = "generative"
    product_source_checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.asset_version_id,
                self.artifact_ref,
                self.content_type,
                self.qa_summary,
                self.provider_id,
            )
        ):
            raise ValueError("Reviewable Creative asset identity and QA summary are required")
        if len(self.checksum_sha256) != 64:
            raise ValueError("Reviewable Creative asset checksum must be SHA-256")
        if (
            self.product_source_checksum_sha256 is not None
            and len(self.product_source_checksum_sha256) != 64
        ):
            raise ValueError("Reviewable Creative product source checksum must be SHA-256")
        if self.revision_count < 0 or self.cost < 0:
            raise ValueError("Reviewable Creative revision count and cost cannot be negative")


@dataclass(frozen=True)
class FinalCreativeReview:
    review_id: str
    request_id: str
    package_id: str
    brand_id: str
    sku_id: str
    objective: str
    platform: str
    direction_summary: str
    assets: tuple[ReviewableCreativeAsset, ...]
    image_count: int
    video_count: int
    status: Literal["ready_for_review"]
    created_at: datetime
    review_checklist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.review_id,
            self.request_id,
            self.package_id,
            self.brand_id,
            self.sku_id,
            self.objective,
            self.platform,
            self.direction_summary,
        )
        if not all(value.strip() for value in required):
            raise ValueError("Final Creative review identity and direction are required")
        actual_images = sum(asset.media_kind == "image" for asset in self.assets)
        actual_videos = sum(asset.media_kind == "video" for asset in self.assets)
        if (actual_images, actual_videos) != (self.image_count, self.video_count):
            raise ValueError("Final Creative review must contain the full requested output set")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Final Creative review timestamp must include timezone information")


__all__ = ["FinalCreativeReview", "ReviewableCreativeAsset"]
