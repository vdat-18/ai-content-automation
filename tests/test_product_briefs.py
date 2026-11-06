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
    # every photo is tried and one is gone: the model sees the other ten
    assert client.seen == [(10, ["ref_1", "ref_2"])]
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
    assert brief["product_photo_urls"] == [f"https://x/p{i}.jpg" for i in range(1, 9)]


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


class _Shortlist:
    def __init__(self, keep_per_call: int = 2) -> None:
        self.calls: list[list[str]] = []
        self.keep_per_call = keep_per_call

    async def ShortlistReferences(self, product_json, user_idea, references, keep):
        labels = [reference.label for reference in references]
        self.calls.append(labels)
        return SimpleNamespace(labels=[*labels[-keep:], "ref_999"])


async def test_shortlist_narrows_any_number_of_references_in_rounds() -> None:
    from ai_content.domains.marketing.products.briefing import ReferenceShortlister

    client = _Shortlist()
    images = [{"image_id": f"id-{i}"} for i in range(50)]
    chosen = await ReferenceShortlister(client).shortlist({}, "", images, keep=3, batch=10)
    # batches of at most ten are read, round after round, until three are left
    assert max(len(call) for call in client.calls) == 10 and len(client.calls) > 5
    assert len(chosen) == 3
    assert {image["image_id"] for image in chosen} <= {f"id-{i}" for i in range(50)}


async def test_shortlist_keeps_the_newest_when_the_model_fails() -> None:
    from ai_content.domains.marketing.products.briefing import ReferenceShortlister

    class Broken:
        async def ShortlistReferences(self, *args):
            raise BamlClientError("503", "503", "503")

    images = [{"image_id": f"id-{i}"} for i in range(30)]
    chosen = await ReferenceShortlister(Broken()).shortlist({}, "", images, keep=4, batch=10)
    assert len(chosen) == 4


async def test_brief_reads_the_shortlist_not_every_reference(tmp_path) -> None:
    from ai_content.domains.marketing.products.briefing import ReferenceShortlister

    writer = _CapturingWriter()
    service = await _service(tmp_path, writer)
    service._shortlister = ReferenceShortlister(_Shortlist())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    pins = [
        {
            "image_url": f"https://i.pinimg.com/236x/aa/bb/{i}.jpg",
            "pin_url": f"/pin/{i}/",
            "title": "",
        }
        for i in range(30)
    ]
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins}
    )
    for image in await service.reference_images("pending", "áo thun"):
        await service._repository.set_image_screening(image["image_id"], {"usable": True}, "live")
    await service.create_brief(PRODUCT_ID)
    assert 0 < len(writer.references) <= 12


def test_reference_note_prefers_the_description() -> None:
    from ai_content.domains.marketing.products.briefing import _note

    assert _note({"screening": {"description": "d", "scene_description": "old"}}) == "d"
    assert _note({"screening": {"scene_description": "old", "placement_note": "p"}}) == "old p"
    assert _note({}) == ""


async def test_video_length_sets_the_shot_count_from_the_finished_length(
    tmp_path, monkeypatch
) -> None:
    # a 15 second clip is trimmed and sped up, so it plays for about 11.8 seconds
    monkeypatch.setenv("AIC_CLIP_SPEED", "1.25")
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
    assert seen == [1, 5, 8]
    with pytest.raises(BriefUnavailable, match="Video length"):
        await service.create_brief(PRODUCT_ID, video_seconds=20)


async def test_brief_is_rewritten_until_it_has_the_requested_number_of_shots(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("AIC_CLIP_SPEED", "1.25")  # 30 seconds is 3 shots
    counts = [1, 1, 3]

    class _Wrong(_FakeWriter):
        async def write(self, product, user_idea, references, shot_count=1):
            return {"title": "T", "shots": [{}] * counts.pop(0)}

    service = await _service(tmp_path, _Wrong())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert record is not None and len(record["brief"]["shots"]) == 3 and counts == []

    counts[:] = [4, 4, 4]
    with pytest.raises(BriefGenerationError, match="4 shots instead of 3"):
        await service.create_brief(PRODUCT_ID, video_seconds=30)
