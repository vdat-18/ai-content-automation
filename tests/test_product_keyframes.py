import base64
import json

import httpx
import pytest

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.keyframes import (
    KeyframeGenerationError,
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

    async def master(self, shot, photos, scene):
        self.calls.append(("master", len(photos)))
        if self.fail:
            raise KeyframeGenerationError("HTTP 503")
        return PNG + b"master"

    async def follow_up(self, shot, master, photos):
        self.calls.append(("follow_up", len(photos)))
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
    assert keyframer.calls == [("master", 2), ("follow_up", 2), ("follow_up", 2)]


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
