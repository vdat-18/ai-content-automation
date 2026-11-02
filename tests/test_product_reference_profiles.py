from types import SimpleNamespace

from ai_content.domains.marketing.products.references import ReferenceProfileGenerator
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService

URL = "https://shop.tiktok.com/vn/pdp/ao-thun/1730000000000000001"
HTML = (
    '<script>"product_info":{"status":1,"product_id":"1730000000000000001",'
    '"title":"Áo thun","price":{"min_sku_price":"99000","currency":"VND"},'
    '"images":[{"url_list":["https://img/1.jpg"]}]}</script>'
)


class _FakeBamlClient:
    async def DraftReferenceSearchProfile(self, product_json: str) -> SimpleNamespace:
        return SimpleNamespace(
            product_type="Áo thun",
            keywords=["ao thun flat lay", "t-shirt photography"],
            exclude_keywords=["meme"],
        )


async def test_select_drafts_profile_once_per_type(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "s.db")
    service = ProductCatalogService(repository, ReferenceProfileGenerator(_FakeBamlClient()))
    await service.ingest({"kind": "page", "url": URL, "html": HTML})
    result = await service.select("1730000000000000001")
    assert result is not None and result["profile"]["product_type"] == "áo thun"
    await service.select("1730000000000000001")
    assert len(await service.profiles()) == 1
    assert await service.selections() == {"1730000000000000001": "áo thun"}
    assert await service.select("missing") is None
    repository.close()


async def test_pinterest_queue_ingest_and_filters(tmp_path) -> None:
    from ai_content.domains.marketing.products.references import ReferenceProfile

    repository = SqliteProductRepository(tmp_path / "p.db")
    service = ProductCatalogService(repository)
    await repository.add_profile_if_missing(
        ReferenceProfile("áo thun", ["ao thun flat lay", "t-shirt photo"], ["meme"], "approved")
    )
    queue = await service.reference_queue(10)
    assert [item["query"] for item in queue] == ["ao thun flat lay", "t-shirt photo"]
    assert queue[0]["url"] == "https://www.pinterest.com/search/pins/?q=ao+thun+flat+lay"

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
            "title": "Funny MEME",
        },
        {"image_url": "https://example.com/x.jpg", "pin_url": "/pin/3/", "title": "not pinterest"},
    ]
    stored = await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "ao thun flat lay", "pins": pins}
    )
    assert (stored["received"], stored["added"]) == (4, 1)
    images = await service.reference_images(None, "áo thun")
    assert images[0]["image_url"] == "https://i.pinimg.com/736x/ab/cd/ef.jpg"
    assert [item["query"] for item in await service.reference_queue(10)] == ["t-shirt photo"]
    assert await service.set_image_status(images[0]["image_id"], "approved")
    assert len(await service.reference_images("approved", None)) == 1
    repository.close()
