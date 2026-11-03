import asyncio
import json
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from ai_content.domains.marketing.products.references import ReferenceProfile
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService
from ai_content.entrypoints.api.dependencies import get_product_catalog_service
from ai_content.entrypoints.api.products import router

PRODUCT_ID = "1730000000000000001"
URL = f"https://shop.tiktok.com/vn/pdp/ao-thun/{PRODUCT_ID}"
INFO = {
    "status": 1,
    "product_id": PRODUCT_ID,
    "title": "Áo thun",
    "price": {"min_sku_price": "99000", "currency": "VND"},
    "sold_count": 1200,
    "images": [{"url_list": ["https://img/1.jpg"]}],
}
HTML = (
    '<script>"product_info":'
    + json.dumps(INFO, ensure_ascii=False, separators=(",", ":"))
    + ',"review_ratings":{"rating_result":{"5":"10","4":"2","3":"0","2":"0","1":"1"}}</script>'
)
FEED_URL = "https://shop.tiktok.com/api/homepage_desktop/products_by_component"
FEED = json.dumps(
    {
        "data": {
            "productList": [
                {
                    "product_id": "2",
                    "title": "Cốc",
                    "product_price_info": {"currency_name": "VND", "sale_price_decimal": "50.000"},
                    "sold_info": {"sold_count": 30},
                    "seo_url": {"canonical_url": "https://shop.tiktok.com/vn/pdp/coc/2"},
                },
                {
                    "product_id": "3",
                    "title": "E-voucher giảm 50k",
                    "product_price_info": {"currency_name": "VND", "sale_price_decimal": "50.000"},
                    "sold_info": {"sold_count": 99},
                    "seo_url": {"canonical_url": "https://shop.tiktok.com/vn/pdp/voucher/3"},
                },
            ]
        }
    }
)


@pytest.fixture
def repository(tmp_path: Path) -> SqliteProductRepository:
    return SqliteProductRepository(tmp_path / "state.db")


