import json
from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook
from tests.pgstore import product_repository

from ai_content.domains.marketing.products.parsing import (
    category_from_page_url,
    is_feed_url,
    parse_feed_payload,
    parse_product_page,
)
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
    repository = product_repository()
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


def test_junk_reason() -> None:
    from ai_content.domains.marketing.products.parsing import junk_reason

    base = {"price": {"sale": "99000", "currency": "VND"}, "title": "Áo", "images": ["u"]}
    assert junk_reason(base) is None
    assert junk_reason({**base, "price": {"sale": "1", "currency": "VND"}})
    assert junk_reason({**base, "title": "E-voucher giảm 50k"})
    assert junk_reason({**base, "images": []})
    assert junk_reason({**base, "title": "QUÀ TẶNG Thẻ Bảo Hành"})
    assert junk_reason({**base, "title": "[Tặng kèm] Gối ôm"})
    assert junk_reason({**base, "title": "Áo thun nam, tặng kèm móc khóa"}) is None


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


def test_parsing_helpers_and_rich_description() -> None:
    from ai_content.domains.marketing.products.parsing import (
        money,
        parse_feed_payload,
        parse_product_page,
        product_id_from_url,
    )

    assert product_id_from_url(URL) == "1730000000000000001"
    assert product_id_from_url("https://shop.tiktok.com/vn") is None
    assert money("1.234.000", "VND") == 1234000
    assert money("47.97", "USD") is None
    assert money("abc", "VND") is None

    info = {
        **INFO,
        "desc_blocks": [
            {"type": "text", "text": "Mô tả"},
            {"type": "ul", "content": [{"text": "ý một"}, "ý hai"]},
        ],
        "shipping": {},
    }
    html = '<script>"product_info":' + json.dumps(info, separators=(",", ":")) + "</script>"
    product = parse_product_page(html, URL)
    assert product is not None and product["description"] == "Mô tả\n- ý một\n- ý hai"
    assert parse_product_page("<html></html>", URL) is None

    assert parse_feed_payload("not json") == []
    components = json.dumps(
        {
            "data": {
                "components_map": [
                    {
                        "component_data": {
                            "products": [
                                {
                                    "product_id": "7",
                                    "product_price_info": {"currency_name": "VND"},
                                }
                            ]
                        }
                    }
                ]
            }
        }
    )
    assert [item["product_id"] for item in parse_feed_payload(components)] == ["7"]


_COMPLETE_REVIEW = {
    "score": 4,
    "setting": "room",
    "lighting": "soft",
    "camera": "eye level",
    "placement": "shelf",
}


