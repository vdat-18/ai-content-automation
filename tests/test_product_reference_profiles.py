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


async def test_images_wait_for_the_review_and_only_the_review_makes_them_live(tmp_path) -> None:
    from ai_content.domains.marketing.products.image_review import ReferenceImageReviewer

    class _FakeReviewClient:
        async def ReviewReferenceImage(self, image):
            return SimpleNamespace(model_dump=lambda: {"usable": image != "cốc"})

    class _Reviewer(ReferenceImageReviewer):
        async def review_all(self, images, http=None):
            return {
                image["image_id"]: (
                    await self._client.ReviewReferenceImage(image["product_type"])
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
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": [pin]}
    )
    assert {i["status"] for i in await service.reference_images(None, None)} == {"pending"}
    counts = await service.screen_images(10)
    assert counts == {"reviewed": 2, "usable": 1, "rejected": 1, "failed": 0}
    statuses = {i["product_type"]: i["status"] for i in await service.reference_images(None, None)}
    assert statuses == {"áo thun": "live", "cốc": "rejected"}


async def test_review_of_all_waiting_images_stops_when_the_model_stops_answering(
    monkeypatch,
) -> None:
    from ai_content.domains.marketing.products import service as service_module
    from ai_content.domains.marketing.products.image_review import ReferenceImageReviewer

    monkeypatch.setattr(service_module, "SCREEN_BATCH", 2)
    batches = {"answered": 0, "limit": 1}

    class _Reviewer(ReferenceImageReviewer):
        def __init__(self) -> None:
            pass

        async def review_all(self, images, http=None):
            answered = batches["answered"] < batches["limit"]
            batches["answered"] += 1
            return {i["image_id"]: ({"usable": True} if answered else None) for i in images}

    service = ProductCatalogService(product_repository(), reviewer=_Reviewer())
    pins = [
        {"image_url": f"https://i.pinimg.com/236x/aa/bb/{n:02d}.jpg", "pin_url": f"/pin/{n}/", "title": "t"}
        for n in range(5)
    ]
    await service.ingest({"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins})

    seen: list[dict[str, int]] = []
    assert await service.screen_pending(seen.append) is False  # batch 2 got no answer
    assert seen[-1] == {"total": 5, "reviewed": 2, "usable": 2, "rejected": 0, "failed": 2}
    assert len(await service.reference_images("pending", None)) == 3

    batches.update(answered=0, limit=99)  # the quota is back: the next run carries on
    assert await service.screen_pending(seen.append) is True
    assert seen[-1]["reviewed"] == 3
    assert await service.reference_images("pending", None) == []


async def test_the_vector_of_a_description_is_stored_as_soon_as_the_review_is_done() -> None:
    class _Reviewer:
        async def review_all(self, images, http=None):
            return {
                i["image_id"]: {"usable": i["title"] != "bad", "description": f"scene {i['title']}"}
                for i in images
            }

    class _Embedder:
        model = "m1"

        async def embed(self, texts):
            return [[float(len(text)), 0.0] for text in texts]

    repository = product_repository()
    service = ProductCatalogService(
        repository, reviewer=_Reviewer(), text_embedder=_Embedder()  # type: ignore[arg-type]
    )
    pins = [
        {"image_url": f"https://i.pinimg.com/236x/aa/bb/{n}.jpg", "pin_url": f"/p/{n}/", "title": n}
        for n in ("good", "bad")
    ]
    await service.ingest({"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins})
    await service.screen_images(10)

    stored = await repository.text_embeddings()
    [live] = await service.reference_images("live", None)
    assert list(stored) == [live["image_id"]]  # the rejected picture has none
    assert stored[live["image_id"]] == {"model": "m1", "vector": [float(len("scene good")), 0.0]}
