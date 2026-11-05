from types import SimpleNamespace

import httpx
import pytest
from baml_py.baml_py import BamlClientError

from ai_content.domains.marketing.products.briefing import (
    BriefGenerationError,
    BriefUnavailable,
    ContentBriefWriter,
    product_facts,
)
from ai_content.domains.marketing.products.references import ProfileGenerationError
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService

PRODUCT_ID = "1730000000000000001"
URL = f"https://shop.tiktok.com/vn/pdp/ao-thun/{PRODUCT_ID}"
HTML = (
    '<script>"product_info":{"status":1,"product_id":"1730000000000000001",'
    '"title":"Áo thun","price":{"min_sku_price":"99000","currency":"VND"},'
    '"images":[{"url_list":["https://img.example/1.jpg"]}],'
    '"specifications":[{"name":"Chất liệu","value":"Cotton"}]}</script>'
)
PIN = {"image_url": "https://i.pinimg.com/236x/ab/cd/ef.jpg", "pin_url": "/pin/1/", "title": "a"}


class _FakeWriter:
    async def write(self, product, user_idea, references, shot_count=1):
        return {
            "title": "Brief",
            "scene": "Phòng giặt",
            "selected_reference_ids": [references[0]["image_id"]],
        }


async def _service(tmp_path, writer=None) -> ProductCatalogService:
    repository = SqliteProductRepository(tmp_path / "b.db")
    service = ProductCatalogService(repository, briefer=writer)
    await service.ingest({"kind": "page", "url": URL, "html": HTML})
    return service


async def _make_reference_live(service: ProductCatalogService) -> str:
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": [PIN]}
    )
    [image] = await service.reference_images("pending", "áo thun")
    await service.set_image_status(image["image_id"], "live")
    return image["image_id"]


async def test_brief_needs_selection_and_live_references(tmp_path) -> None:
    service = await _service(tmp_path, _FakeWriter())
    assert await service.create_brief("missing") is None
    with pytest.raises(BriefUnavailable, match="Select this product"):
        await service.create_brief(PRODUCT_ID)

    await service._repository.select_product(PRODUCT_ID, "áo thun")
    with pytest.raises(BriefUnavailable, match="No usable reference image"):
        await service.create_brief(PRODUCT_ID)

    image_id = await _make_reference_live(service)
    record = await service.create_brief(PRODUCT_ID, "  ý tưởng của tôi ")
    assert record is not None
    assert (record["status"], record["user_idea"]) == ("draft", "ý tưởng của tôi")
    assert record["brief"]["selected_reference_ids"] == [image_id]


async def test_brief_without_llm_reports_configuration_error(tmp_path) -> None:
    service = await _service(tmp_path)
    with pytest.raises(ProfileGenerationError, match="not configured"):
        await service.create_brief(PRODUCT_ID)


async def test_brief_edits_keep_known_fields_and_can_be_approved(tmp_path) -> None:
    service = await _service(tmp_path, _FakeWriter())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    await service.create_brief(PRODUCT_ID)

    updated = await service.update_brief(
        PRODUCT_ID, {"scene": "Ban công", "unknown": "x"}, "approved"
    )
    assert updated is not None and updated["status"] == "approved"
    assert updated["brief"]["scene"] == "Ban công" and "unknown" not in updated["brief"]
    assert [b["product_id"] for b in await service.list_briefs()] == [PRODUCT_ID]
    assert await service.update_brief("missing", {}, "draft") is None


class _FakeBamlClient:
    def __init__(self, fail: bool = False, numbers: list[int] | None = None) -> None:
        self.fail = fail
        self.numbers = numbers if numbers is not None else [2, 2, 1, 40]
        self.seen: list[tuple[int, list[str]]] = []

    async def DraftContentBrief(
        self, product_json, user_idea, shot_count, product_images, references
    ):
        if self.fail:
            raise BamlClientError("503", "503", "503")
        self.seen.append((len(product_images), [ref.label for ref in references]))
        return SimpleNamespace(
            model_dump=lambda: {
                "title": "T",
                "selected_reference_labels": ["ref_2", "ref_1", "ref_9"],
                "product_photo_numbers": list(self.numbers),
            }
        )


def _photo_server(request: httpx.Request) -> httpx.Response:
    if "gone" in request.url.path:
        return httpx.Response(404)
    return httpx.Response(200, content=b"img", headers={"content-type": "image/png"})


async def test_writer_picks_one_scene_and_maps_photo_numbers_to_urls() -> None:
    references = [
        {"image_id": "id-1", "image_url": "https://x/a.jpg"},
        {"image_id": "id-2", "image_url": "https://x/b.jpg", "screening": {"description": "s"}},
    ]
    product = {
        "images": ["https://x/p1.jpg", "https://x/gone-p.jpg"]
        + [f"https://x/p{i}.jpg" for i in range(3, 12)]
    }
    client = _FakeBamlClient()
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        brief = await ContentBriefWriter(client).write(product, "", references, http)
    # only the first nine photos are tried and one is gone: the model sees eight of them
    assert client.seen == [(8, ["ref_1", "ref_2"])]
    # the first label wins and the others are dropped; the reference images are never downloaded
    assert brief["selected_reference_ids"] == ["id-2"]
    assert "selected_reference_labels" not in brief and "product_photo_numbers" not in brief
    # numbers count the photos the model saw: 2 is p3 because p2 is gone; repeats and 40 are dropped
    assert brief["product_photo_urls"] == ["https://x/p3.jpg", "https://x/p1.jpg"]