async def test_reference_image_reviewer_handles_failures(monkeypatch) -> None:
    import httpx
    from baml_py.baml_py import BamlClientError

    from ai_content.domains.marketing.products import image_review
    from ai_content.domains.marketing.products.image_review import ReferenceImageReviewer

    monkeypatch.setattr(image_review, "_image", lambda content: content)  # the client sees the bytes

    class _Client:
        async def ReviewReferenceImage(self, image):
            if image == b"rate":
                raise BamlClientError("429", "429", "429")
            return SimpleNamespace(model_dump=lambda: dict(_COMPLETE_REVIEW))

    def handler(request: httpx.Request) -> httpx.Response:
        if "missing" in request.url.path:
            return httpx.Response(404)
        content = b"rate" if "rate" in request.url.path else b"img"
        return httpx.Response(200, content=content, headers={"content-type": "image/jpeg"})

    images = [
        {"image_id": "ok", "product_type": "áo", "image_url": "https://x/ok.jpg"},
        {"image_id": "gone", "product_type": "áo", "image_url": "https://x/missing.jpg"},
        {"image_id": "rate", "product_type": "lỗi", "image_url": "https://x/rate.jpg"},
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        reviews = await ReferenceImageReviewer(_Client()).review_all(images, http)
    assert reviews == {"ok": {**_COMPLETE_REVIEW, "usable": True}, "gone": None, "rate": None}


def test_a_category_feed_is_recognised_and_read_wherever_it_nests_the_products() -> None:
    assert is_feed_url(
        "https://shop.tiktok.com/api/shop/vn/homepage_desktop/products_by_category?x=1"
    )
    assert is_feed_url("https://shop.tiktok.com/api/homepage_desktop/products_by_component")
    assert not is_feed_url("https://shop.tiktok.com/api/shop/vn/other")
    body = json.dumps(
        {
            "code": 0,
            "data": {
                "section": {
                    "items": [
                        {
                            "product_id": "9",
                            "title": "Mít sấy",
                            "product_price_info": {
                                "currency_name": "VND",
                                "sale_price_decimal": "21.573",
                            },
                            "sold_info": {"sold_count": 6000},
                        },
                        {"product_id": "10", "product_price_info": {"currency_name": "USD"}},
                    ]
                }
            },
        }
    )
    items = parse_feed_payload(body)
    assert [item["product_id"] for item in items] == ["9"]
    assert items[0]["sold_count"] == 6000


def test_the_category_comes_from_the_link_of_the_category_page() -> None:
    page = "https://shop.tiktok.com/vn/c/food-beverages/700437?source=ecommerce_mall"
    assert category_from_page_url(page) == "food-beverages"
    assert category_from_page_url("https://shop.tiktok.com/vn") is None
    assert category_from_page_url("https://shop.tiktok.com/vn/pdp/ao/1730000000000000001") is None


async def test_a_product_keeps_the_category_of_the_list_it_was_collected_from() -> None:
    service = ProductCatalogService(product_repository())
    feed = json.dumps(
        {
            "data": {
                "productList": [
                    {
                        "product_id": "1730000000000000001",
                        "title": "Áo thun",
                        "product_price_info": {"currency_name": "VND"},
                    }
                ]
            }
        }
    )
    await service.ingest(
        {
            "kind": "json",
            "url": "x/homepage_desktop/products_by_category",
            "page_url": "https://shop.tiktok.com/vn/c/fashion/601450?source=x",
            "body": feed,
        }
    )
    await service.ingest({"kind": "page", "url": URL, "html": HTML})
    [product] = await service.details()
    assert product["category"] == "fashion"


async def test_a_product_sent_alone_takes_its_category_from_its_own_page() -> None:
    service = ProductCatalogService(product_repository())
    info = {**INFO, "product_id": "1730000000000000005"}
    html = (
        '<script>"product_info":'
        + json.dumps(info, ensure_ascii=False, separators=(",", ":"))
        + ',"category_name":"Food & Beverages","category_name":"Snacks"</script>'
    )
    await service.ingest(
        {
            "kind": "page",
            "url": URL.replace("1730000000000000001", "1730000000000000005"),
            "html": html,
        }
    )
    [product] = await service.details()
    assert product["category"] == "food-beverages"


async def test_a_vietnamese_category_name_becomes_a_plain_slug() -> None:
    service = ProductCatalogService(product_repository())
    info = {**INFO, "product_id": "1730000000000000006"}
    html = (
        '<script>"product_info":'
        + json.dumps(info, ensure_ascii=False, separators=(",", ":"))
        + ',"category_name":"Điện thoại & Điện tử"</script>'
    )
    url = URL.replace("1730000000000000001", "1730000000000000006")
    await service.ingest({"kind": "page", "url": url, "html": html})
    [product] = await service.details()
    assert product["category"] == "dien-thoai-dien-tu"


def test_a_feed_product_without_a_link_gets_one_from_its_id() -> None:
    body = json.dumps(
        {"data": {"items": [{"product_id": "77", "product_price_info": {"currency_name": "VND"}}]}}
    )
    [item] = parse_feed_payload(body)
    assert item["url"] == "https://shop.tiktok.com/vn/pdp/77"
