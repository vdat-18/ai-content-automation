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
        self.answer = SimpleNamespace(passed=passed, problem=problem)

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
    return await KeyframeChecker(client, retry_delay=0).check("d", [PHOTO], PHOTO)  # type: ignore[arg-type]


async def _clip(client: _Flaky) -> str | None:
    return await ClipChecker(client, retry_delay=0).check("d", [PHOTO], PHOTO, [PHOTO])  # type: ignore[arg-type]


@pytest.mark.parametrize("check", [_keyframe, _clip])
async def test_a_check_is_tried_again_before_it_gives_up(check) -> None:
    recovering = _Flaky(failures=2)
    assert await check(recovering) == "" and recovering.calls == 3
    down = _Flaky(failures=9)
    assert await check(down) is None and down.calls == 3


@pytest.mark.parametrize("check", [_keyframe, _clip])
async def test_a_failed_check_reports_the_problem(check) -> None:
    assert await check(_Flaky(failures=0, passed=False, problem="wrong color")) == "wrong color"
    assert await check(_Flaky(failures=0, passed=False, problem=" ")) != ""
