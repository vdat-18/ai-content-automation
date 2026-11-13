from types import SimpleNamespace

import httpx
import pytest
from baml_py.baml_py import BamlClientError

from ai_content.domains.marketing.products import service as service_module
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
    async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
        return {
            "title": "Brief",
            "scene": "Phòng giặt",
            "shots": [{"role": "hook", "keyframe_prompt": "a hand applies lotion"}] * shot_count,
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

    await _make_reference_live(service)
    record = await service.create_brief(PRODUCT_ID, "  ý tưởng của tôi ")
    assert record is not None
    assert (record["status"], record["user_idea"]) == ("draft", "ý tưởng của tôi")
    assert record["brief"]["selected_reference_ids"] == []  # no embedding model is set up


async def test_every_product_draws_from_the_same_references(tmp_path) -> None:
    service = await _service(tmp_path, _FakeWriter())
    await service._repository.select_product(PRODUCT_ID, "nước tẩy")
    with pytest.raises(BriefUnavailable, match="No usable reference image"):
        await service.create_brief(PRODUCT_ID)

    other = {"image_url": "https://i.pinimg.com/236x/12/34/56.jpg", "pin_url": "/pin/2/", "title": "b"}
    for product_type, pin in (("áo thun", PIN), ("giày", other)):
        await service.ingest({"kind": "pinterest", "product_type": product_type, "query": "q", "pins": [pin]})
        [image] = await service.reference_images("pending", product_type)
        await service.set_image_status(image["image_id"], "live")
    assert await service.create_brief(PRODUCT_ID) is not None  # it has no references of its own type
    assert len(await service._scene_pool()) == 2


async def test_brief_records_whether_it_has_a_person(tmp_path) -> None:
    service = await _service(tmp_path, _FakeWriter())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    with_person = await service.create_brief(PRODUCT_ID, person_photos=[b"face"])
    assert with_person is not None and with_person["brief"]["with_person"] is True
    without = await service.create_brief(PRODUCT_ID)
    assert without is not None and without["brief"]["with_person"] is False


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
        self.people: list[tuple[bool, int]] = []

    async def DraftContentBrief(
        self, product_json, user_idea, shot_count, product_images, with_person, person_images, rules
    ):
        if self.fail:
            raise BamlClientError("503", "503", "503")
        self.seen.append(len(product_images))
        self.people.append((with_person, len(person_images)))
        return SimpleNamespace(
            model_dump=lambda: {
                "title": "T",
                "product_photo_numbers": list(self.numbers),
            }
        )


def _photo_server(request: httpx.Request) -> httpx.Response:
    if "gone" in request.url.path:
        return httpx.Response(404)
    return httpx.Response(200, content=b"img", headers={"content-type": "image/png"})


async def test_writer_maps_photo_numbers_to_urls() -> None:
    product = {
        "images": ["https://x/p1.jpg", "https://x/gone-p.jpg"]
        + [f"https://x/p{i}.jpg" for i in range(3, 12)]
    }
    client = _FakeBamlClient()
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        brief = await ContentBriefWriter(client).write(product, "", http)
    # every photo is tried and one is gone: the model sees the other ten
    assert client.seen == [10]
    assert "product_photo_numbers" not in brief and "selected_reference_ids" not in brief
    # numbers count the photos the model saw: 2 is p3 because p2 is gone; repeats and 40 are dropped
    assert brief["product_photo_urls"] == ["https://x/p3.jpg", "https://x/p1.jpg"]


async def test_the_writer_gives_the_model_the_photos_of_the_person() -> None:
    client = _FakeBamlClient()
    product = {"images": ["https://x/p1.jpg"]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        await ContentBriefWriter(client).write(product, "", http, person_photos=[b"a", b"b"])
        await ContentBriefWriter(client).write(product, "", http)
    assert client.people == [(True, 2), (False, 0)]


async def test_writer_uses_all_photos_when_the_model_picks_none() -> None:
    product = {"images": [f"https://x/p{i}.jpg" for i in range(1, 9)]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        brief = await ContentBriefWriter(_FakeBamlClient(numbers=[])).write(product, "", http)
    assert brief["product_photo_urls"] == [f"https://x/p{i}.jpg" for i in range(1, 9)]


async def test_writer_errors() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_photo_server)) as http:
        with pytest.raises(BriefGenerationError, match="could be downloaded"):
            await ContentBriefWriter(_FakeBamlClient()).write(
                {"images": ["https://x/gone.jpg"]}, "", http
            )
        with pytest.raises(BriefGenerationError):
            await ContentBriefWriter(_FakeBamlClient(fail=True)).write(
                {"images": ["https://x/ok.jpg"]}, "", http
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


class _TwoShots:
    async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
        prompts = ["a hand applies lotion", "sitting in a room", "standing in a room"]
        shots = [{"role": "demo", "keyframe_prompt": prompts[i % 3]} for i in range(shot_count)]
        return {"title": "T", "shots": shots}


class _Embedder:
    model = "m1"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0] if "hand" in text else [0.0, 1.0] for text in texts]


