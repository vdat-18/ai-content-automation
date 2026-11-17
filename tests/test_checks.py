from types import SimpleNamespace

import pytest
from baml_py.baml_py import BamlError

from ai_content.domains.marketing.products.clip_check import ClipChecker
from ai_content.domains.marketing.products.keyframe_check import KeyframeChecker

PHOTO = b"\xff\xd8photo"


class _Flaky:
    """Fails with a BamlError for the first `failures` calls, then answers."""

    def __init__(self, failures: int, passed: bool = True, problem: str = "") -> None:
        self.failures = failures
        self.calls = 0
        self.answer = SimpleNamespace(passed=passed, problem=problem, category="face")

    async def _answer(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise BamlError("quota")
        return self.answer

    async def CheckKeyframe(self, *args):
        return await self._answer()

    async def CheckClip(self, *args):
        return await self._answer()


async def _keyframe(client: _Flaky) -> str | None:
    return await KeyframeChecker(client).check("d", [PHOTO], PHOTO)  # type: ignore[arg-type]


async def _clip(client: _Flaky) -> str | None:
    return await ClipChecker(client).check("d", [PHOTO], PHOTO, [PHOTO])  # type: ignore[arg-type]


@pytest.mark.parametrize("check", [_keyframe, _clip])
async def test_a_check_that_fails_raises_its_error_and_is_asked_only_once(check) -> None:
    down = _Flaky(failures=9)
    with pytest.raises(BamlError):
        await check(down)
    assert down.calls == 1


@pytest.mark.parametrize("check", [_keyframe, _clip])
async def test_a_failed_check_reports_the_problem(check) -> None:
    found = await check(_Flaky(failures=0, passed=False, problem="wrong color"))
    assert found == "wrong color" and found.category == "face"
    assert await check(_Flaky(failures=0, passed=False, problem=" ")) != ""


def test_a_picture_is_typed_by_its_bytes_not_by_what_the_cdn_says() -> None:
    from ai_content.domains.marketing.products.keyframe_check import _image

    samples = {
        b"\x89PNG\r\n\x1a\n": "image/png",
        b"\xff\xd8\xff\xe0": "image/jpeg",
    }
    for content, expected in samples.items():
        assert _image(content).as_base64()[1] == expected


def test_a_webp_picture_is_sent_as_a_real_jpeg() -> None:
    import base64
    import io

    from PIL import Image

    from ai_content.domains.marketing.products.keyframe_check import _image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "WEBP")
    data, media_type = _image(buffer.getvalue()).as_base64()
    assert media_type == "image/jpeg"
    assert Image.open(io.BytesIO(base64.b64decode(data))).format == "JPEG"


async def test_the_clip_check_sends_a_webp_product_photo_as_jpeg() -> None:
    import base64
    import io

    from PIL import Image

    seen = []

    class _Client:
        async def CheckClip(self, description, photos, keyframe, characters, frames):
            seen.extend(photos)
            return SimpleNamespace(passed=True, problem="", category="other")

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "WEBP")
    assert await ClipChecker(_Client()).check("shot", [buffer.getvalue()], b"key", [b"frame"]) == ""
    data, media_type = seen[0].as_base64()
    assert media_type == "image/jpeg"
    assert Image.open(io.BytesIO(base64.b64decode(data))).format == "JPEG"
