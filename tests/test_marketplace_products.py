import json
from io import BytesIO

from openpyxl import load_workbook

from ai_content.domains.marketing.products.parsing import parse_feed_payload, parse_product_page
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService

URL = "https://shop.tiktok.com/vn/pdp/ao-thun/1730000000000000001"
INFO = {
    "status": 1,
    "product_id": "1730000000000000001",
    "title": "Áo thun",
    "price": {"min_sku_price": "99000", "currency": "VND"},
    "sold_count": 1200,
    "images": [{"url_list": ["https://img/1.jpg"]}],
    "skus": [{"sku_id": "s1", "sku_sale_props": [{"prop_value": "Đen"}], "stock": 5}],
    "specifications": [{"name": "Chất liệu", "value": "Cotton"}],
    "header_video": {"id": "v1", "duration": 12, "video_infos": [{"width": 720, "main_url": "u"}]},
}
HTML = (
    "<html><script>"
    + '"product_info":'
    + json.dumps(INFO, ensure_ascii=False, separators=(",", ":"))
    + ',"review_ratings":{"rating_result":{"5":"10","4":"2","3":"0","2":"0","1":"1"}}'
    + "</script></html>"
)
FEED = json.dumps(
    {
        "data": {
            "productList": [
                {
                    "product_id": "1730000000000000002",
                    "title": "Cốc",
                    "product_price_info": {"currency_name": "VND", "sale_price_decimal": "50.000"},
                    "sold_info": {"sold_count": 30},
                    "seo_url": {
                        "canonical_url": "https://shop.tiktok.com/vn/pdp/coc/1730000000000000002"
                    },
                    "bind_video": {"id": "x"},
                },
                {"product_id": "9", "product_price_info": {"currency_name": "USD"}},
            ]
        }
    }
)


def test_parse_product_page() -> None:
    product = parse_product_page(HTML, URL)
    assert product is not None
    assert product["product_id"] == "1730000000000000001"
    assert product["rating_distribution"]["5"] == "10"
    assert product["variants"][0]["variant"] == "Đen"
    assert product["specifications"] == {"Chất liệu": "Cotton"}


def test_parse_feed_keeps_only_vnd() -> None:
    items = parse_feed_payload(FEED)
    assert [item["product_id"] for item in items] == ["1730000000000000002"]
    assert items[0]["has_video"] is True


async def test_ingest_queue_and_export(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "p.db")
    service = ProductCatalogService(repository)
    assert (
        await service.ingest(
            {"kind": "json", "url": "x/homepage_desktop/products_by_component", "body": FEED}
        )
    )["count"] == 1
    assert await service.queue(5) == ["https://shop.tiktok.com/vn/pdp/coc/1730000000000000002"]
    stored = await service.ingest({"kind": "page", "url": URL, "html": HTML})
    assert stored["stored"] == "detail"
    assert len(await service.details()) == 1
    book = load_workbook(BytesIO(await service.export_workbook()))
    assert book.sheetnames == ["products", "variants", "images", "videos", "specifications"]
    assert book["products"].max_row == 2
    repository.close()


def test_junk_reason() -> None:
    from ai_content.domains.marketing.products.parsing import junk_reason

    base = {"price": {"sale": "99000", "currency": "VND"}, "title": "Áo", "images": ["u"]}
    assert junk_reason(base) is None
    assert junk_reason({**base, "price": {"sale": "1", "currency": "VND"}})
    assert junk_reason({**base, "title": "E-voucher giảm 50k"})
    assert junk_reason({**base, "images": []})


async def test_media_download_skips_duplicates(tmp_path) -> None:
    import httpx

    from ai_content.domains.marketing.products.media import download_product_media

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"same-bytes", headers={"content-type": "image/jpeg"})

    products = [
        {"product_id": "1", "images": ["https://x/a", "https://x/b"]},
        {"product_id": "2", "images": ["https://x/c"]},
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await download_product_media(products, tmp_path, client)
        again = await download_product_media(products, tmp_path, client)
    assert (report.downloaded, report.duplicates) == (1, 2)
    assert again.skipped == 1