@pytest.fixture
def client(
    tmp_path: Path, repository: SqliteProductRepository, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("AIC_AI_DATA_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)

    async def service() -> AsyncIterator[ProductCatalogService]:
        yield ProductCatalogService(repository)

    app.dependency_overrides[get_product_catalog_service] = service
    return TestClient(app)


def _capture_product(client: TestClient) -> None:
    response = client.post(
        "/api/v1/products/ingest", json={"kind": "page", "url": URL, "html": HTML}
    )
    assert response.json() == {"stored": "detail", "product_id": PRODUCT_ID}


def test_ingest_list_detail_and_junk_filter(client: TestClient) -> None:
    _capture_product(client)
    assert [p["product_id"] for p in client.get("/api/v1/products").json()] == [PRODUCT_ID]
    assert client.get(f"/api/v1/products/{PRODUCT_ID}").json()["title"] == "Áo thun"
    assert client.get("/api/v1/products/missing").status_code == 404

    voucher = HTML.replace("Áo thun", "E-voucher giảm 50k").replace(PRODUCT_ID, "9")
    client.post(
        "/api/v1/products/ingest",
        json={"kind": "page", "url": URL.replace(PRODUCT_ID, "9"), "html": voucher},
    )
    assert len(client.get("/api/v1/products").json()) == 1
    assert len(client.get("/api/v1/products?include_junk=true").json()) == 2


def test_ingest_ignores_unsupported_captures(client: TestClient) -> None:
    for payload in (
        {"kind": "page", "url": "https://shop.tiktok.com/vn", "html": "<html/>"},
        {"kind": "page", "url": URL, "html": "<html>no product</html>"},
        {"kind": "json", "url": "https://example.com/other", "body": "{}"},
        {"kind": "unknown"},
    ):
        assert client.post("/api/v1/products/ingest", json=payload).json()["stored"] == "ignored"
    assert client.get("/api/v1/products").json() == []


def test_queue_skips_captured_vouchers_and_non_vnd(client: TestClient) -> None:
    client.post("/api/v1/products/ingest", json={"kind": "json", "url": FEED_URL, "body": FEED})
    assert client.get("/api/v1/products/queue").json() == ["https://shop.tiktok.com/vn/pdp/coc/2"]
    client.post(
        "/api/v1/products/ingest",
        json={
            "kind": "page",
            "url": "https://shop.tiktok.com/vn/pdp/coc/2",
            "html": HTML.replace(PRODUCT_ID, "2"),
        },
    )
    assert client.get("/api/v1/products/queue").json() == []


def test_export_json_and_xlsx(client: TestClient) -> None:
    _capture_product(client)
    exported = client.get("/api/v1/products/export?format=json")
    assert exported.headers["content-disposition"].endswith('products.json"')
    assert exported.json()[0]["rating_distribution"]["5"] == "10"

    workbook = load_workbook(BytesIO(client.get("/api/v1/products/export?format=xlsx").content))
    rows = list(workbook["products"].iter_rows(values_only=True))
    header = rows[0]
    assert rows[1][header.index("product_id")] == PRODUCT_ID
    assert rows[1][header.index("star_5")] == "10"
    assert client.get("/api/v1/products/export?format=csv").status_code == 422


def test_select_without_llm_marks_product_and_reports_error(client: TestClient) -> None:
    _capture_product(client)
    result = client.post(f"/api/v1/products/{PRODUCT_ID}/select").json()
    assert result["profile"] is None and "not configured" in result["error"]
    assert client.get("/api/v1/products/selections").json() == {PRODUCT_ID: None}
    assert client.post("/api/v1/products/missing/select").status_code == 404


def test_reference_profile_update_and_queue(
    client: TestClient, repository: SqliteProductRepository
) -> None:
    assert (
        client.put("/api/v1/products/reference-profiles/x", json={"keywords": ["a"]}).status_code
        == 404
    )
    asyncio.run(repository.add_profile_if_missing(ReferenceProfile("áo thun", ["old"])))
    assert client.get("/api/v1/products/reference-queue").json() == []

    updated = client.put(
        "/api/v1/products/reference-profiles/áo thun",
        json={"keywords": ["ao thun flat lay", "t-shirt photo"], "status": "approved"},
    ).json()
    assert updated["status"] == "approved"
    assert client.get("/api/v1/products/reference-profiles").json()[0]["keywords"] == [
        "ao thun flat lay",
        "t-shirt photo",
    ]
    queue = client.get("/api/v1/products/reference-queue?limit=1").json()
    assert queue == [
        {
            "url": "https://www.pinterest.com/search/pins/?q=ao+thun+flat+lay",
            "product_type": "áo thun",
            "query": "ao thun flat lay",
        }
    ]


def test_reference_image_review_flow(client: TestClient) -> None:
    pins = [
        {"image_url": "https://i.pinimg.com/236x/ab/cd/ef.jpg", "pin_url": "/pin/1/", "title": "t"}
    ]
    body = {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins}
    stored = client.post("/api/v1/products/ingest", json=body).json()
    assert stored["added"] == 1 and stored["screened"] is None
    image = client.get("/api/v1/products/reference-images?status=pending").json()[0]
    assert image["image_url"].startswith("https://i.pinimg.com/736x/")

    assert client.delete(f"/api/v1/products/reference-images/{image['image_id']}").json() == {
        "image_id": image["image_id"],
        "status": "removed",
    }
    assert client.delete("/api/v1/products/reference-images/missing").status_code == 404
    assert len(client.get("/api/v1/products/reference-images?status=removed").json()) == 1
    again = client.post("/api/v1/products/ingest", json=body).json()
    assert again["added"] == 0
    assert client.post("/api/v1/products/reference-images/screen").status_code == 503


def test_brief_endpoints(client: TestClient, repository: SqliteProductRepository) -> None:
    assert client.post("/api/v1/products/missing/brief", json={}).status_code == 404
    _capture_product(client)
    assert client.post(f"/api/v1/products/{PRODUCT_ID}/brief", json={}).status_code == 503
    assert client.get(f"/api/v1/products/{PRODUCT_ID}/brief").status_code == 404
    update = {"brief": {}, "status": "approved"}
    assert client.put(f"/api/v1/products/{PRODUCT_ID}/brief", json=update).status_code == 404
    bogus = {"brief": {}, "status": "bogus"}
    assert client.put(f"/api/v1/products/{PRODUCT_ID}/brief", json=bogus).status_code == 422

    asyncio.run(repository.save_brief(PRODUCT_ID, "idea", {"scene": "a", "title": "t"}, "draft"))
    assert client.get("/api/v1/products/briefs").json()[0]["user_idea"] == "idea"
    edit = {"brief": {"scene": "b"}, "status": "approved"}
    saved = client.put(f"/api/v1/products/{PRODUCT_ID}/brief", json=edit).json()
    assert saved["status"] == "approved" and saved["brief"] == {"scene": "b", "title": "t"}
    assert client.get(f"/api/v1/products/{PRODUCT_ID}/brief").json()["brief"]["scene"] == "b"


class _FakeWriter:
    async def write(self, product, user_idea, references):
        return {"title": "T", "idea_seen": user_idea, "selected_reference_ids": []}


def test_brief_creation_reports_unmet_preconditions_then_succeeds(
    tmp_path: Path, repository: SqliteProductRepository
) -> None:
    app = FastAPI()
    app.include_router(router)

    async def service() -> AsyncIterator[ProductCatalogService]:
        yield ProductCatalogService(repository, briefer=_FakeWriter())

    app.dependency_overrides[get_product_catalog_service] = service
    client = TestClient(app)
    _capture_product(client)
    url = f"/api/v1/products/{PRODUCT_ID}/brief"

    first = client.post(url, json={"idea": "ban công"})
    assert first.status_code == 409 and "Select this product" in first.json()["detail"]
    asyncio.run(repository.select_product(PRODUCT_ID, "áo thun"))
    assert client.post(url, json={}).status_code == 409

    pins = [{"image_url": "https://i.pinimg.com/236x/ab/cd/ef.jpg", "pin_url": "/p/", "title": "t"}]
    body = {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins}
    client.post("/api/v1/products/ingest", json=body)
    image = client.get("/api/v1/products/reference-images?status=pending").json()[0]
    asyncio.run(repository.set_image_status(image["image_id"], "live"))
    created = client.post(url, json={"idea": "ban công"}).json()
    assert created["user_idea"] == "ban công" and created["brief"]["idea_seen"] == "ban công"


def test_backfill_needs_the_embedding_model(client: TestClient) -> None:
    assert client.post("/api/v1/products/reference-images/backfill-fingerprints").status_code == 503


def test_media_download_with_no_products(client: TestClient) -> None:
    assert client.post("/api/v1/products/media/download").json() == {
        "downloaded": 0,
        "duplicates": 0,
        "skipped": 0,
        "failed": 0,
    }
