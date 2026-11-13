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
                "product_briefs",
                "product_keyframes",
                "product_clips",
                "product_events",
                "product_pipeline_runs",
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
        assert await service.set_image_status(image["image_id"], "removed")
        assert not await service.set_image_status("missing", "removed")

        class _Reviewer:
            async def review_all(self, images, http=None):
                return {i["image_id"]: {"usable": True} for i in images}

        screener = ProductCatalogService(PostgresProductRepository(engine), reviewer=_Reviewer())  # type: ignore[arg-type]
        await screener.ingest(
            {
                **body,
                "query": "q2",
                "pins": [{**pins[0], "image_url": "https://i.pinimg.com/236x/aa/bb/cc.jpg"}],
            }
        )
        [passed] = await screener.reference_images("live", None)
        assert passed["screening"] == {"usable": True}

        class _Writer:
            async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
                return {"title": "T", "scene": "s", "idea": user_idea}

        briefer = ProductCatalogService(PostgresProductRepository(engine), briefer=_Writer())  # type: ignore[arg-type]
        await briefer.update_profile(ReferenceProfile("áo thun", ["q1"], "approved"))
        record = await briefer.create_brief("1730000000000000001", "ý tưởng", person_photos=[b"face"])
        assert record is not None and record["brief"]["idea"] == "ý tưởng"
        updated = await briefer.update_brief("1730000000000000001", {"scene": "mới"}, "approved")
        assert updated is not None and updated["brief"]["scene"] == "mới"
        assert [b["status"] for b in await briefer.list_briefs()] == ["approved"]
        assert await briefer.get_brief("missing") is None

        keyframe = {
            "product_id": "1730000000000000001",
            "shot_index": 0,
            "status": "ready",
            "prompt": "p",
            "image_path": "keyframes/x/shot_0.jpg",
            "attempts": 1,
            "error": None,
            "qa_problem": "",
        }
        await briefer._repository.save_keyframe(keyframe)
        await briefer._repository.save_keyframe({**keyframe, "attempts": 2})
        assert await briefer.set_keyframe_status("1730000000000000001", 0, "approved")
        assert not await briefer.set_keyframe_status("1730000000000000001", 9, "approved")
        [stored_keyframe] = await briefer.list_keyframes("1730000000000000001")
        assert (stored_keyframe["status"], stored_keyframe["attempts"]) == ("approved", 2)

        clip = {
            "product_id": "1730000000000000001",
            "shot_index": 0,
            "status": "processing",
            "job_id": "job1",
            "job_model": "xai/m",
            "video_path": None,
            "seconds": 6,
            "attempts": 1,
            "error": None,
            "qa_problem": "",
        }
        await briefer._repository.save_clip(clip)
        await briefer._repository.save_clip({**clip, "status": "ready", "video_path": "c.mp4"})
        [stored_clip] = await briefer._repository.list_clips("1730000000000000001")
        assert (stored_clip["status"], stored_clip["video_path"]) == ("ready", "c.mp4")
        await briefer._repository.add_event("1730000000000000001", "clip", 0, "ok", "first")
        await briefer._repository.add_event("1730000000000000001", "video", None, "ok", "second")
        events = await briefer._repository.list_events("1730000000000000001")
        assert [(e["step"], e["shot_index"], e["message"]) for e in events[-2:]] == [
            ("clip", 0, "first"),
            ("video", None, "second"),
        ]
        assert events[0]["at"]

        runs = briefer._repository
        assert await runs.get_run("1730000000000000001") is None
        await runs.save_run("1730000000000000001", "running", "")
        assert await runs.interrupt_runs() == 1
        interrupted = await runs.get_run("1730000000000000001")
        assert interrupted is not None and interrupted["status"] == "interrupted"
        await runs.save_run("1730000000000000001", "paused", "Review the images")
        assert (await runs.get_run("1730000000000000001"))["message"] == "Review the images"
        await runs.clear_work("1730000000000000001")  # the script, images, clips and run go
        assert await runs.get_brief("1730000000000000001") is None
        assert await runs.list_clips("1730000000000000001") == []
        assert await runs.get_run("1730000000000000001") is None
        await runs.save_brief("1730000000000000001", "", {"title": "b"}, "draft")

        repository_for_delete = briefer._repository
        assert await repository_for_delete.delete_product("1730000000000000001") is True
        assert await repository_for_delete.delete_product("1730000000000000001") is False
        assert await repository_for_delete.list_events("1730000000000000001") == []
        assert await repository_for_delete.list_clips("1730000000000000001") == []
        assert all(
            item["product_id"] != "1730000000000000001"
            for item in await repository_for_delete.list_details()
        )

        repository = PostgresProductRepository(engine)
        await repository.add_reference_images(
            "áo thun",
            "q",
            [
                {
                    "image_id": "fp-1",
                    "image_url": "https://i.pinimg.com/736x/fp/fp/1.jpg",
                    "pin_url": "/p/",
                    "title": "t",
                    "phash": "00000000000000ff",
                    "embedding": [1.0, 0.0],
                },
                {
                    "image_id": "fp-2",
                    "image_url": "https://i.pinimg.com/736x/fp/fp/2.jpg",
                    "pin_url": "/p/",
                    "title": "t",
                    "status": "duplicate",
                    "duplicate_of": "fp-1",
                },
            ],
        )
        assert await repository.existing_image_ids(["fp-1", "fp-2", "nope"]) == {"fp-1", "fp-2"}
        [stored] = [f for f in await repository.fingerprints("áo thun") if f["image_id"] == "fp-1"]
        assert stored["phash"] == "00000000000000ff" and stored["embedding"] == [1.0, 0.0]
        missing = {i["image_id"] for i in await repository.images_without_fingerprint(100)}
        assert "fp-1" not in missing and "fp-2" not in missing
        await repository.set_fingerprint("fp-2", "0000000000000001", [0.0, 1.0])
        assert len(await repository.fingerprints("áo thun")) >= 2
    finally:
        await engine.dispose()


def test_postgres_repository_round_trip() -> None:
    # psycopg's async mode cannot run on the Windows default Proactor event loop.
    asyncio.run(_round_trip(), loop_factory=asyncio.SelectorEventLoop)
