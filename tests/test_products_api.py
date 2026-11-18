import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from tests.pgstore import product_repository, runtime_container

from ai_content.domains.marketing.products.pipeline import PipelineStopped
from ai_content.domains.marketing.products.references import GENERAL_TYPE, ReferenceProfile
from ai_content.domains.marketing.products.repositories import PostgresProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService
from ai_content.entrypoints.api import products as products_api
from ai_content.entrypoints.api.dependencies import get_product_catalog_service
from ai_content.entrypoints.api.products import router
from ai_content.platform.notifications import Notification

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
def repository(tmp_path: Path) -> PostgresProductRepository:
    return product_repository()


@pytest.fixture
def client(
    tmp_path: Path, repository: PostgresProductRepository, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("AIC_AI_DATA_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    app.state.postgres_runtime = runtime_container()

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
    assert "raw_product_info" not in client.get("/api/v1/products").json()[0]
    assert "raw_product_info" in client.get(f"/api/v1/products/{PRODUCT_ID}").json()
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


def test_select_marks_the_product_for_the_shared_pool(client: TestClient) -> None:
    _capture_product(client)
    result = client.post(f"/api/v1/products/{PRODUCT_ID}/select").json()
    assert result == {"product_id": PRODUCT_ID}
    assert client.get("/api/v1/products/selections").json() == {PRODUCT_ID: GENERAL_TYPE}
    assert client.post("/api/v1/products/missing/select").status_code == 404


def test_reference_profile_update_and_queue(
    client: TestClient, repository: PostgresProductRepository
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
            "url": "https://www.pinterest.com/search/pins/?filter_genai=true&q=ao+thun+flat+lay",
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
    assert stored["added"] == 1 and "screened" not in stored
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
    assert client.get("/api/v1/products/reference-images/screen").json()["status"] == "idle"


def test_pipeline_endpoints_report_state_and_refuse_a_second_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = "/api/v1/products"
    assert client.post(f"{base}/missing/pipeline", json={}).status_code == 404
    assert client.get(f"{base}/{PRODUCT_ID}/pipeline").json()["status"] == "idle"
    _capture_product(client)
    run = {"status": "running", "step": "Writing storyboard brief", "message": ""}
    monkeypatch.setitem(products_api._pipeline_runs, PRODUCT_ID, run)
    assert client.get(f"{base}/{PRODUCT_ID}/pipeline").json() == run
    assert client.post(f"{base}/{PRODUCT_ID}/pipeline", json={}).status_code == 409


def test_brief_endpoints(client: TestClient, repository: PostgresProductRepository) -> None:
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
    assert saved["brief"] == {"scene": "b", "title": "t"}
    assert client.get(f"/api/v1/products/{PRODUCT_ID}/brief").json()["brief"]["scene"] == "b"


class _FakeWriter:
    async def write(self, product, user_idea, shot_count=1, person_photos=None, rules="", earlier=""):
        return {"title": "T", "idea_seen": user_idea, "selected_reference_ids": []}


def test_brief_creation_reports_unmet_preconditions_then_succeeds(
    tmp_path: Path, repository: PostgresProductRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIC_AI_DATA_ROOT", str(tmp_path))
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
    refused = client.post(url, json={"idea": "ban công"})
    assert refused.status_code == 409 and "photo of the person" in refused.json()["detail"]
    person = client.post("/api/v1/products/persona", json={"name": "Đạt"}).json()
    photo = f"/api/v1/products/persona/{person['id']}/image?rights=confirmed"
    client.put(photo, content=b"face", headers={"content-type": "image/jpeg"})
    created = client.post(url, json={"idea": "ban công"}).json()
    assert created["user_idea"] == "ban công" and created["brief"]["idea_seen"] == "ban công"


def test_backfill_needs_the_embedding_model(client: TestClient) -> None:
    client.app.dependency_overrides[get_product_catalog_service] = _service_without_embedder
    assert client.post("/api/v1/products/reference-images/backfill-fingerprints").status_code == 503


async def _service_without_embedder() -> AsyncIterator[ProductCatalogService]:
    service = ProductCatalogService(product_repository())
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
    tmp_path: Path, client: TestClient, repository: PostgresProductRepository
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
    tmp_path: Path, client: TestClient, repository: PostgresProductRepository
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
        "qa_problem": "",
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
    assert client.get(url).json() == {"exists": False, "voiceover": False, "voice_id": ""}
    video = tmp_path / "media" / "videos" / PRODUCT_ID / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    assert client.get(url).json() == {"exists": True, "voiceover": False, "voice_id": ""}
    (video.parent / "voiceover.mp3").write_bytes(b"v")
    (video.parent / "voiceover.json").write_text('{"voice_id": "tiendat.mp3"}', encoding="utf-8")
    assert client.get(url).json() == {"exists": True, "voiceover": True, "voice_id": "tiendat.mp3"}


def test_people_are_created_given_photos_made_default_and_removed(client: TestClient) -> None:
    base = "/api/v1/products/persona"
    jpeg = {"content-type": "image/jpeg"}
    assert client.get(base).json() == []
    assert client.post(base, json={"name": ""}).status_code == 422
    dat = client.post(base, json={"name": "Đạt"}).json()
    lan = client.post(base, json={"name": "Lan"}).json()
    one = f"{base}/{dat['id']}/image"
    assert client.get(one).status_code == 404

    assert client.put(one, content=b"one", headers=jpeg).status_code == 422
    confirmed = f"{one}?rights=confirmed"
    assert client.put(confirmed, content=b"", headers=jpeg).status_code == 422
    assert (
        client.put(confirmed, content=b"x", headers={"content-type": "text/plain"}).status_code
        == 415
    )
    assert client.put(f"{base}/nobody/image?rights=confirmed", content=b"x", headers=jpeg).status_code == 404
    assert client.put(confirmed, content=b"one", headers=jpeg).json()["attempts"] == 1
    assert client.put(f"{confirmed}&add=true", content=b"two", headers=jpeg).status_code == 200
    assert client.get(one).content == b"one"
    assert client.get(f"{one}?n=1").content == b"two"
    assert client.get(f"{one}?n=2").status_code == 404

    listed = client.get(base).json()
    assert [(p["name"], p["photos"], p["default"]) for p in listed] == [
        ("Đạt", 2, True),
        ("Lan", 0, False),
    ]
    made = client.put(f"{base}/{lan['id']}/default").json()
    assert [p["default"] for p in made] == [False, True]
    assert client.put(f"{base}/nobody/default").status_code == 404

    left = client.delete(f"{base}/{lan['id']}").json()  # the default moves on
    assert [(p["name"], p["default"]) for p in left] == [("Đạt", True)]
    assert client.delete(f"{base}/{lan['id']}").status_code == 404


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
    tmp_path: Path, client: TestClient, repository: PostgresProductRepository
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
        "with_person": True,
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
    assert output["persona"] == {"photos": 0}
    first, second = output["shots"]
    assert (first["has_keyframe"], first["keyframe_attempts"], first["in_video"]) == (True, 3, True)
    assert (second["delivery"], second["in_video"]) == ("narrated", False)
    assert output["video"]["voice"] == "Kim Oanh" and output["video"]["exists"] is True


def test_starting_over_removes_what_was_made_and_keeps_the_product(
    tmp_path: Path,
    client: TestClient,
    repository: PostgresProductRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = f"/api/v1/products/{PRODUCT_ID}"
    assert client.delete(f"{base}/brief").status_code == 404
    _capture_product(client)
    asyncio.run(repository.save_brief(PRODUCT_ID, "", {"shots": [{"role": "hook"}]}, "approved"))
    folder = tmp_path / "media" / "keyframes" / PRODUCT_ID
    folder.mkdir(parents=True)
    (folder / "shot_0.jpg").write_bytes(b"jpeg")
    asyncio.run(
        repository.save_keyframe(
            {
                "product_id": PRODUCT_ID,
                "shot_index": 0,
                "status": "approved",
                "prompt": "p",
                "image_path": f"keyframes/{PRODUCT_ID}/shot_0.jpg",
                "attempts": 1,
                "error": None,
                "qa_problem": "",
            }
        )
    )
    run = {"status": "running", "step": "", "message": ""}
    monkeypatch.setitem(products_api._pipeline_runs, PRODUCT_ID, run)
    assert client.delete(f"{base}/brief").status_code == 409
    monkeypatch.delitem(products_api._pipeline_runs, PRODUCT_ID)
    ended = {"status": "paused", "step": "", "message": "Review the images"}
    products_api._pipeline_runs[PRODUCT_ID] = ended

    assert client.delete(f"{base}/brief").json() == {"deleted": True}
    assert client.get(f"{base}/pipeline").json()["status"] == "idle"
    assert client.get(f"{base}/brief").status_code == 404
    assert client.get(f"{base}/keyframes").json() == []
    assert not folder.exists()
    assert client.get(base).json()["title"] == "Áo thun"


async def test_the_end_of_a_run_is_announced_with_a_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[Notification] = []

    class _Notifications:
        async def save(self, notification: Notification) -> None:
            saved.append(notification)

    runs: list[tuple[str, str]] = []

    class _Service:
        async def detail(self, product_id: str) -> dict:
            return {"title": "Sọt lưới"}

        async def save_run(self, product_id: str, status: str, message: str = "") -> None:
            runs.append((status, message))

    @asynccontextmanager
    async def notifications():
        yield _Notifications()

    @asynccontextmanager
    async def scope():
        yield _Service()

    async def finished(*args, **kwargs) -> None:
        return None

    async def stopped(*args, **kwargs) -> None:
        raise PipelineStopped("Review the images")

    for outcome, until, kind, title in (
        (finished, "script", "pipeline_done", "The script is ready to read"),
        (stopped, "video", "pipeline_paused", "The video needs a look"),
    ):
        monkeypatch.setattr(products_api, "run_pipeline", outcome)
        run = {"status": "running", "step": "", "message": ""}
        monkeypatch.setitem(products_api._pipeline_runs, PRODUCT_ID, run)
        request = products_api.PipelineRequest(until=until)
        await products_api._run_pipeline(scope, PRODUCT_ID, request, tmp_path, notifications)
        note = saved[-1]
        assert (note.kind, note.title) == (kind, title)
        assert note.action_path == f"/studio/{PRODUCT_ID}" and "Sọt lưới" in note.detail
    assert "Review the images" in saved[-1].detail
    assert runs == [("done", ""), ("paused", "Review the images")]


def test_how_a_run_ended_survives_a_restart(
    client: TestClient, repository: PostgresProductRepository
) -> None:
    url = f"/api/v1/products/{PRODUCT_ID}/pipeline"
    assert client.get(url).json()["status"] == "idle"
    asyncio.run(repository.save_run(PRODUCT_ID, "running", ""))
    assert asyncio.run(repository.interrupt_runs()) == 1
    interrupted = client.get(url).json()
    assert interrupted["status"] == "interrupted" and "restarted" in interrupted["message"]
    asyncio.run(repository.save_run(PRODUCT_ID, "paused", "Review the images"))
    assert asyncio.run(repository.interrupt_runs()) == 0
    assert client.get(url).json() == {"status": "paused", "step": "", "message": "Review the images"}
    asyncio.run(repository.clear_work(PRODUCT_ID))
    assert client.get(url).json()["status"] == "idle"
