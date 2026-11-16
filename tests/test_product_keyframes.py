import asyncio
import base64
import io
import json
import re

import httpx
import pytest
from PIL import Image
from tests.pgstore import product_repository, usage_repository

from ai_content.domains.marketing.products import keyframes as keyframes_module
from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.keyframe_check import QAProblem
from ai_content.domains.marketing.products.keyframes import (
    KeyframeGenerationError,
    KeyframeGenerator,
    KeyframeImageClient,
    _to_vertical,
)
from ai_content.domains.marketing.products.service import (
    NOT_CHECKED,
    KeyframeUnavailable,
    ProductCatalogService,
)

PRODUCT_ID = "1730000000000000001"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
SHOTS = [
    {"role": "hook", "keyframe_prompt": "master shot"},
    {"role": "demo", "keyframe_prompt": "close up"},
    {"role": "call_to_action", "keyframe_prompt": "final"},
]


class _FakeKeyframer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail = fail

    async def master(self, shot, photos, scene, fix="", persona=None):
        self.calls.append(("master", len(photos), fix))
        if self.fail:
            raise KeyframeGenerationError("HTTP 503")
        return PNG + b"master"

    async def follow_up(self, shot, master, photos, fix="", persona=None, reference=None):
        self.calls.append(("follow_up", len(photos), fix))
        assert master == PNG + b"master"
        return PNG + b"follow"


@pytest.fixture(autouse=True)
def fake_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch_images(urls, http=None):
        return [b"photo-" + url.encode() for url in urls]

    monkeypatch.setattr(service_module, "fetch_images", fetch_images)


async def _service(tmp_path, keyframer, shots=SHOTS) -> ProductCatalogService:
    repository = product_repository()
    service = ProductCatalogService(repository, keyframer=keyframer)
    await repository.upsert_detail(
        {
            "product_id": PRODUCT_ID,
            "title": "Giỏ",
            "images": ["https://img.example/1.jpg", "https://img.example/2.jpg"],
        }
    )
    await repository.save_brief(PRODUCT_ID, "", {"title": "b", "shots": shots}, "approved")
    return service


async def test_master_comes_first_then_other_shots_after_approval(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)

    first = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert [(k["shot_index"], k["status"]) for k in first] == [(0, "ready")]
    assert (tmp_path / "keyframes" / PRODUCT_ID / "shot_0.jpg").read_bytes() == PNG + b"master"

    with pytest.raises(KeyframeUnavailable, match="Approve the master"):
        await service.generate_keyframes(PRODUCT_ID, tmp_path, shot_index=1)

    assert await service.set_keyframe_status(PRODUCT_ID, 0, "approved")
    rest = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert [(k["shot_index"], k["status"]) for k in rest] == [
        (0, "approved"),
        (1, "ready"),
        (2, "ready"),
    ]
    assert keyframer.calls == [("master", 2, ""), ("follow_up", 2, ""), ("follow_up", 2, "")]


async def test_keyframes_use_the_photos_the_brief_picked(tmp_path) -> None:
    urls = [f"https://img.example/{i}.jpg" for i in range(1, 9)]
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    await service._repository.upsert_detail(
        {"product_id": PRODUCT_ID, "title": "Giỏ", "images": urls}
    )
    # no pick yet: the first photos of the product, but only three of them reach the model
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.calls[-1][1] == 3
    brief = {"title": "b", "shots": SHOTS, "product_photo_urls": [urls[6], urls[1], urls[3]]}
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path, shot_index=0)
    assert keyframer.calls[-1][1] == 3


async def test_failed_generation_is_recorded_and_attempts_count_up(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer(fail=True))
    [failed] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert (failed["status"], failed["error"], failed["attempts"]) == ("failed", "HTTP 503", 1)
    [again] = await service.generate_keyframes(PRODUCT_ID, tmp_path, shot_index=0)
    assert again["attempts"] == 2


async def test_preconditions_are_reported(tmp_path) -> None:
    service = await _service(tmp_path, None)
    with pytest.raises(KeyframeUnavailable, match="not configured"):
        await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert await service.generate_keyframes("missing", tmp_path) is None

    empty = await _service(tmp_path, _FakeKeyframer(), shots=[])
    with pytest.raises(KeyframeUnavailable, match="no storyboard"):
        await empty.generate_keyframes(PRODUCT_ID, tmp_path)

    with pytest.raises(KeyframeUnavailable, match="does not exist"):
        await (await _service(tmp_path, _FakeKeyframer())).generate_keyframes(
            PRODUCT_ID, tmp_path, shot_index=9
        )


