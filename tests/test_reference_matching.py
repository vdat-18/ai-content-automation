import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_content.domains.marketing.data_sources.adapters import MockDataConnector
from ai_content.domains.marketing.data_sources.config import load_data_sources_config
from ai_content.domains.marketing.research_crawler.brand_context import _research_product
from ai_content.domains.marketing.research_crawler.models import (
    ResearchBrandContext,
    ResearchMediaAsset,
    ResearchProduct,
    ResearchProductMatch,
    ResearchRecordQuery,
    ResearchReferenceProfile,
    ResearchScreening,
    StoredResearchRecord,
)
from ai_content.domains.marketing.research_crawler.repositories import (
    SqliteResearchCrawlRepository,
)
from ai_content.domains.marketing.research_crawler.screening import _apply_scene_rules
from ai_content.domains.marketing.research_crawler.shortlist import shortlist_references

_DEMO = Path(__file__).parents[1] / "config/data_sources/demo.json"
_NOW = datetime(2026, 10, 1, tzinfo=UTC)
_MASK = "9003"
_PILLOW = "9000"


def _record(
    key: str,
    *,
    matches: tuple[tuple[str, str], ...],
    background_usable: bool = True,
    advertiser: str | None = None,
) -> StoredResearchRecord:
    profile = ResearchReferenceProfile(
        summary=f"{key} bedroom scene",
        relevance_to_project="sleep",
        background_usable=background_usable,
        product_matches=tuple(
            ResearchProductMatch(product_id=product_id, match_kind=kind, confidence=0.9)
            for product_id, kind in matches
        ),
    )
    return StoredResearchRecord(
        record_key=key,
        workspace_id="w",
        brand_id="AuraSleep",
        platform="meta",
        external_id=key,
        record_type="ad",
        advertiser=advertiser or key,
        media_assets=[
            ResearchMediaAsset(
                media_id="m1",
                media_kind="image",
                source_url_fingerprint="f",
                source_url="https://example.com/a.png",
                status="available",
                artifact_ref=f"a/{key}.png",
                sha256=f"sha-{key}",
            )
        ],
        screening_status="kept",
        screening=ResearchScreening(
            status="completed",
            prompt_version="v1",
            model="gemini",
            content_hash="h",
            usable=True,
            reason_code="ok",
            reason="ok",
            confidence=0.9,
            profile=profile,
        ),
        review_status="approved",
        content_hash=key,
        first_seen_at=_NOW - timedelta(days=3),
        last_seen_at=_NOW - timedelta(days=3),
        latest_run_id="r",
    )


def test_mock_products_carry_reference_facts() -> None:
    definitions = {item.source_id: item for item in load_data_sources_config(_DEMO)}
    records = asyncio.run(MockDataConnector().fetch(definitions["mock-aurasleep-products"]))[0]
    products = {item.title: item for item in map(_research_product, records) if item}
    mask = products["Hush Silk Sleep Mask"]
    assert mask.category.endswith("Sleep Masks")
    assert "airplane seat" in mask.usage_scenes and "swim goggles" in mask.not_to_confuse_with
    assert len(products) == 4


def test_scene_rules_drop_unknown_products_and_backgroundless_images() -> None:
    context = ResearchBrandContext(
        brand_id="AuraSleep",
        version="v",
        source_versions=(),
        product_facts=(),
        products=(ResearchProduct(product_id=_MASK, title="Hush Silk Sleep Mask"),),
    )
    output = {"usable": True}
    profile = {
        "background_usable": False,
        "background_reason": "plain white backdrop",
        "swap_mode": "style_only",
        "product_matches": [
            {"product_id": _MASK, "match_kind": "scene_fit", "confidence": 0.8},
            {"product_id": "table", "match_kind": "scene_fit", "confidence": 0.8},
        ],
    }
    _apply_scene_rules(output, profile, context)
    assert [item["product_id"] for item in profile["product_matches"]] == [_MASK]
    assert output["usable"] is False and output["reason_code"] == "no_usable_background"


def test_shortlist_only_returns_references_matched_to_the_product() -> None:
    records = [
        _record("mask", matches=((_MASK, "scene_fit"),)),
        _record("pillow", matches=((_PILLOW, "scene_fit"),)),
        _record("studio", matches=((_MASK, "scene_fit"),), background_usable=False),
    ]
    picks = shortlist_references(records, product_text="mask", product_id=_MASK, now=_NOW)
    assert [item.record_key for item in picks] == ["mask"]


def test_shortlist_prefers_references_not_used_before() -> None:
    records = [
        _record("old", matches=((_MASK, "scene_fit"),)),
        _record("fresh", matches=((_MASK, "scene_fit"),)),
    ]
    picks = shortlist_references(
        records, product_text="mask", product_id=_MASK, use_counts={"old": 2}, limit=2, now=_NOW
    )
    assert [item.record_key for item in picks] == ["fresh", "old"]


def test_repository_links_products_and_counts_uses(tmp_path: Path) -> None:
    repository = SqliteResearchCrawlRepository(tmp_path / "state.db")
    record = _record("mask", matches=((_MASK, "scene_fit"),))

    async def run() -> tuple[int, int, dict[str, int]]:
        with repository._connection:
            repository._connection.execute(
                "INSERT INTO research_records (record_key, workspace_id, brand_id, platform, "
                "external_id, record_type, text, screening_status, review_status, has_images, "
                "has_videos, content_hash, latest_run_id, version_count, first_seen_at, "
                "last_seen_at, payload) VALUES (?, 'w', 'AuraSleep', 'meta', 'mask', 'ad', '', "
                "'kept', 'approved', 1, 0, 'h', 'r', 1, 't', 't', '')",
                ("mask",),
            )
            repository._connection.execute(
                "UPDATE research_records SET payload = ? WHERE record_key = 'mask'",
                (record.model_dump_json(),),
            )
        assert record.screening is not None
        await repository.save_record_enrichment("mask", screening=record.screening)
        match = await repository.search_records(
            ResearchRecordQuery(brand_id="AuraSleep", product_id=_MASK)
        )
        other = await repository.search_records(
            ResearchRecordQuery(brand_id="AuraSleep", product_id=_PILLOW)
        )
        await repository.record_reference_uses(("research:mask:m1",), "batch-1")
        await repository.record_reference_uses(("research:mask:m1",), "batch-1")
        await repository.record_reference_uses(("research:mask:m1",), "batch-2")
        return match.total, other.total, await repository.reference_use_counts(("mask",))

    assert asyncio.run(run()) == (1, 0, {"mask": 2})