class _Picker:
    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    async def choose(self, product, shot, candidates):
        self.seen.append([item["image_id"] for item in candidates])
        return candidates[0]["image_id"] if candidates else None


async def _two_described_references(service: ProductCatalogService) -> dict[str, str]:
    pins = [
        {"image_url": "https://i.pinimg.com/236x/aa/bb/1.jpg", "pin_url": "/pin/1/", "title": ""},
        {"image_url": "https://i.pinimg.com/236x/aa/bb/2.jpg", "pin_url": "/pin/2/", "title": ""},
    ]
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": pins}
    )
    found: dict[str, str] = {}
    for image, text in zip(
        await service.reference_images("pending", "áo thun"),
        ("a hand holding a bottle", "a person in a bedroom"),
        strict=True,
    ):
        review = {"usable": True, "description": text}
        await service._repository.set_image_screening(image["image_id"], review, "live")
        found[text] = image["image_id"]
    return found


async def test_each_shot_gets_the_reference_that_fits_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIC_CLIP_SPEED", "1.25")  # 30 seconds is 3 shots
    service = await _service(tmp_path, _TwoShots())
    embedder, picker = _Embedder(), _Picker()
    service._text_embedder, service._reference_picker = embedder, picker
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    ids = await _two_described_references(service)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    brief = record["brief"]
    # the closest description comes first: the hand shot sees the hand picture first
    hand, room = ids["a hand holding a bottle"], ids["a person in a bedroom"]
    assert brief["shot_references"] == [hand, room, None]  # the third shot would repeat the room
    assert brief["selected_reference_ids"] == [hand, room]
    # the descriptions were embedded once, then only the shots; a second brief reuses them
    assert [len(call) for call in embedder.calls] == [2, 3]
    await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert [len(call) for call in embedder.calls] == [2, 3, 3]


class _SameTextEmbedder(_Embedder):
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _ProductLookEmbedder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def embed_many(self, images):
        if self.fail:
            raise RuntimeError("model missing")
        return [[1.0, 0.0] for _ in images]


async def _look_service(tmp_path, monkeypatch, fail: bool = False):
    async def photos(urls, http=None):
        return [b"photo" for _ in urls]

    monkeypatch.setattr(service_module, "fetch_images", photos)
    service = await _service(tmp_path, _TwoShots())
    picker = _Picker()
    service._text_embedder, service._reference_picker = _SameTextEmbedder(), picker
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    ids = await _two_described_references(service)
    service._embedder = _ProductLookEmbedder(fail)
    hand, room = ids["a hand holding a bottle"], ids["a person in a bedroom"]
    await service._repository.set_fingerprint(hand, "0" * 16, [0.0, 1.0])
    await service._repository.set_fingerprint(room, "0" * 16, [1.0, 0.0])
    return service, picker, hand, room


async def test_references_that_look_like_the_product_photos_rank_first(
    tmp_path, monkeypatch
) -> None:
    service, picker, hand, room = await _look_service(tmp_path, monkeypatch)
    await service.create_brief(PRODUCT_ID, video_seconds=30)
    # the texts tie, so the picture that looks like the product (the room) comes first
    assert picker.seen[0] == [room, hand]


async def test_references_fall_back_to_text_when_the_product_cannot_be_embedded(
    tmp_path, monkeypatch
) -> None:
    service, picker, hand, room = await _look_service(tmp_path, monkeypatch, fail=True)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert record is not None and picker.seen[0] == [hand, room]