async def test_writer_uses_the_first_photos_when_the_model_picks_none() -> None:
    product = {"images": [f"https://x/p{i}.jpg" for i in range(1, 9)]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        brief = await ContentBriefWriter(_FakeBamlClient(numbers=[])).write(
            product, "", [{"image_id": "a"}], http
        )
    assert brief["product_photo_urls"] == [f"https://x/p{i}.jpg" for i in range(1, 6)]


async def test_writer_errors() -> None:
    reference = [{"image_id": "a"}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        with pytest.raises(BriefGenerationError, match="could be downloaded"):
            await ContentBriefWriter(_FakeBamlClient()).write(
                {"images": ["https://x/gone.jpg"]}, "", reference, http
            )
        with pytest.raises(BriefGenerationError):
            await ContentBriefWriter(_FakeBamlClient(fail=True)).write(
                {"images": ["https://x/ok.jpg"]}, "", reference, http
            )


def test_product_facts_are_compact() -> None:
    facts = product_facts(
        {
            "title": "T",
            "price": {"sale": "99000"},
            "specifications": {str(i): i for i in range(40)},
            "variants": [{"variant": f"v{i}"} for i in range(30)],
            "description": "d" * 5000,
        }
    )
    assert facts["price_vnd"] == "99000"
    assert len(facts["specifications"]) == 20 and len(facts["variants"]) == 10
    assert len(facts["description"]) == 3000


class _CapturingWriter:
    def __init__(self) -> None:
        self.references: list[dict] = []

    async def write(self, product, user_idea, references, shot_count=1):
        self.references = references
        return {"title": "T", "selected_reference_ids": []}


async def test_brief_uses_varied_live_references(tmp_path) -> None:
    writer = _CapturingWriter()
    service = await _service(tmp_path, writer)
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    pins = [
        {
            "image_url": f"https://i.pinimg.com/236x/aa/bb/{i}.jpg",
            "pin_url": f"/pin/{i}/",
            "title": "",
        }
        for i in range(12)
    ]
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins}
    )
    images = await service.reference_images("pending", "áo thun")
    for index, image in enumerate(images):
        await service._repository.set_image_screening(image["image_id"], {"usable": True}, "live")
        cluster = index % 4  # four groups of three near-identical vectors
        vector = [0.0] * 4
        vector[cluster] = 1.0
        await service._repository.set_fingerprint(image["image_id"], f"{index:016x}", vector)
    await service.create_brief(PRODUCT_ID)
    clusters = {
        index % 4
        for index, image in enumerate(images)
        if image["image_id"] in {r["image_id"] for r in writer.references}
    }
    assert len(writer.references) == 8 and clusters == {0, 1, 2, 3}
    assert all("embedding" not in r for r in writer.references)


def test_reference_note_prefers_the_description() -> None:
    from ai_content.domains.marketing.products.briefing import _note

    assert _note({"screening": {"description": "d", "scene_description": "old"}}) == "d"
    assert _note({"screening": {"scene_description": "old", "placement_note": "p"}}) == "old p"
    assert _note({}) == ""


async def test_video_length_sets_the_shot_count_in_whole_clips(tmp_path) -> None:
    seen: list[int] = []

    class _Counting(_FakeWriter):
        async def write(self, product, user_idea, references, shot_count=1):
            seen.append(shot_count)
            return await super().write(product, user_idea, references)

    service = await _service(tmp_path, _Counting())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    await service.create_brief(PRODUCT_ID)
    await service.create_brief(PRODUCT_ID, video_seconds=60)
    await service.create_brief(PRODUCT_ID, video_seconds=90)
    assert seen == [1, 4, 6]
    with pytest.raises(BriefUnavailable, match="Video length"):
        await service.create_brief(PRODUCT_ID, video_seconds=20)


async def test_brief_is_rewritten_until_it_has_the_requested_number_of_shots(tmp_path) -> None:
    counts = [1, 1, 2]

    class _Wrong(_FakeWriter):
        async def write(self, product, user_idea, references, shot_count=1):
            return {"title": "T", "shots": [{}] * counts.pop(0)}

    service = await _service(tmp_path, _Wrong())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert record is not None and len(record["brief"]["shots"]) == 2 and counts == []

    counts[:] = [3, 3, 3]
    with pytest.raises(BriefGenerationError, match="3 shots instead of 2"):
        await service.create_brief(PRODUCT_ID, video_seconds=30)
