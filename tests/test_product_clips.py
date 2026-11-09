import json
import shutil
import subprocess

import httpx
import pytest

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.clips import (
    ClipGenerationError,
    JobState,
    StitchClip,
    StitchUnavailable,
    VideoClient,
    caption_font,
    clip_frames,
    cover_frame,
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
        await stitch([StitchClip(tmp_path / "a.mp4", 1)], tmp_path / "out.mp4")


def _make_clip(path, color: str, seconds: int = 3, audio: bool = True) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color={color}:s=320x568:d={seconds}:r=24",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    subprocess.run([*command, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def _probe(path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stitch_joins_trimmed_clips_without_the_clips_own_audio(tmp_path) -> None:
    clips = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"c{index}.mp4"
        _make_clip(path, color)
        clips.append(StitchClip(path, 2.0, "Phòng giặt gọn hơn" if index == 0 else ""))
    output = tmp_path / "videos" / "out.mp4"
    await stitch(clips, output)
    assert 3.3 < float(_probe(output, "format=duration")) < 3.8
    assert _probe(output, "stream=codec_type").split() == ["video"]
    assert sorted(p.name for p in output.parent.iterdir()) == ["out.mp4"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_cover_is_a_jpeg_frame_of_the_video(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "blue", seconds=3, audio=False)
    cover = tmp_path / "cover.jpg"
    await cover_frame(clip, cover)
    assert cover.read_bytes()[:2] == b"\xff\xd8"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stitch_lays_one_voiceover_over_the_whole_video(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "green", seconds=4, audio=False)
    voice = tmp_path / "voice.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", str(voice)],
        check=True,
    )  # fmt: skip
    output = tmp_path / "videos" / "out.mp4"
    await stitch([StitchClip(clip, 3.0)], output, voiceover=voice)
    assert sorted(_probe(output, "stream=codec_type").split()) == ["audio", "video"]
    assert float(_probe(output, "format=duration")) < 2.3


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or caption_font() is None, reason="no ffmpeg or caption font"
)
async def test_stitch_burns_the_caption_into_the_picture(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "black", audio=False)
    plain, captioned = tmp_path / "plain.mp4", tmp_path / "captioned.mp4"
    await stitch([StitchClip(clip, 3.0)], plain)
    await stitch([StitchClip(clip, 3.0, "Gấp gọn trong 3 giây")], captioned)
    frame = lambda video: subprocess.run(  # noqa: E731
        ["ffmpeg", "-v", "error", "-ss", "1", "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    assert max(frame(plain)) < 20 and max(frame(captioned)) > 200


def test_voiceover_is_found_beside_the_video(tmp_path) -> None:
    from ai_content.domains.marketing.products.service import find_voiceover

    assert find_voiceover(tmp_path, "p1") is None
    folder = tmp_path / "videos" / "p1"
    folder.mkdir(parents=True)
    (folder / "voiceover.m4a").write_bytes(b"x")
    assert find_voiceover(tmp_path, "p1") == folder / "voiceover.m4a"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_building_the_video_records_how_it_was_made(tmp_path) -> None:
    service = await _service(tmp_path, _FakeVideo())
    clip = tmp_path / "clips" / PRODUCT_ID / "shot_0.mp4"
    clip.parent.mkdir(parents=True)
    _make_clip(clip, "red", seconds=4, audio=False)
    await service._repository.save_clip(
        {
            "product_id": PRODUCT_ID,
            "shot_index": 0,
            "status": "ready",
            "job_id": "j",
            "job_model": "m",
            "video_path": f"clips/{PRODUCT_ID}/shot_0.mp4",
            "seconds": 5,
            "attempts": 2,
            "error": None,
            "qa_problem": "",
        }
    )
    await service.note_voice(PRODUCT_ID, tmp_path, "Kim Oanh")
    await service.build_video(PRODUCT_ID, tmp_path)
    folder = tmp_path / "videos" / PRODUCT_ID
    built = json.loads((folder / "video.json").read_text(encoding="utf-8"))
    assert built["clip_attempts"] == {"0": 2} and built["captions"] is False
    assert built["voice"]["voice"] == "Kim Oanh" and built["seconds"] > 0
    assert (folder / "cover.jpg").is_file()
    [output] = await service.list_outputs(tmp_path)
    assert (output["shots"], output["voice"], output["has_cover"]) == (1, "Kim Oanh", True)


async def test_clip_prompt_follows_the_shots_delivery(tmp_path) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    record = await service._repository.get_brief(PRODUCT_ID)
    shots = [
        {**record["brief"]["shots"][0], "delivery": "talking", "voiceover": "Xin chào các bạn"}
    ]
    await service._repository.save_brief(
        PRODUCT_ID, "", {**record["brief"], "shots": shots}, "approved"
    )
    await service.generate_clips(PRODUCT_ID, tmp_path)
    assert "speaks naturally to the camera" in video.submitted[0][0]
    assert 'says in Vietnamese, in one go: "Xin chào các bạn"' in video.submitted[0][0]
    assert "no dialogue" not in video.submitted[0][0]

    shots[0]["delivery"] = "narrated"
    await service._repository.save_brief(
        PRODUCT_ID, "", {**record["brief"], "shots": shots}, "approved"
    )
    await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    assert "Nobody speaks" in video.submitted[1][0]
    assert "no dialogue" in video.submitted[1][0] and "Xin chào" not in video.submitted[1][0]


def test_clips_play_faster_by_the_configured_speed(monkeypatch) -> None:
    from ai_content.domains.marketing.products.clips import clip_speed, shot_seconds

    monkeypatch.delenv("AIC_CLIP_SPEED", raising=False)
    assert clip_speed() == 1.25 and round(shot_seconds(15), 2) == 11.8
    monkeypatch.setenv("AIC_CLIP_SPEED", "1")
    assert round(shot_seconds(15), 2) == 14.75
    monkeypatch.setenv("AIC_CLIP_SPEED", "9")
    assert clip_speed() == 2.0
    monkeypatch.setenv("AIC_CLIP_SPEED", "abc")
    assert clip_speed() == 1.25


class _FakeClipChecker:
    def __init__(self, verdicts: list[str | None]) -> None:
        self.verdicts = verdicts
        self.calls: list[tuple[str, bytes, int]] = []

    async def check(self, description, photos, keyframe, frames, persona=None):
        self.calls.append((description, keyframe, len(frames)))
        return self.verdicts.pop(0)


async def test_finished_clip_is_checked_and_a_flag_is_kept_until_it_is_made_again(
    tmp_path, monkeypatch
) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    checker = _FakeClipChecker(["product melts in frame 3", "", None])
    service._clip_checker = checker

    async def frames(path, seconds):
        return [b"a", b"b", b"c"]

    monkeypatch.setattr(service_module, "clip_frames", frames)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("completed", video_url="https://v/x.mp4")
    [flagged] = await service.clips(PRODUCT_ID, tmp_path)
    assert (flagged["status"], flagged["qa_problem"]) == ("ready", "product melts in frame 3")
    assert checker.calls == [("push in", b"jpeg", 3)]

    [again] = await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    assert (again["status"], again["qa_problem"]) == ("processing", "")
    video.states["job1"] = JobState("completed", video_url="https://v/y.mp4")
    [passed] = await service.clips(PRODUCT_ID, tmp_path)
    assert (passed["status"], passed["qa_problem"]) == ("ready", "")

    await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    video.states["job2"] = JobState("completed", video_url="https://v/z.mp4")
    [unchecked] = await service.clips(PRODUCT_ID, tmp_path)
    assert (unchecked["status"], unchecked["qa_problem"]) == ("ready", "")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_clip_frames_are_three_stills_in_time_order(tmp_path) -> None:
    path = tmp_path / "clip.mp4"
    _make_clip(path, "red", seconds=4, audio=False)
    frames = await clip_frames(path, 4)
    assert len(frames) == 3 and all(frame[:2] == b"\xff\xd8" for frame in frames)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4"]
