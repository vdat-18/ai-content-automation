from types import SimpleNamespace

from tests.pgstore import product_repository

from ai_content.domains.marketing.products.references import GENERAL_TYPE
from ai_content.domains.marketing.products.service import ProductCatalogService

URL = "https://shop.tiktok.com/vn/pdp/ao-thun/1730000000000000001"
HTML = (
    '<script>"product_info":{"status":1,"product_id":"1730000000000000001",'
    '"title":"Áo thun","price":{"min_sku_price":"99000","currency":"VND"},'
    '"images":[{"url_list":["https://img/1.jpg"]}]}</script>'
)


async def test_select_marks_the_product_with_the_shared_type(tmp_path) -> None:
    repository = product_repository()
    service = ProductCatalogService(repository)
    await service.ingest({"kind": "page", "url": URL, "html": HTML})
    assert await service.select("1730000000000000001") is True
    assert await service.selections() == {"1730000000000000001": GENERAL_TYPE}
    assert await service.select("missing") is False


async def test_pinterest_queue_ingest_and_filters(tmp_path) -> None:
    from ai_content.domains.marketing.products.references import ReferenceProfile

    repository = product_repository()
    service = ProductCatalogService(repository)
    await repository.add_profile_if_missing(
        ReferenceProfile("áo thun", ["ao thun flat lay", "t-shirt photo"], "approved")
    )
    queue = await service.reference_queue(10)
    assert [item["query"] for item in queue] == ["ao thun flat lay", "t-shirt photo"]
    assert queue[0]["url"] == "https://www.pinterest.com/search/pins/?filter_genai=true&q=ao+thun+flat+lay"

    pins = [
        {
            "image_url": "https://i.pinimg.com/236x/ab/cd/ef.jpg",
            "pin_url": "/pin/1/",
            "title": "Flat lay",
        },
        {
            "image_url": "https://i.pinimg.com/474x/ab/cd/ef.jpg",
            "pin_url": "/pin/1/",
            "title": "dup",
        },
        {
            "image_url": "https://i.pinimg.com/236x/aa/bb/cc.jpg",
            "pin_url": "/pin/2/",
            "title": "Other style",
        },
        {"image_url": "https://example.com/x.jpg", "pin_url": "/pin/3/", "title": "not pinterest"},
    ]
    stored = await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "ao thun flat lay", "pins": pins}
    )
    assert (stored["received"], stored["added"]) == (4, 2)
    images = await service.reference_images(None, "áo thun")
    assert "https://i.pinimg.com/736x/ab/cd/ef.jpg" in {i["image_url"] for i in images}
    assert [item["query"] for item in await service.reference_queue(10)] == ["t-shirt photo"]
    assert await service.set_image_status(images[0]["image_id"], "removed")
    assert len(await service.reference_images("removed", None)) == 1


async def test_ingest_screens_images_before_they_go_live(tmp_path) -> None:
    from ai_content.domains.marketing.products.image_review import ReferenceImageReviewer

    class _FakeReviewClient:
        async def ReviewReferenceImage(self, product_type, image):
            usable = product_type != "cốc"
            return SimpleNamespace(model_dump=lambda: {"usable": usable})

    class _Reviewer(ReferenceImageReviewer):
        async def review_all(self, images, http=None):
            return {
                image["image_id"]: (
                    await self._client.ReviewReferenceImage(image["product_type"], None)
                ).model_dump()
                for image in images
            }

    repository = product_repository()
    plain = ProductCatalogService(repository)
    pin = {
        "image_url": "https://i.pinimg.com/236x/ab/cd/ef.jpg",
        "pin_url": "/pin/1/",
        "title": "a",
    }
    other = {
        "image_url": "https://i.pinimg.com/236x/aa/bb/cc.jpg",
        "pin_url": "/pin/2/",
        "title": "b",
    }
    await plain.ingest({"kind": "pinterest", "product_type": "cốc", "query": "q", "pins": [other]})
    assert [i["status"] for i in await plain.reference_images(None, None)] == ["pending"]

    service = ProductCatalogService(repository, reviewer=_Reviewer(_FakeReviewClient()))
    stored = await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": [pin]}
    )
    assert stored["screened"] == {"reviewed": 2, "usable": 1, "rejected": 1, "failed": 0}
    statuses = {i["product_type"]: i["status"] for i in await service.reference_images(None, None)}
    assert statuses == {"áo thun": "live", "cốc": "rejected"}
