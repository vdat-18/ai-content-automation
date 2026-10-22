import asyncio
from pathlib import Path

from ai_content.domains.marketing.data_sources.adapters import MockDataConnector
from ai_content.domains.marketing.data_sources.config import load_data_sources_config

_DEMO = Path(__file__).parents[1] / "config/data_sources/demo.json"


def _fetch(source_id: str):
    definitions = {item.source_id: item for item in load_data_sources_config(_DEMO)}
    return asyncio.run(MockDataConnector().fetch(definitions[source_id]))[0]


def test_demo_config_covers_three_brands() -> None:
    brands = {item.metadata["brand"] for item in load_data_sources_config(_DEMO)}
    assert brands == {"AuraSleep", "OaklineHome", "LumiSkin"}


def test_mock_products_are_deterministic_and_complete() -> None:
    first = _fetch("mock-oakline-products")
    assert first == _fetch("mock-oakline-products")
    assert len(first) == 8
    for record in first:
        assert record.kind == "product"
        assert record.data["variants"] and record.data["media"]
        assert all(variant["sku"] for variant in record.data["variants"])


def test_mock_ads_tell_the_fatigue_story() -> None:
    ads = _fetch("mock-aurasleep-meta-ads")
    assert ads and all(record.kind == "ad_performance" for record in ads)
    fatigued = [
        r for r in ads if float(r.data["ctr_last_14d"]) < 0.6 * float(r.data["ctr_first_14d"])
    ]
    steady = [
        r for r in ads if float(r.data["ctr_last_14d"]) > 0.8 * float(r.data["ctr_first_14d"])
    ]
    assert fatigued and steady
    assert all(float(r.data["spend"]) > 0 for r in ads)


def test_mock_sources_sync_end_to_end(tmp_path: Path) -> None:
    from ai_content.domains.marketing.data_sources.bootstrap import build_runtime

    runtime = build_runtime(
        load_data_sources_config(_DEMO),
        tmp_path / "state.db",
        tmp_path / "artifacts",
        shopify_token=None,
        lark_token=None,
        lark_app_id=None,
        lark_app_secret=None,
        google_token=None,
        meta_token=None,
        google_ads_token=None,
        google_ads_client_id=None,
        google_ads_client_secret=None,
        google_ads_refresh_token=None,
        google_ads_developer_token=None,
        google_ads_login_customer_id=None,
        pinterest_token=None,
        google_merchant_token=None,
        klaviyo_api_key=None,
        timeout_seconds=5,
    )

    async def run():
        runs = await runtime.sync_all()
        snapshots = await runtime.repository.list_latest_snapshots()
        report = runtime.performance_compiler.compile(snapshots, runtime.definitions)
        await runtime.close()
        return runs, report

    runs, report = asyncio.run(run())
    assert len(runs) == 6 and all(item.status.value == "succeeded" for item in runs)
    assert report.creatives


def test_listed_packshots_use_fetchable_urls() -> None:
    products = {record.data["title"]: record for record in _fetch("mock-oakline-products")}
    desk_media = products["Haven Standing Desk"].data["media"]
    assert desk_media and all(
        item["url"].startswith("https://") and item["url"].endswith("/haven-standing-desk.png")
        for item in desk_media
    )
    lamp_media = products["Arc Floor Lamp"].data["media"]
    assert all(item["url"].startswith("mock://") for item in lamp_media)
