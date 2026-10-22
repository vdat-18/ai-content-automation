from datetime import UTC, datetime, timedelta

from ai_content.domains.marketing.research_crawler.models import (
    ResearchMediaAsset,
    ResearchReferenceProfile,
    ResearchScreening,
    StoredResearchRecord,
)
from ai_content.domains.marketing.research_crawler.shortlist import shortlist_references

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _record(
    key: str,
    *,
    advertiser: str,
    subject: str,
    style: str,
    digest: str,
    days_ago: int = 5,
) -> StoredResearchRecord:
    profile = ResearchReferenceProfile(
        summary=f"{subject} ad",
        relevance_to_project="skincare serum",
        primary_subject=subject,
        product_categories=("skincare",),
        visual_style=(style,),
    )
    screening = ResearchScreening(
        status="completed",
        prompt_version="v1",
        model="grok",
        content_hash="h",
        usable=True,
        reason_code="ok",
        reason="ok",
        confidence=0.9,
        profile=profile,
    )
    return StoredResearchRecord(
        record_key=key,
        workspace_id="w",
        brand_id="LumiSkin",
        platform="meta",
        external_id=key,
        record_type="ad",
        advertiser=advertiser,
        media_assets=[
            ResearchMediaAsset(
                media_id="m1",
                media_kind="image",
                source_url_fingerprint="f",
                source_url="https://example.com/a.png",
                status="available",
                artifact_ref=f"a/{key}.png",
                sha256=digest,
            )
        ],
        screening_status="kept",
        screening=screening,
        review_status="approved",
        content_hash=key,
        first_seen_at=_NOW - timedelta(days=days_ago),
        last_seen_at=_NOW - timedelta(days=days_ago),
        latest_run_id="r",
    )


def test_shortlist_prefers_relevant_and_varied_references() -> None:
    records = [
        _record("a", advertiser="X", subject="hydrating serum bottle", style="macro", digest="1"),
        _record("b", advertiser="Y", subject="hydrating serum bottle", style="macro", digest="2"),
        _record("c", advertiser="Z", subject="serum on skin", style="lifestyle", digest="3"),
        _record("d", advertiser="W", subject="office chair", style="studio", digest="4"),
    ]
    picks = shortlist_references(records, product_text="Hydrating Serum", limit=2, now=_NOW)
    assert [item.record_key for item in picks] == ["a", "c"]


def test_shortlist_drops_exact_duplicates_and_same_advertiser() -> None:
    records = [
        _record("a", advertiser="X", subject="serum", style="macro", digest="1"),
        _record("b", advertiser="X", subject="serum", style="lifestyle", digest="2"),
        _record("c", advertiser="Y", subject="serum", style="macro", digest="1"),
    ]
    picks = shortlist_references(records, product_text="serum", limit=5, now=_NOW)
    assert [item.record_key for item in picks] == ["a"]
