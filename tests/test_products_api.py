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


def test_select_queues_the_product_at_once(client: TestClient) -> None:
    _capture_product(client)
    result = client.post(f"/api/v1/products/{PRODUCT_ID}/select").json()
    assert result == {"product_id": PRODUCT_ID, "queued": True}
    assert client.get("/api/v1/products/selections").json() == {PRODUCT_ID: None}
    assert client.post("/api/v1/products/missing/select").status_code == 404


async def test_background_select_records_why_it_failed(
    repository: SqliteProductRepository, client: TestClient
) -> None:
    from contextlib import asynccontextmanager

    from ai_content.entrypoints.api import products as products_module

    _capture_product(client)

    @asynccontextmanager
    async def scope() -> AsyncIterator[ProductCatalogService]:
        yield ProductCatalogService(repository)

    await products_module._run_select(scope, PRODUCT_ID, False)
    assert "not configured" in products_module._select_errors[PRODUCT_ID]
    assert client.get("/api/v1/products/select-errors").json()[PRODUCT_ID]
    products_module._select_errors.clear()


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
    assert saved["status"] == "approved"
    assert saved["brief"] == {
        "scene": "b",
        "title": "t",
        "warnings": [],
        "quality_problems": [],
    }
    assert client.get(f"/api/v1/products/{PRODUCT_ID}/brief").json()["brief"]["scene"] == "b"


class _FakeWriter:
    async def write(self, product, user_idea, references, shot_count=1):
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
    client.app.dependency_overrides[get_product_catalog_service] = _service_without_embedder
    assert client.post("/api/v1/products/reference-images/backfill-fingerprints").status_code == 503


async def _service_without_embedder() -> AsyncIterator[ProductCatalogService]:
    service = ProductCatalogService(SqliteProductRepository(Path(":memory:")))
    service._embedder = None  # noqa: SLF001
    yield service


def test_ingesting_images_without_a_duplicate_check_is_refused_not_passed(
    client: TestClient,
) -> None:
    client.app.dependency_overrides[get_product_catalog_service] = _service_without_embedder
    body = {
        "kind": "pinterest",
        "product_type": "x",
        "query": "q",
        "pins": [
            {"image_url": "https://i.pinimg.com/236x/a/b/c.jpg", "pin_url": "/pin/1/", "title": "t"}
        ],
    }
    response = client.post("/api/v1/products/ingest", json=body)
    assert response.status_code == 503 and "duplicate check" in response.json()["detail"]


def test_media_download_with_no_products(client: TestClient) -> None:
    assert client.post("/api/v1/products/media/download").json() == {
        "downloaded": 0,
        "duplicates": 0,
        "skipped": 0,
        "failed": 0,
    }


def test_keyframe_endpoints(
    tmp_path: Path, client: TestClient, repository: SqliteProductRepository
) -> None:
    base = f"/api/v1/products/{PRODUCT_ID}/keyframes"
    assert client.post(base, json={}).status_code == 404
    _capture_product(client)
    asyncio.run(
        repository.save_brief(PRODUCT_ID, "", {"shots": [{"keyframe_prompt": "p"}]}, "draft")
    )
    assert client.get(base).json() == []
    assert client.post(base, json={}).status_code == 409
    assert client.get(f"{base}/0/image").status_code == 404

    image = tmp_path / "media" / "keyframes" / PRODUCT_ID / "shot_0.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpeg-bytes")
    keyframe = {
        "product_id": PRODUCT_ID,
        "shot_index": 0,
        "status": "ready",
        "prompt": "p",
        "image_path": f"keyframes/{PRODUCT_ID}/shot_0.jpg",
        "attempts": 1,
        "error": None,
        "qa_problem": "",
    }
    asyncio.run(repository.save_keyframe(keyframe))
    assert client.get(f"{base}/0/image").content == b"jpeg-bytes"
    assert client.put(f"{base}/0", json={"status": "approved"}).status_code == 200
    assert client.get(base).json()[0]["status"] == "approved"
    assert client.put(f"{base}/0", json={"status": "bogus"}).status_code == 422
    assert client.put(f"{base}/5", json={"status": "approved"}).status_code == 404


