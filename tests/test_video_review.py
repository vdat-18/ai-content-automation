import shutil
from types import SimpleNamespace

import pytest
from baml_py.baml_py import BamlError
from tests.test_product_clips import PRODUCT_ID, _make_clip

from ai_content.domains.marketing.products.clips import StitchClip, sample_frames, stitch
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService
from ai_content.domains.marketing.products.video_review import VideoReviewer

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _reviewer(reply=None, error: Exception | None = None) -> VideoReviewer:
    class Client:
        async def ReviewFinalVideo(self, product_json, storyboard_json, product_photos, frames):  # noqa: N802
            if error:
                raise error
            return SimpleNamespace(**reply)

    return VideoReviewer(Client())  # type: ignore[arg-type]


async def test_a_passing_video_review_has_no_problems() -> None:
    reviewer = _reviewer({"passed": True, "problems": []})
    assert await reviewer.review({}, {}, [], []) == []


async def test_a_failing_video_review_returns_what_is_wrong() -> None:
    reviewer = _reviewer({"passed": False, "problems": [" Around frame 5 the basket is tiny. "]})
    assert await reviewer.review({}, {}, [], []) == ["Around frame 5 the basket is tiny."]
    silent = _reviewer({"passed": False, "problems": []})
    assert await silent.review({}, {}, [], [])


async def test_a_video_review_that_could_not_run_is_unchecked() -> None:
    assert await _reviewer(error=BamlError("down")).review({}, {}, [], []) is None


@needs_ffmpeg
async def test_frames_are_sampled_along_the_whole_video(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", seconds=6, audio=False)
    output = tmp_path / "videos" / "out.mp4"
    await stitch([StitchClip(clip, 6.0)], output)
    frames = await sample_frames(output, 4.0, 4)
    assert len(frames) == 4 and all(frame[:2] == b"\xff\xd8" for frame in frames)


class _Judge:
    def __init__(self, problems: list[str] | None) -> None:
        self.problems = problems
        self.frames = 0

    async def review(self, product, brief, photos, frames):
        self.frames = len(frames)
        return self.problems


@needs_ffmpeg
@pytest.mark.parametrize(
    ("problems", "status"),
    [([], "ok"), (["Around frame 2 the basket is tiny."], "flagged"), (None, "skipped")],
)
async def test_the_verdict_on_the_finished_video_goes_to_the_run_log(
    tmp_path, problems, status
) -> None:
    judge = _Judge(problems)
    service = ProductCatalogService(
        SqliteProductRepository(tmp_path / "v.db"),
        video_reviewer=judge,  # type: ignore[arg-type]
    )
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", seconds=4, audio=False)
    video = tmp_path / "videos" / "out.mp4"
    await stitch([StitchClip(clip, 4.0)], video)
    await service._review_video(PRODUCT_ID, {"shots": []}, [StitchClip(clip, 4.0)], video)
    event = (await service.events(PRODUCT_ID))[-1]
    assert event["step"] == "video_review" and event["status"] == status
    assert judge.frames >= 1
