"""Compile successful paid production results into one exact-version review card."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ai_content.domains.marketing.creative.application.paid_media_production import (
    PaidMediaProductionResult,
)
from ai_content.domains.marketing.creative.ports.final_review import (
    FinalCreativeReview,
    ReviewableCreativeAsset,
)

ProducedResult = tuple[
    str,
    Literal["image", "video"],
    PaidMediaProductionResult,
]


def build_final_creative_review(
    *,
    review_id: str,
    request_id: str,
    package_id: str,
    brand_id: str,
    sku_id: str,
    objective: str,
    platform: str,
    direction_summary: str,
    expected_image_count: int,
    expected_video_count: int,
    results: tuple[ProducedResult, ...],
    review_checklist: tuple[str, ...] = (),
    created_at: datetime | None = None,
) -> FinalCreativeReview:
    assets: list[ReviewableCreativeAsset] = []
    for asset_version_id, media_kind, result in results:
        artifact = result.selected_artifact
        if not result.success or artifact is None or not result.attempts:
            raise ValueError("Final review requires every requested asset to pass production QA")
        evaluation = result.attempts[-1].evaluation
        if evaluation.outcome != "pass":
            raise ValueError("Final review requires a passing final QA evaluation")
        assets.append(
            ReviewableCreativeAsset(
                asset_version_id=asset_version_id,
                media_kind=media_kind,
                artifact_ref=artifact.artifact_ref,
                checksum_sha256=artifact.checksum_sha256,
                content_type=artifact.content_type,
                qa_summary=evaluation.summary,
                revision_count=len(result.attempts) - 1,
                provider_id=artifact.provider_id,
                cost=result.total_cost,
                fidelity_mode=artifact.fidelity_mode,
                product_source_checksum_sha256=artifact.product_source_checksum_sha256,
            )
        )
    return FinalCreativeReview(
        review_id=review_id,
        request_id=request_id,
        package_id=package_id,
        brand_id=brand_id,
        sku_id=sku_id,
        objective=objective,
        platform=platform,
        direction_summary=direction_summary,
        assets=tuple(assets),
        image_count=expected_image_count,
        video_count=expected_video_count,
        status="ready_for_review",
        created_at=created_at or datetime.now(UTC),
        review_checklist=review_checklist,
    )


__all__ = ["ProducedResult", "build_final_creative_review"]
