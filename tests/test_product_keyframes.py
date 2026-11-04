import base64
import json

import httpx
import pytest

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.keyframes import (
    KeyframeGenerationError,
    KeyframeGenerator,
    KeyframeImageClient,
)
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import (
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

    async def follow_up(self, shot, master, photos, fix="", persona=None):
        self.calls.append(("follow_up", len(photos), fix))
        assert master == PNG + b"master"
        return PNG + b"follow"


@pytest.fixture(autouse=True)
def fake_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch_images(urls, http=None):
        return [b"photo-" + url.encode() for url in urls]

    monkeypatch.setattr(service_module, "fetch_images", fetch_images)


async def _service(tmp_path, keyframer, shots=SHOTS) -> ProductCatalogService:
    repository = SqliteProductRepository(tmp_path / "k.db")
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


async def test_failed_check_regenerates_with_the_problem_then_passes(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    service._checker = _Checker(["wrong color", ""])
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.calls == [("master", 2, ""), ("master", 2, "wrong color")]
    assert (record["status"], record["attempts"], record["qa_problem"]) == ("ready", 2, "")


async def test_check_that_keeps_failing_stops_after_two_fixes_and_flags_the_image(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    checker = _Checker(["bad", "still bad", "no luck"])
    service._checker = checker
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert checker.calls == 3 and len(keyframer.calls) == 3
    assert (record["status"], record["attempts"], record["qa_problem"]) == ("ready", 3, "no luck")


async def test_unchecked_keyframe_is_not_regenerated(tmp_path) -> None:
    keyframer = _FakeKeyframer()
    service = await _service(tmp_path, keyframer)
    service._checker = _Checker([None])
    [record] = await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert len(keyframer.calls) == 1 and record["qa_problem"] == ""


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
        self.personas: list[bytes | None] = []

    async def persona(self, description, fix=""):
        return PNG + description.encode()

    async def master(self, shot, photos, scene, fix="", persona=None):
        self.personas.append(persona)
        return await super().master(shot, photos, scene, fix, persona)


async def test_a_person_must_be_approved_before_keyframes_and_is_passed_to_each_one(
    tmp_path,
) -> None:
    keyframer = _PersonaKeyframer()
    service = await _service(tmp_path, keyframer)
    brief = {
        "title": "b",
        "shots": SHOTS,
        "persona": {"description": "woman, 28", "status": "none"},
    }
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")

    with pytest.raises(KeyframeUnavailable, match="Approve the person"):
        await service.generate_keyframes(PRODUCT_ID, tmp_path)

    persona = await service.generate_persona(PRODUCT_ID, tmp_path)
    assert persona is not None and persona["status"] == "ready" and persona["attempts"] == 1
    assert (tmp_path / persona["image_path"]).read_bytes() == PNG + b"woman, 28"
    with pytest.raises(KeyframeUnavailable, match="Approve the person"):
        await service.generate_keyframes(PRODUCT_ID, tmp_path)

    assert await service.set_persona_status(PRODUCT_ID, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert keyframer.personas == [PNG + b"woman, 28"]
    edited = await service.generate_persona(PRODUCT_ID, tmp_path, "man, 40")
    assert edited is not None and edited["description"] == "man, 40" and edited["attempts"] == 2


async def test_person_errors_are_reported(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer())
    assert await service.generate_persona("missing", tmp_path) is None
    with pytest.raises(KeyframeUnavailable, match="no person yet"):
        await service.generate_persona(PRODUCT_ID, tmp_path)
    assert not await service.set_persona_status(PRODUCT_ID, "approved")
    with pytest.raises(ValueError, match="status must be one of"):
        await service.set_persona_status(PRODUCT_ID, "published")


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
    shot = {"keyframe_prompt": "she folds the basket"}
    await generator.master(shot, [b"p1", b"p2"], b"room", persona=b"face")
    await generator.master(shot, [b"p1"], None)
    await generator.follow_up(shot, b"master", [b"p1"], persona=b"face")
    await generator.persona("woman, 28")
    with_person, without, follow, portrait = client.calls
    assert with_person[1] == 4 and "Image 3 is the character" in with_person[0]
    assert (
        "Image 4 is a scene reference" in with_person[0]
        and "Do not show any human face" not in with_person[0]
    )
    assert without[1] == 1 and "Do not show any human face" in without[0]
    assert follow[1] == 3 and "Image 2 is the character" in follow[0]
    assert (
        portrait[1] == 0 and "does not exist" in portrait[0] and portrait[0].endswith("woman, 28")
    )


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

    repository = SqliteProductRepository(tmp_path / "s.db")
    service = ProductCatalogService(
        repository, keyframer=KeyframeGenerator(_Client()), checker=_SizeChecker()
    )
    await repository.upsert_detail(
        {"product_id": PRODUCT_ID, "title": "Giỏ", "images": ["https://img.example/1.jpg"]}
    )
    brief = {"title": "b", "product_size": "about 60 cm tall, knee height", "shots": SHOTS[:1]}
    await repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert "about 60 cm tall, knee height" in prompts[0]
    assert "about 60 cm tall, knee height" in seen[0]


async def test_each_step_is_written_to_the_run_log(tmp_path) -> None:
    service = await _service(tmp_path, _FakeKeyframer())
    service._checker = _Checker(["wrong color", ""])
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    await service.set_keyframe_status(PRODUCT_ID, 0, "approved")
    events = await service.events(PRODUCT_ID)
    assert [(e["step"], e["status"], e["shot_index"]) for e in events] == [
        ("keyframe", "retry", 0),
        ("keyframe", "ok", 0),
        ("keyframe", "approved", 0),
    ]
    assert "wrong color" in events[0]["message"] and "2 attempt" in events[1]["message"]
