"""Run the product repository against a real PostgreSQL migrated to head.

Set AIC_TEST_DATABASE_URL (postgresql+psycopg://...) to a disposable database to enable.
"""

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ai_content.domains.marketing.products.references import ReferenceProfile
from ai_content.domains.marketing.products.repositories import PostgresProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService

DATABASE_URL = os.getenv("AIC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AIC_TEST_DATABASE_URL is not set")

URL = "https://shop.tiktok.com/vn/pdp/ao-thun/1730000000000000001"
HTML = (
    '<script>"product_info":{"status":1,"product_id":"1730000000000000001",'
    '"title":"Áo thun","price":{"min_sku_price":"99000","currency":"VND"},'
    '"images":[{"url_list":["https://img/1.jpg"]}]}</script>'
)
FEED = (
    '{"data":{"productList":[{"product_id":"2","title":"Cốc",'
    '"product_price_info":{"currency_name":"VND","sale_price_decimal":"50.000"},'
    '"sold_info":{"sold_count":30},'
    '"seo_url":{"canonical_url":"https://shop.tiktok.com/vn/pdp/coc/2"}}]}}'
)


async def _round_trip() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as connection:
            for table in (
                "marketplace_products",
                "product_selections",
                "reference_profiles",
                "reference_images",
                "reference_searches",
            ):
                await connection.exec_driver_sql(f"TRUNCATE marketing.{table}")
        service = ProductCatalogService(PostgresProductRepository(engine))

        await service.ingest(
            {"kind": "json", "url": "x/homepage_desktop/products_by_component", "body": FEED}
        )
        assert await service.queue(5) == ["https://shop.tiktok.com/vn/pdp/coc/2"]
        await service.ingest({"kind": "page", "url": URL, "html": HTML})
        await service.ingest({"kind": "page", "url": URL, "html": HTML})
        assert [p["product_id"] for p in await service.details()] == ["1730000000000000001"]
        detail = await service.detail("1730000000000000001")
        assert detail is not None and detail["title"] == "Áo thun"
        assert await service.detail("missing") is None
        assert (await service.export_workbook())[:2] == b"PK"

        class _Generator:
            async def generate(self, product):
                return ReferenceProfile("áo thun", ["ao thun flat lay"])

        service = ProductCatalogService(PostgresProductRepository(engine), _Generator())  # type: ignore[arg-type]
        assert (await service.select("1730000000000000001"))["profile"]["product_type"] == "áo thun"
        await service.update_profile(ReferenceProfile("áo thun", ["new keyword"], "approved"))
        await service.select("1730000000000000001")
        assert (await service.profiles())[0].keywords == ["new keyword"]
        await service.select("1730000000000000001", regenerate=True)
        assert (await service.profiles())[0].keywords == ["ao thun flat lay"]
        assert await service.update_profile(ReferenceProfile("none", [])) is False
        assert await service.selections() == {"1730000000000000001": "áo thun"}

        await service.update_profile(ReferenceProfile("áo thun", ["q1", "q2"], "approved"))
        assert [i["query"] for i in await service.reference_queue(10)] == ["q1", "q2"]
        pins = [
            {
                "image_url": "https://i.pinimg.com/236x/ab/cd/ef.jpg",
                "pin_url": "/pin/1/",
                "title": "a",
            }
        ]
        body = {"kind": "pinterest", "product_type": "áo thun", "query": "q1", "pins": pins}
        assert (await service.ingest(body))["added"] == 1
        assert (await service.ingest(body))["added"] == 0
        assert [i["query"] for i in await service.reference_queue(10)] == ["q2"]
        [image] = await service.reference_images("pending", "áo thun")
        assert image["image_url"].startswith("https://i.pinimg.com/736x/")
        assert await service.set_image_status(image["image_id"], "approved")
        assert not await service.set_image_status("missing", "approved")

        class _Reviewer:
            async def review_all(self, images, http=None):
                return {i["image_id"]: {"usable": True, "reason": "ok"} for i in images}

        screener = ProductCatalogService(PostgresProductRepository(engine), reviewer=_Reviewer())  # type: ignore[arg-type]
        await screener.ingest(
            {
                **body,
                "query": "q2",
                "pins": [{**pins[0], "image_url": "https://i.pinimg.com/236x/aa/bb/cc.jpg"}],
            }
        )
        [passed] = await screener.reference_images("new", None)
        assert passed["screening"] == {"usable": True, "reason": "ok"}
    finally:
        await engine.dispose()


def test_postgres_repository_round_trip() -> None:
    # psycopg's async mode cannot run on the Windows default Proactor event loop.
    asyncio.run(_round_trip(), loop_factory=asyncio.SelectorEventLoop)