async def test_review_status_must_be_known(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer())
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    with pytest.raises(ValueError, match="status must be one of"):
        await service.set_keyframe_status(PRODUCT_ID, 0, "published")
    assert not await service.set_keyframe_status(PRODUCT_ID, 7, "approved")


def _client(handler) -> KeyframeImageClient:
    return KeyframeImageClient(
        base_url="https://api.example/v1",
        api_key="k",
        model="m",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_delay=0,
    )


async def test_client_follows_image_link_sends_size_and_all_images() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=PNG)
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "![x](https://cdn.example/a.jpg)"}}]},
        )

    image = await _client(handler).generate("prompt", [b"one", b"two"])
    assert image == PNG
    assert seen["size"] == "1024x1792"
    parts = seen["messages"][0]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]


async def test_client_edits_mode_posts_images_to_the_edits_endpoint() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=PNG)
        seen["path"] = request.url.path
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example/a.jpeg"}]})

    client = KeyframeImageClient(
        base_url="https://api.example/v1",
        api_key="k",
        model="m",
        api="edits",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_delay=0,
    )
    assert await client.generate("prompt", [b"one", b"two"]) == PNG
    assert seen["path"] == "/v1/images/edits"
    assert (seen["prompt"], seen["aspect_ratio"], len(seen["image"])) == ("prompt", "9:16", 2)
    assert seen["size"] == "1024x1792"


async def test_client_edits_mode_reads_a_base64_image_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    client = KeyframeImageClient(
        base_url="https://api.example/v1",
        api_key="k",
        model="m",
        api="edits",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_delay=0,
    )
    assert await client.generate("prompt", [b"one"]) == PNG


async def test_client_reads_inline_base64_and_retries_overload() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, text="overloaded")
        data = "data:image/png;base64," + base64.b64encode(PNG).decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": data}}]})

    assert await _client(handler).generate("p", []) == PNG
    assert len(attempts) == 3


async def test_client_gives_up_and_rejects_client_errors() -> None:
    always_busy = _client(lambda request: httpx.Response(503, text="busy"))
    with pytest.raises(KeyframeGenerationError, match="HTTP 503"):
        await always_busy.generate("p", [])
    forbidden = _client(lambda request: httpx.Response(403, text="subscribe first"))
    with pytest.raises(KeyframeGenerationError, match="HTTP 403"):
        await forbidden.generate("p", [])
    no_image = _client(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "sorry"}}]})
    )
    with pytest.raises(KeyframeGenerationError, match="no image"):
        await no_image.generate("p", [])


class _Checker:
    def __init__(self, verdicts: list[str | None]) -> None:
        self.verdicts = verdicts
        self.calls = 0

    async def check(self, description, photos, keyframe, master=None, persona=None, previous=None):
        self.calls += 1
        return self.verdicts.pop(0)


class _HungChecker:
    async def check(self, description, photos, keyframe, master=None, persona=None, previous=None):
        await asyncio.sleep(60)


