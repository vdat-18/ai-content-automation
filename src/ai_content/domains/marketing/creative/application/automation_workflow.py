"""State transitions for Marketing Creative review and Ads handoff."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from ai_content.domains.marketing.creative.application.ads_activation import (
    AdsActivationService,
)
from ai_content.domains.marketing.creative.application.ads_drafts import (
    approve_ads_draft,
)
from ai_content.domains.marketing.creative.ports.ads_activation import (
    AdsActivationApproval,
    AdsActivationReceipt,
    AdsDraft,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    ExactCreativeReviewDecision,
    ManualGenerationRequest,
    ManualTakeoverRecord,
    MarketingCreativeAutomationState,
    MarketingCreativeAutomationStatus,
    ProducedCreativeAssetRecord,
)
from ai_content.domains.marketing.creative.ports.final_review import (
    FinalCreativeReview,
)


def initialize_automation_state(
    *,
    request_id: str,
    package_id: str,
    package_ref: str,
    route: Literal["manual", "assisted", "automated"],
    status: str,
    now: datetime | None = None,
) -> MarketingCreativeAutomationState:
    timestamp = now or datetime.now(UTC)
    return MarketingCreativeAutomationState(
        request_id=request_id,
        package_id=package_id,
        package_ref=package_ref,
        route=route,
        status=MarketingCreativeAutomationStatus(status),
        final_review=None,
        review_decision=None,
        ads_draft=None,
        ads_approval=None,
        ads_receipt=None,
        created_at=timestamp,
        updated_at=timestamp,
        production_assets=(),
        production_error_code=None,
        production_error_detail=None,
    )


def record_production_outcome(
    state: MarketingCreativeAutomationState,
    assets: tuple[ProducedCreativeAssetRecord, ...],
    *,
    error_code: str | None = None,
    error_detail: str | None = None,
    now: datetime | None = None,
) -> MarketingCreativeAutomationState:
    if state.status not in {
        MarketingCreativeAutomationStatus.AWAITING_GENERATION_PROVIDER,
        MarketingCreativeAutomationStatus.PRODUCING,
    }:
        raise ValueError("Creative automation is not accepting production results")
    failed = error_code is not None or any(not asset.success for asset in assets)
    return replace(
        state,
        status=(
            MarketingCreativeAutomationStatus.PRODUCTION_NEEDS_ATTENTION
            if failed
            else MarketingCreativeAutomationStatus.PRODUCING
        ),
        production_assets=(*state.production_assets, *assets),
        production_error_code=error_code,
        production_error_detail=error_detail,
        revision=state.revision + 1,
        updated_at=now or datetime.now(UTC),
    )


def record_final_review(
    state: MarketingCreativeAutomationState,
    review: FinalCreativeReview,
    *,
    now: datetime | None = None,
) -> MarketingCreativeAutomationState:
    if review.request_id != state.request_id or review.package_id != state.package_id:
        raise ValueError("Final review belongs to a different automation request")
    if state.status not in {
        MarketingCreativeAutomationStatus.AWAITING_GENERATION_PROVIDER,
        MarketingCreativeAutomationStatus.PRODUCING,
    }:
        raise ValueError("Creative automation is not accepting a final review")
    return replace(
        state,
        status=MarketingCreativeAutomationStatus.READY_FOR_REVIEW,
        final_review=review,
        review_decision=None,
        ads_draft=None,
        ads_approval=None,
        ads_receipt=None,
        production_error_code=None,
        production_error_detail=None,
        revision=state.revision + 1,
        updated_at=now or datetime.now(UTC),
    )


def decide_final_review(
    state: MarketingCreativeAutomationState,
    *,
    decision_id: str,
    review_id: str,
    asset_version_ids: tuple[str, ...],
    asset_checksums: tuple[str, ...],
    decision: Literal["approve", "manual_takeover"],
    reviewer_alias: str,
    reason: str,
    key_visual_asset_version_id: str | None = None,
    decided_at: datetime | None = None,
) -> MarketingCreativeAutomationState:
    review = state.final_review
    if state.status != MarketingCreativeAutomationStatus.READY_FOR_REVIEW or review is None:
        raise ValueError("Creative automation is not ready for review")
    if review.review_id != review_id:
        raise ValueError("Creative review changed before the decision was submitted")
    if len(asset_version_ids) != len(set(asset_version_ids)):
        raise ValueError("Creative review assets must be unique")
    current_assets = {asset.asset_version_id: asset for asset in review.assets}
    if any(
        current_assets.get(asset_id) is None
        or current_assets[asset_id].checksum_sha256 != checksum
        for asset_id, checksum in zip(asset_version_ids, asset_checksums, strict=True)
    ):
        raise ValueError("Creative assets changed before the decision was submitted")
    if key_visual_asset_version_id is not None:
        key_visual = current_assets.get(key_visual_asset_version_id)
        if key_visual is None or key_visual.media_kind != "image":
            raise ValueError("Key Visual must be an approved image")
    timestamp = decided_at or datetime.now(UTC)
    exact_decision = ExactCreativeReviewDecision(
        decision_id=decision_id,
        review_id=review_id,
        decision=decision,
        asset_version_ids=asset_version_ids,
        asset_checksums=asset_checksums,
        reviewer_alias=reviewer_alias,
        reason=reason,
        decided_at=timestamp,
        key_visual_asset_version_id=key_visual_asset_version_id,
    )
    next_status = {
        "approve": MarketingCreativeAutomationStatus.CREATIVE_APPROVED,
        "manual_takeover": MarketingCreativeAutomationStatus.MANUAL_TAKEOVER,
    }[decision]
    return replace(
        state,
        status=next_status,
        review_decision=exact_decision,
        revision=state.revision + 1,
        updated_at=timestamp,
    )


def request_generation_again(
    state: MarketingCreativeAutomationState,
    *,
    generation_request_id: str,
    requested_by: str,
    reason: str,
    target_asset_version_ids: tuple[str, ...] = (),
    knowledge_refs: tuple[str, ...] = (),
    revision_guidance: tuple[str, ...] = (),
    requested_at: datetime | None = None,
) -> MarketingCreativeAutomationState:
    if state.status not in {
        MarketingCreativeAutomationStatus.READY_FOR_REVIEW,
        MarketingCreativeAutomationStatus.PRODUCTION_NEEDS_ATTENTION,
    }:
        raise ValueError("Creative automation is not ready to generate again")
    if any(
        item.generation_request_id == generation_request_id for item in state.generation_requests
    ):
        return state
    eligible_asset_ids = (
        {asset.asset_version_id for asset in state.final_review.assets}
        if state.final_review is not None
        else {asset.asset_version_id for asset in state.production_assets}
    )
    unknown_targets = set(target_asset_version_ids) - eligible_asset_ids
    if unknown_targets:
        raise ValueError("Generate again targets must belong to the current Creative run")
    timestamp = requested_at or datetime.now(UTC)
    request = ManualGenerationRequest(
        generation_request_id=generation_request_id,
        requested_by=requested_by,
        reason=reason,
        requested_at=timestamp,
        target_asset_version_ids=target_asset_version_ids,
        knowledge_refs=knowledge_refs,
        revision_guidance=revision_guidance,
    )
    return replace(
        state,
        status=MarketingCreativeAutomationStatus.AWAITING_GENERATION_PROVIDER,
        final_review=None,
        review_decision=None,
        production_error_code=None,
        production_error_detail=None,
        generation_requests=(*state.generation_requests, request),
        revision=state.revision + 1,
        updated_at=timestamp,
    )


def request_manual_takeover(
    state: MarketingCreativeAutomationState,
    *,
    takeover_id: str,
    requested_by: str,
    reason: str,
    requested_at: datetime | None = None,
) -> MarketingCreativeAutomationState:
    if state.manual_takeover is not None:
        if state.manual_takeover.takeover_id == takeover_id:
            return state
        raise ValueError("Creative automation was already taken over manually")
    if state.status not in {
        MarketingCreativeAutomationStatus.NEEDS_INPUT,
        MarketingCreativeAutomationStatus.AWAITING_GENERATION_PROVIDER,
        MarketingCreativeAutomationStatus.PRODUCTION_NEEDS_ATTENTION,
    }:
        raise ValueError("Creative automation is not available for manual takeover")
    timestamp = requested_at or datetime.now(UTC)
    takeover = ManualTakeoverRecord(
        takeover_id=takeover_id,
        requested_by=requested_by,
        reason=reason,
        requested_at=timestamp,
    )
    return replace(
        state,
        status=MarketingCreativeAutomationStatus.MANUAL_TAKEOVER,
        manual_takeover=takeover,
        revision=state.revision + 1,
        updated_at=timestamp,
    )


def attach_ads_draft(
    state: MarketingCreativeAutomationState,
    draft: AdsDraft,
    *,
    now: datetime | None = None,
) -> MarketingCreativeAutomationState:
    decision = state.review_decision
    review = state.final_review
    if (
        state.status != MarketingCreativeAutomationStatus.CREATIVE_APPROVED
        or decision is None
        or decision.decision != "approve"
        or review is None
    ):
        raise ValueError("Ads Draft requires an approved final Creative review")
    if draft.request_id != state.request_id:
        raise ValueError("Ads Draft belongs to a different automation request")
    exact_ids = tuple(asset.asset_version_id for asset in draft.assets)
    exact_checksums = tuple(asset.checksum_sha256 for asset in draft.assets)
    if exact_ids != decision.asset_version_ids or exact_checksums != decision.asset_checksums:
        raise ValueError("Ads Draft must use the exact approved Creative assets")
    return replace(
        state,
        status=MarketingCreativeAutomationStatus.ADS_DRAFT_READY,
        ads_draft=draft,
        ads_approval=None,
        ads_receipt=None,
        revision=state.revision + 1,
        updated_at=now or datetime.now(UTC),
    )


def approve_automation_ads_draft(
    state: MarketingCreativeAutomationState,
    *,
    approval_id: str,
    reviewer_alias: str,
    reason: str,
    approved_at: datetime | None = None,
) -> tuple[MarketingCreativeAutomationState, AdsActivationApproval]:
    if state.status != MarketingCreativeAutomationStatus.ADS_DRAFT_READY:
        raise ValueError("Creative automation Ads Draft is not ready for approval")
    if state.ads_draft is None:
        raise ValueError("Creative automation Ads Draft is missing")
    approved_draft, approval = approve_ads_draft(
        state.ads_draft,
        approval_id=approval_id,
        reviewer_alias=reviewer_alias,
        reason=reason,
        approved_at=approved_at,
    )
    return (
        replace(
            state,
            status=MarketingCreativeAutomationStatus.ADS_APPROVED,
            ads_draft=approved_draft,
            ads_approval=approval,
            ads_receipt=None,
            revision=state.revision + 1,
            updated_at=approval.approved_at,
        ),
        approval,
    )


async def activate_automation_ads(
    state: MarketingCreativeAutomationState,
    service: AdsActivationService,
) -> tuple[MarketingCreativeAutomationState, AdsActivationReceipt]:
    if state.status != MarketingCreativeAutomationStatus.ADS_APPROVED:
        raise ValueError("Creative automation Ads Draft is not approved for activation")
    if state.ads_draft is None or state.ads_approval is None:
        raise ValueError("Creative automation Ads approval is incomplete")
    activated_draft, receipt = await service.activate(state.ads_draft, state.ads_approval)
    return (
        replace(
            state,
            status=MarketingCreativeAutomationStatus.ACTIVATED,
            ads_draft=activated_draft,
            ads_receipt=receipt,
            revision=state.revision + 1,
            updated_at=receipt.activated_at,
        ),
        receipt,
    )


__all__ = [
    "activate_automation_ads",
    "approve_automation_ads_draft",
    "attach_ads_draft",
    "decide_final_review",
    "initialize_automation_state",
    "record_final_review",
    "record_production_outcome",
    "request_generation_again",
    "request_manual_takeover",
]