def test_clip_endpoints(
    tmp_path: Path, client: TestClient, repository: SqliteProductRepository
) -> None:
    base = f"/api/v1/products/{PRODUCT_ID}"
    assert client.post(f"{base}/clips", json={}).status_code == 404
    _capture_product(client)
    asyncio.run(repository.save_brief(PRODUCT_ID, "", {"shots": [{"role": "hook"}]}, "approved"))
    assert client.get(f"{base}/clips").json() == []
    assert client.post(f"{base}/clips", json={}).status_code == 409
    assert client.get(f"{base}/clips/0/video").status_code == 404
    assert client.get(f"{base}/video").status_code == 404
    assert client.post(f"{base}/video").status_code == 409

    media = tmp_path / "media"
    (media / "clips" / PRODUCT_ID).mkdir(parents=True)
    (media / "clips" / PRODUCT_ID / "shot_0.mp4").write_bytes(b"clip-bytes")
    clip = {
        "product_id": PRODUCT_ID,
        "shot_index": 0,
        "status": "ready",
        "job_id": "j",
        "job_model": "m",
        "video_path": f"clips/{PRODUCT_ID}/shot_0.mp4",
        "seconds": 6,
        "attempts": 1,
        "error": None,
    }
    asyncio.run(repository.save_clip(clip))
    assert client.get(f"{base}/clips/0/video").content == b"clip-bytes"
    (media / "videos" / PRODUCT_ID).mkdir(parents=True)
    (media / "videos" / PRODUCT_ID / "video.mp4").write_bytes(b"final")
    assert client.get(f"{base}/video").content == b"final"
    assert client.get(f"{base}/cover").status_code == 404
    (media / "videos" / PRODUCT_ID / "cover.jpg").write_bytes(b"cover")
    assert client.get(f"{base}/cover").content == b"cover"


def test_post_package_and_download(tmp_path: Path, client: TestClient) -> None:
    base = f"/api/v1/products/{PRODUCT_ID}"
    assert client.post(f"{base}/post-package").status_code == 404
    video = tmp_path / "media" / "videos" / PRODUCT_ID / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"final")
    download = client.get(f"{base}/video?download=true")
    assert download.content == b"final"
    assert PRODUCT_ID in download.headers["content-disposition"]
    assert "content-disposition" not in client.get(f"{base}/video").headers


def test_video_info_reports_whether_a_stitched_video_exists(
    tmp_path: Path, client: TestClient
) -> None:
    url = f"/api/v1/products/{PRODUCT_ID}/video-info"
    assert client.get(url).json() == {"exists": False, "voiceover": False}
    video = tmp_path / "media" / "videos" / PRODUCT_ID / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    assert client.get(url).json() == {"exists": True, "voiceover": False}
    (video.parent / "voiceover.mp3").write_bytes(b"v")
    assert client.get(url).json() == {"exists": True, "voiceover": True}
    assert client.get(url.replace("video-info", "voiceover")).content == b"v"


def test_voiceover_upload_replaces_the_previous_file(tmp_path: Path, client: TestClient) -> None:
    url = f"/api/v1/products/{PRODUCT_ID}/voiceover"
    folder = tmp_path / "media" / "videos" / PRODUCT_ID
    assert client.put(url, content=b"x", headers={"content-type": "text/plain"}).status_code == 415
    assert client.put(url, content=b"", headers={"content-type": "audio/wav"}).status_code == 422
    assert client.put(url, content=b"mp3", headers={"content-type": "audio/mpeg"}).json() == {
        "voiceover": "mp3"
    }
    assert client.put(url, content=b"wav", headers={"content-type": "audio/wav"}).json() == {
        "voiceover": "wav"
    }
    assert sorted(p.name for p in folder.iterdir()) == ["voiceover.json", "voiceover.wav"]


def test_persona_endpoints(
    tmp_path: Path, client: TestClient, repository: SqliteProductRepository
) -> None:
    base = f"/api/v1/products/{PRODUCT_ID}/persona"
    assert client.post(base, json={}).status_code == 404
    assert client.put(base, json={"status": "approved"}).status_code == 404
    assert client.get(f"{base}/image").status_code == 404
    _capture_product(client)
    persona = {
        "description": "woman, 28",
        "image_path": f"persona/{PRODUCT_ID}/persona.jpg",
        "status": "ready",
        "attempts": 1,
    }
    asyncio.run(repository.save_brief(PRODUCT_ID, "", {"persona": persona}, "approved"))
    assert client.post(base, json={}).status_code == 409
    assert client.put(base, json={"status": "bogus"}).status_code == 422
    assert client.get(f"{base}/image").status_code == 404

    portrait = tmp_path / "media" / "persona" / PRODUCT_ID / "persona.jpg"
    portrait.parent.mkdir(parents=True)
    portrait.write_bytes(b"portrait")
    assert client.get(f"{base}/image").content == b"portrait"
    assert client.put(base, json={"status": "approved"}).status_code == 200
    saved = client.get(f"/api/v1/products/{PRODUCT_ID}/brief").json()
    assert saved["brief"]["persona"]["status"] == "approved"


def test_voice_list_and_unknown_voice_sample(client: TestClient) -> None:
    listed = client.get("/api/v1/products/voices").json()
    assert {"id": "kimoanh.mp3", "label": "Kim Oanh"} in listed
    assert client.get("/api/v1/products/voices/nope/sample").status_code == 409


