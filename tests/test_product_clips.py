import shutil
import subprocess

import httpx
import pytest

from ai_content.domains.marketing.products.clips import (
    ClipGenerationError,
    JobState,
    StitchUnavailable,
    VideoClient,
    stitch,
)
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import (
    KeyframeUnavailable,
    ProductCatalogService,
)

PRODUCT_ID = "1730000000000000001"
SHOTS = [
    {"role": "hook", "motion_prompt": "push in", "duration_seconds": 5},
    {"role": "demo", "motion_prompt": "pan left", "duration_seconds": 8},
]


class _FakeVideo:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, int]] = []
        self.states: dict[str, JobState] = {}

    async def submit(self, prompt, image, seconds):
        job = f"job{len(self.submitted)}"
        self.submitted.append((prompt, seconds))
        self.states[job] = JobState("processing")
        return job, "xai/model"

    async def status(self, job_id, job_model):
        assert job_model == "xai/model"
        return self.states[job_id]

    async def download(self, video_url):
        return b"mp4-bytes"


async def _service(tmp_path, video) -> ProductCatalogService:
    repository = SqliteProductRepository(tmp_path / "c.db")
    service = ProductCatalogService(repository, videographer=video)
    await repository.save_brief(PRODUCT_ID, "", {"title": "b", "shots": SHOTS}, "approved")
    for index in range(2):
        frame = tmp_path / f"frame{index}.jpg"
        frame.write_bytes(b"jpeg")
        await repository.save_keyframe(
            {
                "product_id": PRODUCT_ID,
                "shot_index": index,
                "status": "approved" if index == 0 else "ready",
                "prompt": "p",
                "image_path": frame.name,
                "attempts": 1,
                "error": None,
                "qa_problem": "",
            }
        )
    return service


async def test_only_approved_keyframes_start_jobs_and_finished_ones_are_downloaded(
    tmp_path,
) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    [clip] = await service.generate_clips(PRODUCT_ID, tmp_path)
    assert (clip["shot_index"], clip["status"], clip["seconds"]) == (0, "processing", 15)
    assert video.submitted[0][0].startswith("push in")

    with pytest.raises(KeyframeUnavailable, match="No approved keyframe"):
        await service.generate_clips(PRODUCT_ID, tmp_path)
    with pytest.raises(KeyframeUnavailable, match="Approve this shot"):
        await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=1)

    assert (await service.clips(PRODUCT_ID, tmp_path))[0]["status"] == "processing"
    video.states["job0"] = JobState("completed", video_url="https://v/x.mp4")
    [ready] = await service.clips(PRODUCT_ID, tmp_path)
    assert ready["status"] == "ready"
    assert (tmp_path / ready["video_path"]).read_bytes() == b"mp4-bytes"


async def test_failed_job_keeps_the_reason_and_can_be_started_again(tmp_path) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("failed", error="policy")
    [failed] = await service.clips(PRODUCT_ID, tmp_path)
    assert (failed["status"], failed["error"]) == ("failed", "policy")
    [again] = await service.generate_clips(PRODUCT_ID, tmp_path)
    assert (again["status"], again["attempts"]) == ("processing", 2)


async def test_submit_error_is_recorded_as_a_failed_clip(tmp_path) -> None:
    class _Down(_FakeVideo):
        async def submit(self, prompt, image, seconds):
            raise ClipGenerationError("HTTP 503")

    service = await _service(tmp_path, _Down())
    [clip] = await service.generate_clips(PRODUCT_ID, tmp_path)
    assert (clip["status"], clip["error"]) == ("failed", "HTTP 503")


async def test_video_needs_a_configured_model_and_ready_clips(tmp_path) -> None:
    service = await _service(tmp_path, None)
    with pytest.raises(KeyframeUnavailable, match="not configured"):
        await service.generate_clips(PRODUCT_ID, tmp_path)
    assert await service.generate_clips("missing", tmp_path) is None

    video = _FakeVideo()
    service = await _service(tmp_path, video)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    with pytest.raises(StitchUnavailable, match="shot 1 is not ready"):
        await service.build_video(PRODUCT_ID, tmp_path)
    assert await service.build_video("missing", tmp_path) is None


def _client(handler) -> VideoClient:
    return VideoClient(
        base_url="https://api.example/v1",
        api_key="k",
        model="dw/xai/model",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_video_client_submits_polls_and_downloads() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "v1", "model": "xai/model", "status": "queued"})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=b"video")
        return httpx.Response(
            200,
            json={"status": "completed", "video_url": "https://api.example/v1/videos/v1/content"},
        )

    client = _client(handler)
    assert await client.submit("p", b"\x89PNG....", 15) == ("v1", "xai/model")
    body = seen[0].content.decode()
    assert '"seconds":15' in body and '"size":"9:16"' in body and "data:image/png" in body
    state = await client.status("v1", "xai/model")
    assert (state.status, state.video_url) == (
        "completed",
        "https://api.example/v1/videos/v1/content",
    )
    assert "model=xai%2Fmodel" in str(seen[1].url)
    assert await client.download(state.video_url or "") == b"video"


async def test_video_client_reports_http_errors() -> None:
    client = _client(lambda request: httpx.Response(503, text="busy"))
    with pytest.raises(ClipGenerationError, match="HTTP 503"):
        await client.submit("p", b"x", 6)
    no_id = _client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ClipGenerationError, match="no job id"):
        await no_id.submit("p", b"x", 6)
    failing = _client(lambda request: httpx.Response(500))
    with pytest.raises(ClipGenerationError, match="status check failed"):
        await failing.status("v1", "m")


async def test_stitch_requires_clips_and_ffmpeg(tmp_path, monkeypatch) -> None:
    with pytest.raises(StitchUnavailable, match="No clip"):
        await stitch([], tmp_path / "out.mp4")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(StitchUnavailable, match="ffmpeg is not installed"):
        await stitch([(tmp_path / "a.mp4", 1)], tmp_path / "out.mp4")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stitch_joins_trimmed_clips(tmp_path) -> None:
    sources = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"c{index}.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=320x568:d=3:r=24",
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "3", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
            check=True,
        )  # fmt: skip
        sources.append((path, 2.0))
    output = tmp_path / "videos" / "out.mp4"
    await stitch(sources, output)
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert 3.8 < float(duration) < 4.3
    assert not list(output.parent.glob("part_*.mp4"))