async def test_a_check_that_hangs_is_given_up_and_the_image_is_still_saved(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(service_module, "CHECK_SECONDS", 0.05)
    service = await _service(tmp_path, _FakeKeyframer())
    service._checker = _HungChecker()
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert record["status"] == "ready" and record["qa_problem"].startswith("Not checked")


async def test_a_failed_check_only_advises_and_never_makes_another_image(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    checker = _Checker(["wrong color"])
    service._checker = checker
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert checker.calls == 1 and keyframer.calls == [("master", 2, "")]
    assert (record["status"], record["attempts"], record["qa_problem"]) == (
        "ready",
        1,
        "wrong color",
    )


async def test_unchecked_keyframe_is_not_regenerated(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    service._checker = _Checker([None])
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert len(keyframer.calls) == 1 and record["qa_problem"] == NOT_CHECKED


class _RecordingChecker:
    def __init__(self) -> None:
        self.previous: list[bytes | None] = []

    async def check(self, description, photos, keyframe, master=None, persona=None, previous=None):
        self.previous.append(previous)
        return ""


async def test_later_shots_are_checked_against_the_shot_before_them(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer())
    checker = _RecordingChecker()
    service._checker = checker
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    await service.set_keyframe_status(PRODUCT_ID, 0, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    # master and shot 1 (which follows the master) have no earlier shot; shot 2 sees shot 1
    assert checker.previous == [None, None, PNG + b"follow"]


class _PersonaKeyframer(_FakeKeyframer):
    def __init__(self) -> None:
        super().__init__()
        self.personas: list[list[bytes] | None] = []

    async def master(self, shot, photos, scene, fix="", persona=None):
        self.personas.append(persona)
        return await super().master(shot, photos, scene, fix, persona)


async def _save_brief(service, with_person: bool) -> None:
    brief = {"title": "b", "shots": SHOTS, "with_person": with_person}
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")


async def test_all_photos_of_the_person_reach_the_image_model_when_the_brief_has_a_person(
    tmp_path,
) -> None:
    keyframer = _PersonaKeyframer()
    service = await _service(tmp_path, keyframer)
    await _save_brief(service, with_person=True)

    with pytest.raises(KeyframeUnavailable, match="Upload the photos of the person"):
        await service.generate_keyframes(PRODUCT_ID, tmp_path)

    person = await service.create_persona(tmp_path, "Đạt")  # the first one is the default
    await service.upload_persona(tmp_path, person["id"], b"one")
    await service.upload_persona(tmp_path, person["id"], b"two", add=True)
    await service.upload_persona(tmp_path, person["id"], b"three", add=True)
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.personas == [[b"one", b"two", b"three"]]


async def test_a_brief_without_a_person_never_gets_one_even_when_photos_exist(tmp_path) -> None:
    keyframer = _PersonaKeyframer()
    service = await _service(tmp_path, keyframer)
    await _save_brief(service, with_person=False)
    person = await service.create_persona(tmp_path, "Đạt")
    await service.upload_persona(tmp_path, person["id"], b"one")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.personas == [None]


async def test_a_video_keeps_following_the_person_it_was_written_for(tmp_path) -> None:
    keyframer = _PersonaKeyframer()
    service = await _service(tmp_path, keyframer)
    first = await service.create_persona(tmp_path, "Đạt")
    second = await service.create_persona(tmp_path, "Lan")
    await service.upload_persona(tmp_path, first["id"], b"dat")
    await service.upload_persona(tmp_path, second["id"], b"lan")
    brief = {"title": "b", "shots": SHOTS, "with_person": True, "persona_id": second["id"]}
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.set_default_persona(tmp_path, second["id"])
    await service.set_default_persona(tmp_path, first["id"])  # the default moves on
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.personas == [[b"lan"]]


async def test_people_have_a_default_and_can_be_added_replaced_or_removed(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer())
    assert await service.list_personas(tmp_path) == []
    assert await service.get_persona(tmp_path) is None
    assert await service.brief_persona(tmp_path) == (None, [])

    dat = await service.create_persona(tmp_path, " Đạt ")
    lan = await service.create_persona(tmp_path, "Lan")
    assert dat["name"] == "Đạt"
    assert [(p["name"], p["default"]) for p in await service.list_personas(tmp_path)] == [
        ("Đạt", True),
        ("Lan", False),
    ]
    assert await service.upload_persona(tmp_path, "missing", b"x") is None

    first = await service.upload_persona(tmp_path, dat["id"], b"one")
    await service.upload_persona(tmp_path, dat["id"], b"two", add=True)
    third = await service.upload_persona(tmp_path, dat["id"], b"three", add=True)
    assert (first["attempts"], third["attempts"]) == (1, 3)
    assert await service.persona_photos(tmp_path) == [b"one", b"two", b"three"]  # the default
    assert await service.persona_photos(tmp_path, lan["id"]) == []
    assert (await service.brief_persona(tmp_path))[0] == dat["id"]

    replaced = await service.upload_persona(tmp_path, dat["id"], b"only")
    assert replaced["image_paths"] == [f"persona/{dat['id']}/photo_3.jpg"]
    assert sorted(p.name for p in (tmp_path / "persona" / dat["id"]).iterdir()) == ["photo_3.jpg"]

    assert await service.set_default_persona(tmp_path, lan["id"]) is True
    assert await service.set_default_persona(tmp_path, "missing") is False
    assert (await service.get_persona(tmp_path))["id"] == lan["id"]

    assert await service.delete_persona(tmp_path, lan["id"]) is True  # the default moves on
    assert [p["default"] for p in await service.list_personas(tmp_path)] == [True]
    assert await service.delete_persona(tmp_path, "missing") is False
    assert await service.delete_persona(tmp_path, dat["id"]) is True
    assert await service.list_personas(tmp_path) == []


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def generate(self, prompt, images):
        self.calls.append((prompt, len(images)))
        return PNG


async def test_prompts_name_the_person_only_when_there_is_one() -> None:
    from ai_content.domains.marketing.products.keyframes import KeyframeGenerator

    client = _RecordingClient()
    generator = KeyframeGenerator(client)  # type: ignore[arg-type]
    shot = {"keyframe_prompt": "she folds the basket", "rules": "- Clear skin: no acne"}
    await generator.master(shot, [b"p1", b"p2"], b"room", persona=[b"face"])
    await generator.master(shot, [b"p1"], None)
    await generator.follow_up(shot, b"master", [b"p1"], persona=[b"face"])
    await generator.follow_up(shot, b"master", [b"p1"], persona=[b"face"], reference=b"pose")
    with_person, without, follow, with_reference = client.calls
    assert with_person[1] == 4 and "Images 1 to 2 are the real product photos" in with_person[0]
    assert "Image 3 shows the person in the ad" in with_person[0]
    assert (
        "Image 4 is a scene reference" in with_person[0]
        and "Do not show any human face" not in with_person[0]
    )
    assert "Rules to follow in the picture:" + chr(10) + "- Clear skin: no acne" in with_person[0]
    assert without[1] == 1 and "Do not show any human face" in without[0]
    assert follow[1] == 3 and "Image 1 is the real product photo" in follow[0]
    assert "Image 2 shows the person in the ad" in follow[0]
    assert "Image 3 is the approved master keyframe" in follow[0]
    assert with_reference[1] == 4 and "Image 4 is a loose reference" in with_reference[0]
    assert "loose reference" not in follow[0]


async def test_the_real_product_size_reaches_the_image_prompt_and_the_checker(tmp_path) -> None:
    prompts: list[str] = []

    class _Client:
        async def generate(self, prompt, images):
            prompts.append(prompt)
            return PNG + b"img"

    seen: list[str] = []

    class _SizeChecker:
        async def check(
            self, description, photos, keyframe, master=None, persona=None, previous=None
        ):
            seen.append(description)
            return ""

    repository = product_repository()
    service = ProductCatalogService(
        repository, keyframer=KeyframeGenerator(_Client()), checker=_SizeChecker()
    )
    await repository.upsert_detail(
        {"product_id": PRODUCT_ID, "title": "Giỏ", "images": ["https://img.example/1.jpg"]}
    )
    brief = {
        "title": "b",
        "product_size": "about 60 cm tall, knee height",
        "product_variant": "matte pink bottle",
        "shots": SHOTS[:1],
    }
    await repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert "about 60 cm tall, knee height" in prompts[0]
    assert "about 60 cm tall, knee height" in seen[0]
    # one version of the product, shot like an ordinary phone photo
    assert "show only this one: matte pink bottle" in prompts[0]
    assert "matte pink bottle" in seen[0]


async def test_each_step_is_written_to_the_run_log(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer())
    service._checker = _Checker(["wrong color"])
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    await service.set_keyframe_status(PRODUCT_ID, 0, "approved")
    events = await service.events(PRODUCT_ID)
    assert [(e["step"], e["status"], e["shot_index"]) for e in events] == [
        ("keyframe", "flagged", 0),
        ("keyframe", "approved", 0),
    ]
    assert "wrong color" in events[0]["message"]


async def test_generated_keyframes_are_uploaded_and_restored_from_the_remote(tmp_path) -> None:
    from tests.test_product_media_store import _Remote

    remote = _Remote()
    service = await _service(tmp_path, _FakeKeyframer())
    service._remote_media = remote
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert (
        remote.objects["affiliate-media/keyframes/" + PRODUCT_ID + "/shot_0.jpg"] == PNG + b"master"
    )

    (tmp_path / "keyframes" / PRODUCT_ID / "shot_0.jpg").unlink()
    await service.set_keyframe_status(PRODUCT_ID, 0, "approved")
    # the master is read back from the remote to make the other shots
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert (tmp_path / "keyframes" / PRODUCT_ID / "shot_1.jpg").is_file()


class _SlowKeyframer(_FakeKeyframer):
    def __init__(self) -> None:
        super().__init__()
        self.running = 0
        self.peak = 0

    async def follow_up(self, shot, master, photos, fix="", persona=None, reference=None):
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.02)
        self.running -= 1
        return await super().follow_up(shot, master, photos, fix, persona, reference)


class _CutChecker:
    def __init__(self) -> None:
        self.previous: dict[str, bytes | None] = {}

    async def check(self, description, photos, keyframe, master=None, persona=None, previous=None):
        self.previous[description.splitlines()[0]] = previous
        return ""


async def test_follow_up_shots_run_together_and_cut_check_sees_the_shot_before(tmp_path) -> None:
    shots = [
        {"role": "r", "keyframe_prompt": f"shot {i}", "description": f"d{i}"} for i in range(4)
    ]
    keyframer = _SlowKeyframer()
    service = await _service(tmp_path, keyframer, shots)
    checker = _CutChecker()
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    await service.set_keyframe_status(PRODUCT_ID, 0, "approved")
    service._checker = checker
    await service.generate_keyframes(PRODUCT_ID, tmp_path)

    assert keyframer.peak > 1
    assert checker.previous["d1"] is None
    assert checker.previous["d2"] == PNG + b"follow"
    assert checker.previous["d3"] == PNG + b"follow"


def _jpeg(size: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, "JPEG")
    return buffer.getvalue()


def test_large_input_images_are_shrunk_and_the_rest_pass_through() -> None:
    small = _jpeg((800, 1200))
    assert keyframes_module._shrink(small) == small
    assert keyframes_module._shrink(PNG) == PNG

    big = keyframes_module._shrink(_jpeg((3000, 2000)))
    assert Image.open(io.BytesIO(big)).size == (1792, 1195)


async def test_the_prompt_names_every_photo_of_the_person() -> None:
    from ai_content.domains.marketing.products.keyframes import KeyframeGenerator

    client = _RecordingClient()
    generator = KeyframeGenerator(client)  # type: ignore[arg-type]
    shot = {"keyframe_prompt": "he folds the basket"}
    await generator.master(shot, [b"p1"], None, persona=[b"a", b"b", b"c"])
    [(prompt, count)] = client.calls
    assert count == 4 and "Images 2 to 4 show the person in the ad" in prompt
    assert not re.search(r"\b(she|her)\b", prompt)


async def test_the_product_comes_first_then_the_person_then_the_references() -> None:
    from ai_content.domains.marketing.products.keyframes import KeyframeGenerator

    client = _RecordingClient()
    generator = KeyframeGenerator(client)  # type: ignore[arg-type]
    shot = {"keyframe_prompt": "he folds the basket"}
    await generator.follow_up(
        shot, b"m", [b"p1", b"p2", b"p3"], persona=[b"a", b"b"], reference=b"r"
    )
    [(prompt, count)] = client.calls
    assert count == 7
    order = [
        prompt.index(text)
        for text in (
            "Images 1 to 3 are the real product photos",
            "Images 4 to 5 show the person in the ad",
            "Image 6 is the approved master keyframe",
            "Image 7 is a loose reference",
        )
    ]
    assert order == sorted(order)
    assert "first the real product exactly as in its photos, then the face" in prompt


def test_the_story_note_gives_one_shot_the_whole_video() -> None:
    brief = {
        "title": "Giỏ gấp",
        "selling_angle": "gọn nhà",
        "target_audience": "người ở trọ",
        "scene": "phòng trọ nhỏ",
        "product_placement": "cạnh giường",
        "style": ["tự nhiên"],
        "colors": ["trắng"],
        "shots": [
            {"role": "hook", "description": "mở đầu", "voiceover": "câu một"},
            {"role": "demo", "description": "dùng thử", "voiceover": "câu hai"},
        ],
    }
    note = keyframes_module.story_note(brief, 1)
    assert "shot 2 of 2" in note and "phòng trọ nhỏ" in note and "cạnh giường" in note
    assert "What is said over this shot: câu hai" in note
    assert "1. hook: mở đầu" in note and "2. demo: dùng thử" in note


async def test_the_story_reaches_the_image_prompt_and_the_checker(tmp_path) -> None:
    prompts: list[str] = []

    class _Client:
        async def generate(self, prompt, images):
            prompts.append(prompt)
            return PNG

    seen: list[str] = []

    class _Checker:
        async def check(
            self, description, photos, keyframe, master=None, persona=None, previous=None
        ):
            seen.append(description)
            return ""

    service = await _service(tmp_path, KeyframeGenerator(_Client()))  # type: ignore[arg-type]
    service._checker = _Checker()
    brief = {"title": "b", "scene": "phòng trọ nhỏ", "shots": SHOTS}
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert "The whole video, for context:" in prompts[0] and "phòng trọ nhỏ" in prompts[0]
    assert "phòng trọ nhỏ" in seen[0]


async def test_a_note_is_the_first_thing_the_image_model_is_asked_to_fix(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    await service.generate_keyframes(PRODUCT_ID, tmp_path, 0, "faint marks on the cheek")
    assert keyframer.calls == [("master", 2, "faint marks on the cheek")]


async def test_an_unchecked_keyframe_can_be_checked_again_without_a_new_image(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    checker = _Checker([None, "wrong label"])
    service._checker = checker
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert record["qa_problem"] == NOT_CHECKED

    checked = await service.recheck_keyframe(PRODUCT_ID, 0, tmp_path)
    assert checked["qa_problem"] == "wrong label" and checked["status"] == "ready"
    assert (await service.list_keyframes(PRODUCT_ID))[0]["qa_problem"] == "wrong label"
    assert len(keyframer.calls) == 1 and checker.calls == 2
    assert await service.recheck_keyframe(PRODUCT_ID, 2, tmp_path) is None


def _picture(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(("size", "expected"), [((1024, 1536), (864, 1536)), ((1792, 1024), (576, 1024)), ((864, 1536), (864, 1536))])
def test_a_keyframe_that_is_not_9_by_16_is_cropped_to_it(size, expected) -> None:
    kept = _to_vertical(_picture(*size))
    assert Image.open(io.BytesIO(kept)).size == expected
    assert _to_vertical(b"not an image") == b"not an image"


class _PhotoChecker:
    def __init__(self) -> None:
        self.photos: list[int] = []

    async def check(self, description, photos, keyframe, master=None, persona=None, previous=None):
        self.photos.append(len(photos))
        return ""


async def test_the_check_sees_more_product_photos_than_the_image_model(tmp_path) -> None:
    urls = [f"https://img.example/{i}.jpg" for i in range(1, 9)]
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    await service._repository.upsert_detail({"product_id": PRODUCT_ID, "title": "Giỏ", "images": urls})
    checker = _PhotoChecker()
    service._checker = checker
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.calls[-1][1] == 3 and checker.photos == [4]
    await service.recheck_keyframe(PRODUCT_ID, 0, tmp_path)
    assert checker.photos == [4, 4]


class _FaceChecker:
    """Fails every image on the face, as a strict check does."""

    def __init__(self, category: str) -> None:
        self.category = category
        self.calls = 0

    async def check(self, description, photos, keyframe, master=None, persona=None, previous=None):
        self.calls += 1
        return QAProblem(f"problem {self.calls}", self.category)


async def test_a_face_problem_is_not_proposed_as_a_rule_but_others_are(tmp_path) -> None:
    from tests.test_product_knowledge import _knowledge

    knowledge = _knowledge(tmp_path)
    service = await _service(tmp_path, _FakeKeyframer())
    service._knowledge = knowledge
    service._checker = _FaceChecker("face")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert await knowledge.repository.list() == []
    service._checker = _FaceChecker("product")
    await service.generate_keyframes(PRODUCT_ID, tmp_path, shot_index=0)
    assert [item.content for item in await knowledge.repository.list()] == ["problem 1"]


async def test_a_skin_product_keeps_the_skin_of_the_person_as_it_is() -> None:
    client = _RecordingClient()
    generator = KeyframeGenerator(client)  # type: ignore[arg-type]
    shot = {"keyframe_prompt": "she holds the cream"}
    await generator.master(shot, [b"p1"], None, persona=[b"face"])
    await generator.master({**shot, "retouch": False}, [b"p1"], None, persona=[b"face"])
    retouched, kept = (prompt for prompt, _ in client.calls)
    assert "Retouch only the skin" in retouched and "Do not retouch" not in retouched
    assert "Do not retouch the skin" in kept and "Retouch only the skin" not in kept


async def test_every_image_call_is_counted_in_the_usage_ledger(tmp_path) -> None:
    from datetime import UTC, datetime, timedelta

    from ai_content.platform.ai_usage import (
        AIUsageFilters,
        AIUsageTracker,
    )

    service = await _service(tmp_path, _FakeKeyframer())
    ledger = usage_repository()
    service._usage = AIUsageTracker(ledger)
    service._checker = _Checker(["wrong color"])
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    now = datetime.now(UTC)
    window = AIUsageFilters(
        now - timedelta(hours=1), now + timedelta(hours=1), correlation_id=PRODUCT_ID
    )
    [counted] = (await ledger.summary(window)).by_operation
    assert (counted.key, counted.request_count, counted.succeeded) == ("keyframe", 1, 1)