def test_deleting_a_product_removes_it_and_what_was_made_from_it(
    tmp_path: Path, client: TestClient
) -> None:
    _capture_product(client)
    media = tmp_path / "media"
    for relative in (f"keyframes/{PRODUCT_ID}/shot_0.jpg", f"videos/{PRODUCT_ID}/video.mp4"):
        (media / relative).parent.mkdir(parents=True, exist_ok=True)
        (media / relative).write_bytes(b"x")

    assert client.delete(f"/api/v1/products/{PRODUCT_ID}").json() == {"deleted": True}
    assert client.get("/api/v1/products").json() == []
    assert client.get(f"/api/v1/products/{PRODUCT_ID}").status_code == 404
    assert not (media / "keyframes" / PRODUCT_ID).exists()
    assert not (media / "videos" / PRODUCT_ID).exists()
    assert client.delete(f"/api/v1/products/{PRODUCT_ID}").status_code == 404

    # collecting the same product again does not bring it back
    _capture_product(client)
    assert client.get("/api/v1/products").json() == []
    assert PRODUCT_ID not in client.get("/api/v1/products/queue").text


def test_outputs_list_the_videos_and_say_what_each_is_made_from(
    tmp_path: Path, client: TestClient, repository: SqliteProductRepository
) -> None:
    base = f"/api/v1/products/{PRODUCT_ID}"
    assert client.get("/api/v1/products/outputs").json() == []
    assert client.get(f"{base}/output").status_code == 404
    _capture_product(client)
    shots = [
        {"role": "hook", "delivery": "talking", "voiceover": "Xin chào", "description": "d"},
        {"role": "call_to_action", "voiceover": "Mua ngay"},
    ]
    brief = {
        "title": "Giỏ",
        "shots": shots,
        "selected_reference_ids": ["r1"],
        "product_photo_urls": ["https://img.example/1.jpg"],
        "persona": {"description": "A woman", "image_path": "persona/p.jpg"},
    }
    asyncio.run(repository.save_brief(PRODUCT_ID, "ý tưởng", brief, "approved"))
    reference = {
        "image_id": "r1",
        "image_url": "https://i/r1.jpg",
        "pin_url": "/pin/1/",
        "title": "t",
    }
    asyncio.run(repository.add_reference_images("áo thun", "q", [reference]))
    asyncio.run(
        repository.save_keyframe(
            {
                "product_id": PRODUCT_ID,
                "shot_index": 0,
                "status": "approved",
                "prompt": "p",
                "image_path": "k.jpg",
                "attempts": 3,
                "error": None,
                "qa_problem": "",
            }
        )
    )
    assert client.get("/api/v1/products/outputs").json() == []

    folder = tmp_path / "media" / "videos" / PRODUCT_ID
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"final")
    (folder / "video.json").write_text(
        '{"built_at": "2026-11-05T10:00:00+00:00", "seconds": 23.6, "captions": false, '
        '"clip_attempts": {"0": 1}, "voice": {"voice": "Kim Oanh"}}',
        encoding="utf-8",
    )
    [item] = client.get("/api/v1/products/outputs").json()
    assert (item["title"], item["seconds"], item["shots"], item["voice"]) == (
        "Giỏ",
        23.6,
        1,
        "Kim Oanh",
    )

    output = client.get(f"{base}/output").json()
    assert output["product"]["title"] == "Áo thun"
    assert output["brief"]["user_idea"] == "ý tưởng"
    assert output["product_photos"] == ["https://img.example/1.jpg"]
    assert [r["image_url"] for r in output["references"]] == ["https://i/r1.jpg"]
    assert output["persona"] == {"description": "A woman", "has_image": True}
    first, second = output["shots"]
    assert (first["has_keyframe"], first["keyframe_attempts"], first["in_video"]) == (True, 3, True)
    assert (second["delivery"], second["in_video"]) == ("narrated", False)
    assert output["video"]["voice"] == "Kim Oanh" and output["video"]["exists"] is True


def test_user_photo_becomes_the_person_after_rights_are_confirmed(
    tmp_path: Path, client: TestClient, repository: SqliteProductRepository
) -> None:
    url = f"/api/v1/products/{PRODUCT_ID}/persona/image"
    jpeg = {"content-type": "image/jpeg"}
    assert client.put(f"{url}?rights=confirmed", content=b"x", headers=jpeg).status_code == 404
    _capture_product(client)
    asyncio.run(repository.save_brief(PRODUCT_ID, "", {"title": "b"}, "approved"))
    assert client.put(url, content=b"photo", headers=jpeg).status_code == 422
    confirmed = f"{url}?rights=confirmed"
    assert (
        client.put(confirmed, content=b"x", headers={"content-type": "text/plain"}).status_code
        == 415
    )
    assert client.put(confirmed, content=b"", headers=jpeg).status_code == 422
    saved = client.put(confirmed, content=b"photo", headers=jpeg).json()
    assert saved["status"] == "ready" and saved["source"] == "uploaded"
    assert client.get(url).content == b"photo"
    assert (
        client.put(
            f"/api/v1/products/{PRODUCT_ID}/persona", json={"status": "approved"}
        ).status_code
        == 200
    )