async def test_a_reference_is_not_used_for_two_shots(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIC_CLIP_SPEED", "1.25")  # 30 seconds is 3 shots
    class _SameShots(_TwoShots):
        async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
            brief = await super().write(product, user_idea, shot_count, person_photos)
            for shot in brief["shots"]:
                shot["keyframe_prompt"] = "a hand pours lotion"
            return brief

    service = await _service(tmp_path, _SameShots())
    service._text_embedder, service._reference_picker = _Embedder(), _Picker()
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    ids = await _two_described_references(service)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert record["brief"]["shot_references"] == [ids["a hand holding a bottle"], None, None]


async def test_shots_have_no_reference_without_an_embedding_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIC_CLIP_SPEED", "1.25")  # 30 seconds is 3 shots
    service = await _service(tmp_path, _TwoShots())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _two_described_references(service)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert record["brief"]["shot_references"] == [None, None, None]
    assert record["brief"]["selected_reference_ids"] == []


async def test_text_embedder_sends_batches_and_orders_the_vectors() -> None:
    import json as jsonlib

    from ai_content.domains.marketing.products.text_embedding import (
        TextEmbedder,
        TextEmbeddingError,
    )

    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content)
        sizes.append(len(body["input"]))
        rows = [{"index": i, "embedding": [float(len(t))]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": rows[::-1]})

    embedder = TextEmbedder("https://x/v1", "k", "m")
    original = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: original(transport=httpx.MockTransport(handler), **kw)  # type: ignore[assignment,misc]
    try:
        vectors = await embedder.embed(["a" * n for n in range(1, 71)])
        assert sizes == [64, 6] and vectors[0] == [1.0] and vectors[69] == [70.0]
        httpx.AsyncClient = lambda **kw: original(  # type: ignore[assignment,misc]
            transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw
        )
        with pytest.raises(TextEmbeddingError):
            await embedder.embed(["x"])
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]


def test_reference_note_prefers_the_description() -> None:
    from ai_content.domains.marketing.products.briefing import reference_note

    assert reference_note({"screening": {"description": "d", "scene_description": "old"}}) == "d"
    assert (
        reference_note({"screening": {"scene_description": "old", "placement_note": "p"}})
        == "old p"
    )
    assert reference_note({}) == ""


async def test_video_length_sets_the_shot_count_from_the_finished_length(
    tmp_path, monkeypatch
) -> None:
    # a 15 second clip is trimmed and sped up, so it plays for about 11.8 seconds
    monkeypatch.setenv("AIC_CLIP_SPEED", "1.25")
    seen: list[int] = []

    class _Counting(_FakeWriter):
        async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
            seen.append(shot_count)
            return await super().write(product, user_idea, shot_count, person_photos)

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
        async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
            return {"title": "T", "shots": [{}] * counts.pop(0)}

    service = await _service(tmp_path, _Wrong())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert record is not None and len(record["brief"]["shots"]) == 3 and counts == []

    counts[:] = [4, 4, 4]
    with pytest.raises(BriefGenerationError, match="4 shots instead of 3"):
        await service.create_brief(PRODUCT_ID, video_seconds=30)


async def test_editing_the_script_flags_what_was_already_made_from_it(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "s.db")
    service = ProductCatalogService(repository)
    shots = [
        {"keyframe_prompt": "a", "motion_prompt": "m", "voiceover": "hello", "delivery": "talking"},
        {"keyframe_prompt": "b", "motion_prompt": "n", "voiceover": "world", "delivery": "narrated"},
    ]
    await repository.save_brief("42", "", {"title": "t", "shots": shots}, "approved")
    for index in range(2):
        await repository.save_keyframe(
            {
                "product_id": "42",
                "shot_index": index,
                "status": "approved",
                "prompt": "p",
                "image_path": f"k{index}.jpg",
                "attempts": 1,
                "error": None,
                "qa_problem": "",
            }
        )
        await repository.save_clip(
            {
                "product_id": "42",
                "shot_index": index,
                "status": "ready",
                "job_id": "j",
                "job_model": "m",
                "video_path": f"c{index}.mp4",
                "seconds": 15,
                "attempts": 1,
                "error": None,
                "qa_problem": "",
            }
        )
    edited = [
        {**shots[0], "voiceover": "hello there", "keyframe_prompt": "a  "},  # words only: its clip
        {**shots[1], "voiceover": "a new line"},  # a narrated line is read later: nothing to flag
    ]
    await service.update_brief("42", {"shots": edited}, "approved")
    keyframes = await repository.list_keyframes("42")
    clips = await repository.list_clips("42")
    assert [k["qa_problem"] for k in keyframes] == ["", ""]
    assert [c["qa_problem"] for c in clips] == ["The script of this scene changed after it was filmed", ""]

    moved = [{**edited[0], "keyframe_prompt": "another picture"}, edited[1]]
    await service.update_brief("42", {"shots": moved}, "approved")
    first = (await repository.list_keyframes("42"))[0]
    assert first["status"] == "ready" and "image was made" in first["qa_problem"]
    assert (await repository.list_keyframes("42"))[1]["status"] == "approved"


async def test_the_run_log_says_when_no_reference_has_been_described(tmp_path) -> None:
    service = await _service(tmp_path, _TwoShots())
    service._text_embedder, service._reference_picker = _Embedder(), _Picker()
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)  # live, but the review left no description on it
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert set(record["brief"]["shot_references"]) == {None}
    last = [e for e in await service.events(PRODUCT_ID) if e["step"] == "references"][-1]
    assert last["status"] == "warning" and "has a description yet" in last["message"]
