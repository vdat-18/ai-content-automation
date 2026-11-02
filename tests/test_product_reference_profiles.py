import httpx

from ai_content.domains.marketing.products.references import (
    ReferenceProfileGenerator,
    parse_profile,
)
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService

URL = "https://shop.tiktok.com/vn/pdp/ao-thun/1730000000000000001"
HTML = (
    '<script>"product_info":{"status":1,"product_id":"1730000000000000001",'
    '"title":"Áo thun","price":{"min_sku_price":"99000","currency":"VND"},'
    '"images":[{"url_list":["https://img/1.jpg"]}]}</script>'
)
ANSWER = (
    '{"product_type":"Áo thun","keywords":["ao thun flat lay","t-shirt photography"],'
    '"exclude_keywords":["meme"]}'
)


async def test_select_drafts_profile_once_per_type(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = f"```json\n{ANSWER}\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    assert parse_profile(ANSWER).product_type == "áo thun"
    repository = SqliteProductRepository(tmp_path / "s.db")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = ReferenceProfileGenerator(
            base_url="http://x/v1", api_key="k", model="m", client=client
        )
        service = ProductCatalogService(repository, generator)
        await service.ingest({"kind": "page", "url": URL, "html": HTML})
        result = await service.select("1730000000000000001")
        assert result["profile"]["product_type"] == "áo thun"
        await service.select("1730000000000000001")
    assert len(await service.profiles()) == 1
    assert await service.selections() == {"1730000000000000001": "áo thun"}
    assert await service.select("missing") is None
    repository.close()
