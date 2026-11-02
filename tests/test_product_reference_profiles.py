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
