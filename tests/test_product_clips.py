import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from tests.pgstore import knowledge_repository, product_repository

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.clips import (
    _STICKER_BOTTOM_LIMIT,
    _STICKER_TOP,
    _STICKER_TOPS,
    CHECK_FRAMES,
    ClipGenerationError,
    JobState,
    StitchClip,
    StitchUnavailable,
    VideoClient,
    _ducked_mix,
    _float_y,
    _handheld,
    _measured_loudnorm,
    _slide_in,
    caption_font,
    clip_frames,
    clip_seconds_for,
    cover_frame,
    sharpness,
    shot_seconds,
    still_tail_seconds,
    stitch,
)
from ai_content.domains.marketing.products.service import (
    NOT_CHECKED,
    HookClipPending,
    KeyframeUnavailable,
    ProductCatalogService,
)

PRODUCT_ID = "1730000000000000001"
SHOTS = [
    {"role": "hook", "motion_prompt": "push in"},
    {"role": "demo", "motion_prompt": "pan left"},
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
    repository = product_repository()
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
    lost = await _client(lambda request: httpx.Response(404)).status("v1", "m")
    assert lost.status == "failed" and "lost" in lost.error


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
async def test_stitch_joins_trimmed_clips_without_the_clips_own_audio(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("AIC_BGM_PATH", str(tmp_path / "no-music.wav"))
    clips = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"c{index}.mp4"
        _make_clip(path, color)
        clips.append(StitchClip(path, 2.0, "Phòng giặt gọn hơn" if index == 0 else ""))
    output = tmp_path / "videos" / "out.mp4"
    await stitch(clips, output)
    # each part is its source length (2.0 s minus the trims) shortened by the speed-up, so the
    # picture keeps the length the voice-over was cut to
    assert abs(float(_probe(output, "format=duration")) - 2 * shot_seconds(2.0)) < 0.15
    assert _probe(output, "stream=codec_type").split() == ["video"]
    assert sorted(p.name for p in output.parent.iterdir()) == ["out.mp4"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_cover_is_a_jpeg_frame_of_the_video(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "blue", seconds=3, audio=False)
    cover = tmp_path / "cover.jpg"
    await cover_frame(clip, cover)
    assert cover.read_bytes()[:2] == b"\xff\xd8"


def test_sticker_floats_only_after_the_spring_has_settled() -> None:
    expression = _float_y(170, 2.0, 1)
    assert expression.startswith("'170+")
    assert "min(1,max(0,t-2-0.5)/0.5)" in expression  # no drift until half a second after entry


def test_sticker_slides_back_out_to_the_left_edge_before_it_goes() -> None:
    entry, exit_ = _slide_in(1.0, 40), _slide_in(1.0, 40, leave=3.0)
    assert "pow(" not in entry
    assert "+pow(min(1,max(0,t-3)/0.25),2)" in exit_  # no movement until 3 s, done 0.25 s later


def test_handheld_drift_stays_inside_the_spare_picture() -> None:
    graph = _handheld()
    assert graph.startswith("scale=1104:1944,crop=1080:1920")
    # the crop origin is 12 +- 9 px at most, so it never leaves the 24 px of spare picture
    assert "x='12+6*sin(2.1*t)+3*sin(5.3*t)'" in graph


def test_sharpness_ranks_a_crisp_picture_above_a_blurred_one(tmp_path) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    crisp = Image.new("RGB", (120, 120), "white")
    ImageDraw.Draw(crisp).rectangle((30, 30, 90, 90), fill="black")
    crisp.save(tmp_path / "crisp.jpg")
    crisp.filter(ImageFilter.GaussianBlur(6)).save(tmp_path / "blur.jpg")
    assert sharpness(tmp_path / "crisp.jpg") > sharpness(tmp_path / "blur.jpg")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_cover_of_a_video_shorter_than_every_moment_still_exists(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "blue", seconds=0.3, audio=False)
    await cover_frame(clip, tmp_path / "cover.jpg")
    assert (tmp_path / "cover.jpg").read_bytes()[:2] == b"\xff\xd8"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.mp4", "cover.jpg"]


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


def test_the_music_fades_out_to_end_with_the_voice_over() -> None:
    assert "afade=t=out:st=3.200:d=0.8" in _ducked_mix(0, 1, ends_at=4.0)
    assert "afade" not in _ducked_mix(0, 1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stitch_fades_the_music_out_at_the_end(tmp_path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "green", seconds=6, audio=False)
    voice, music = tmp_path / "voice.wav", tmp_path / "music.wav"
    for path, tone in ((voice, "sine=frequency=150:duration=4"), (music, "sine=frequency=800:duration=10")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", tone, str(path)], check=True)  # fmt: skip
    output = tmp_path / "videos" / "out.mp4"
    await stitch([StitchClip(clip, 5.0)], output, voiceover=voice, bgm=music)

    def level(start: float) -> float:
        result = subprocess.run(
            ["ffmpeg", "-v", "info", "-ss", str(start), "-t", "0.2", "-i", str(output), "-vn",
             "-af", "highpass=f=700,highpass=f=700,lowpass=f=900,astats", "-f", "null", "-"],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        return float(re.findall(r"RMS level dB: (-?[\d.inf]+)", result.stderr)[-1])

    assert level(3.7) < level(1.0) - 6  # the 800 Hz music is much quieter near the end


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
    assert "in exact sync with the spoken Vietnamese" in video.submitted[0][0]
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
    from ai_content.domains.marketing.products.clips import clip_speed

    monkeypatch.delenv("AIC_CLIP_SPEED", raising=False)
    assert clip_speed() == 1.1 and round(shot_seconds(15), 2) == 13.41
    monkeypatch.setenv("AIC_CLIP_SPEED", "1")
    assert round(shot_seconds(15), 2) == 14.75
    monkeypatch.setenv("AIC_CLIP_SPEED", "9")
    assert clip_speed() == 2.0
    monkeypatch.setenv("AIC_CLIP_SPEED", "abc")
    assert clip_speed() == 1.1


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
    assert (unchecked["status"], unchecked["qa_problem"]) == ("ready", NOT_CHECKED)


async def test_a_flagged_clip_shows_its_problem_but_makes_no_rule(tmp_path, monkeypatch) -> None:
    from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService

    video = _FakeVideo()
    service = await _service(tmp_path, video)
    knowledge = CreativeKnowledgeService(knowledge_repository())
    service._knowledge = knowledge
    service._clip_checker = _FakeClipChecker(["long sleeves appear in frame 2", "", None])  # type: ignore[assignment]

    async def frames(path, seconds):
        return [b"a", b"b", b"c"]

    monkeypatch.setattr(service_module, "clip_frames", frames)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("completed", video_url="https://v/x.mp4")
    [flagged, *_] = await service.clips(PRODUCT_ID, tmp_path)
    assert flagged["qa_problem"] == "long sleeves appear in frame 2"
    assert await knowledge.repository.list() == []  # a defect of one clip is not a rule


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_clip_frames_are_stills_in_time_order(tmp_path) -> None:
    path = tmp_path / "clip.mp4"
    _make_clip(path, "red", seconds=4, audio=False)
    frames = await clip_frames(path, 4)
    assert len(frames) == CHECK_FRAMES and all(frame[:2] == b"\xff\xd8" for frame in frames)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4"]


async def test_a_clip_of_a_brief_without_a_person_forbids_people(tmp_path) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    record = await service._repository.get_brief(PRODUCT_ID)
    brief = {**record["brief"], "with_person": False}
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.generate_clips(PRODUCT_ID, tmp_path)
    assert "No person appears in the picture" in video.submitted[-1][0]

    await service._repository.save_brief(PRODUCT_ID, "", {**brief, "with_person": True}, "approved")
    await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    assert "No person appears" not in video.submitted[-1][0]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or caption_font() is None, reason="no ffmpeg or caption font"
)
async def test_stitch_burns_spoken_words_only_while_they_are_said(tmp_path) -> None:
    from ai_content.domains.marketing.products.captions import spoken_cues

    clip = tmp_path / "c.mp4"
    _make_clip(clip, "black", audio=False)
    output = tmp_path / "spoken.mp4"
    cues = tuple(spoken_cues("Gấp gọn trong 3 giây", 1.5))
    await stitch([StitchClip(clip, 3.0, cues=cues)], output)
    frame = lambda second: subprocess.run(  # noqa: E731
        ["ffmpeg", "-v", "error", "-ss", second, "-i", str(output), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    assert max(frame("0.7")) > 200 and max(frame("2.3")) < 20


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_a_hook_variant_reuses_the_clips_and_keeps_its_own_files(tmp_path) -> None:
    spoken: list[str] = []

    class _Speaker:
        async def speak(self, text, voice=None):
            spoken.append(text)
            return subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
                 "-f", "mp3", "-"], capture_output=True, check=True,
            ).stdout  # fmt: skip

    service = await _service(tmp_path, _FakeVideo())
    service._speaker = _Speaker()  # type: ignore[assignment]
    clip = tmp_path / "clips" / PRODUCT_ID / "shot_0.mp4"
    clip.parent.mkdir(parents=True)
    _make_clip(clip, "red", seconds=4, audio=False)
    await service._repository.save_clip(
        {
            "product_id": PRODUCT_ID, "shot_index": 0, "status": "ready", "job_id": "j",
            "job_model": "m", "video_path": f"clips/{PRODUCT_ID}/shot_0.mp4", "seconds": 5,
            "attempts": 1, "error": None, "qa_problem": "",
        }
    )  # fmt: skip
    await service._write_json(
        tmp_path,
        f"videos/{PRODUCT_ID}/hooks.json",
        {"hooks": [{"id": "hook_1", "angle": "question", "text": "Bạn đã thử chưa?"}]},
    )
    made = await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1")
    assert made == f"videos/{PRODUCT_ID}/hook_1/video.mp4"
    folder = tmp_path / "videos" / PRODUCT_ID
    assert "Bạn đã thử chưa?" in spoken
    assert (folder / "hook_1" / "video.mp4").is_file()
    assert (folder / "hook_1" / "voiceover.mp3").is_file()
    assert not (folder / "video.mp4").exists() and not (folder / "voiceover.mp3").exists()
    built = json.loads((folder / "hook_1" / "video.json").read_text(encoding="utf-8"))
    assert built["hook"] == "Bạn đã thử chưa?"
    assert [h["built"] for h in await service.hooks(PRODUCT_ID, tmp_path)] == [True]


def test_a_clip_is_cut_to_the_length_its_shot_should_have() -> None:
    from ai_content.domains.marketing.products.clips import clip_seconds_for

    assert abs(shot_seconds(clip_seconds_for(6.0)) - 6.0) < 1e-6


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_a_shot_is_cut_when_its_voice_over_ends_early(tmp_path) -> None:
    service = await _service(tmp_path, _FakeVideo())
    clip = tmp_path / "clips" / PRODUCT_ID / "shot_0.mp4"
    clip.parent.mkdir(parents=True)
    _make_clip(clip, "red", seconds=15, audio=False)
    await service._repository.save_clip(
        {
            "product_id": PRODUCT_ID, "shot_index": 0, "status": "ready", "job_id": "j",
            "job_model": "m", "video_path": f"clips/{PRODUCT_ID}/shot_0.mp4", "seconds": 15,
            "attempts": 1, "error": None, "qa_problem": "",
        }
    )  # fmt: skip
    await service.note_voice(PRODUCT_ID, tmp_path, "Kim Oanh", {"0": 2.0}, "", {"0": 3.0})
    await service.build_video(PRODUCT_ID, tmp_path)
    built = json.loads(
        (tmp_path / "videos" / PRODUCT_ID / "video.json").read_text(encoding="utf-8")
    )
    assert 2.9 < built["seconds"] < 3.1  # without the cut it would be 3.8


async def test_two_services_do_not_collect_the_same_clip_twice(tmp_path) -> None:
    downloads: list[int] = []

    class _Slow(_FakeVideo):
        async def download(self, video_url):
            downloads.append(1)
            await asyncio.sleep(0.01)
            return b"mp4-bytes"

    video = _Slow()
    first = await _service(tmp_path, video)
    await first.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("completed", video_url="https://v/x.mp4")
    second = ProductCatalogService(first._repository, videographer=video)
    await asyncio.gather(first.clips(PRODUCT_ID, tmp_path), second.clips(PRODUCT_ID, tmp_path))
    assert len(downloads) == 1


async def test_a_flagged_clip_can_be_accepted_as_it_is(tmp_path) -> None:
    service = await _service(tmp_path, _FakeVideo())
    clip = {
        "product_id": PRODUCT_ID,
        "shot_index": 0,
        "status": "ready",
        "job_id": "j",
        "job_model": "m",
        "video_path": "clips/x.mp4",
        "seconds": 15,
        "attempts": 1,
        "error": None,
        "qa_problem": "six fingers in frame 4",
    }
    await service._repository.save_clip(clip)
    assert not await service.accept_clip(PRODUCT_ID, 1)
    assert await service.accept_clip(PRODUCT_ID, 0)
    assert (await service._repository.list_clips(PRODUCT_ID))[0]["qa_problem"] == ""
    events = await service.events(PRODUCT_ID)
    assert events[-1]["status"] == "accepted" and "six fingers" in events[-1]["message"]


async def test_an_unchecked_clip_can_be_checked_again_without_a_new_clip(
    tmp_path, monkeypatch
) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    service._clip_checker = _FakeClipChecker([None, ""])

    async def frames(path, seconds):
        return [b"a"]

    monkeypatch.setattr(service_module, "clip_frames", frames)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("completed", video_url="https://v/x.mp4")
    [unchecked] = await service.clips(PRODUCT_ID, tmp_path)
    assert unchecked["qa_problem"] == NOT_CHECKED

    assert (await service.recheck_clip(PRODUCT_ID, 0, tmp_path))["qa_problem"] == ""
    assert (await service.clips(PRODUCT_ID, tmp_path))[0]["qa_problem"] == ""
    assert len(video.submitted) == 1
    assert await service.recheck_clip(PRODUCT_ID, 1, tmp_path) is None


async def test_a_skin_product_clip_is_checked_against_the_skin_in_the_photos(
    tmp_path, monkeypatch
) -> None:
    from ai_content.domains.marketing.products.keyframes import KEEP_SKIN_NOTE

    video = _FakeVideo()
    service = await _service(tmp_path, video)
    brief = {"title": "b", "shots": SHOTS, "skin_sensitive": True}
    await service._repository.save_brief(PRODUCT_ID, "", brief, "approved")
    checker = _FakeClipChecker([""])
    service._clip_checker = checker

    async def frames(path, seconds):
        return [b"a"]

    monkeypatch.setattr(service_module, "clip_frames", frames)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("completed", video_url="https://v/x.mp4")
    await service.clips(PRODUCT_ID, tmp_path)
    assert KEEP_SKIN_NOTE in checker.calls[0][0]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_a_video_without_a_voice_over_still_gets_the_background_music(
    tmp_path, monkeypatch
) -> None:
    music = tmp_path / "music.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1", str(music)],
        check=True,
    )
    monkeypatch.setenv("AIC_BGM_PATH", str(music))
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", audio=False)
    output = tmp_path / "out.mp4"
    await stitch([StitchClip(clip, 3.0)], output)
    assert sorted(_probe(output, "stream=codec_type").split()) == ["audio", "video"]


async def test_a_hook_on_a_talking_opening_films_its_own_clip_first(
    tmp_path, monkeypatch
) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    shots = [{**SHOTS[0], "delivery": "talking", "voiceover": "old words"}, SHOTS[1]]
    await service._repository.save_brief(PRODUCT_ID, "", {"title": "b", "shots": shots}, "approved")
    await service._repository.save_keyframe(
        {
            "product_id": PRODUCT_ID,
            "shot_index": 0,
            "status": "approved",
            "prompt": "p",
            "image_path": "frame0.jpg",
            "attempts": 1,
            "error": None,
            "qa_problem": "",
        }
    )
    await service._write_json(
        tmp_path,
        f"videos/{PRODUCT_ID}/hooks.json",
        {"hooks": [{"id": "hook_1", "angle": "question", "text": "Bạn đã thử chưa?"}]},
    )
    seen: dict[str, object] = {}

    async def voiceover(product_id, media_root, voice=None, variant="", hook="", opening_clip=None):
        seen["voiceover"] = (hook, opening_clip)

    async def build(product_id, media_root, captions=False, stickers=False, **options):
        seen["build"] = options
        return "built.mp4"

    monkeypatch.setattr(service, "create_voiceover", voiceover)
    monkeypatch.setattr(service, "build_video", build)

    with pytest.raises(HookClipPending):  # the first call starts filming
        await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1")
    [(prompt, _)] = video.submitted
    assert 'says in Vietnamese, in one go: "Bạn đã thử chưa?"' in prompt and "old words" not in prompt
    assert [h["filming"] for h in await service.hooks(PRODUCT_ID, tmp_path)] == [True]
    with pytest.raises(HookClipPending):  # still being filmed: no second clip is paid for
        await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1")
    assert len(video.submitted) == 1 and not seen

    video.states["job0"] = JobState("completed", video_url="https://v/h.mp4")
    assert await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1") == "built.mp4"
    clip = tmp_path / "videos" / PRODUCT_ID / "hook_1" / "shot_0.mp4"
    assert clip.read_bytes() == b"mp4-bytes"
    assert seen["voiceover"] == ("Bạn đã thử chưa?", clip) and seen["build"]["opening_clip"] == clip
    assert [h["filming"] for h in await service.hooks(PRODUCT_ID, tmp_path)] == [False]
    assert len(video.submitted) == 1


async def test_a_failed_opening_clip_is_reported_and_asked_for_again_on_the_next_try(
    tmp_path,
) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    shots = [{**SHOTS[0], "delivery": "talking"}, SHOTS[1]]
    await service._repository.save_brief(PRODUCT_ID, "", {"title": "b", "shots": shots}, "approved")
    await service._repository.save_keyframe(
        {
            "product_id": PRODUCT_ID,
            "shot_index": 0,
            "status": "approved",
            "prompt": "p",
            "image_path": "frame0.jpg",
            "attempts": 1,
            "error": None,
            "qa_problem": "",
        }
    )
    await service._write_json(
        tmp_path,
        f"videos/{PRODUCT_ID}/hooks.json",
        {"hooks": [{"id": "hook_1", "angle": "question", "text": "Bạn đã thử chưa?"}]},
    )
    with pytest.raises(HookClipPending):
        await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1")
    video.states["job0"] = JobState("failed", error="policy")
    with pytest.raises(KeyframeUnavailable, match="opening clip failed: policy"):
        await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1")
    with pytest.raises(HookClipPending):  # a new try films it again
        await service.build_hook_video(PRODUCT_ID, tmp_path, "hook_1")
    assert len(video.submitted) == 2


async def test_the_opening_clip_of_a_hook_replaces_the_first_clip_in_the_video(
    tmp_path, monkeypatch
) -> None:
    service = await _service(tmp_path, _FakeVideo())
    for index in range(2):
        await service.set_keyframe_status(PRODUCT_ID, index, "approved")
        clip = tmp_path / f"clips/{PRODUCT_ID}/shot_{index}.mp4"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"mp4")
        await service._repository.save_clip(
            {
                "product_id": PRODUCT_ID,
                "shot_index": index,
                "status": "ready",
                "job_id": "j",
                "job_model": "m",
                "video_path": f"clips/{PRODUCT_ID}/shot_{index}.mp4",
                "seconds": 15,
                "attempts": 1,
                "error": None,
                "qa_problem": "",
            }
        )
    stitched: list[Path] = []

    async def fake_stitch(parts, output, voice=None, bgm=None, music=True):
        stitched.extend(part.path for part in parts)

    async def fake_cover(video, output):
        return None

    async def fake_measure(video, voice=None):
        return None

    monkeypatch.setattr(service_module, "stitch", fake_stitch)
    monkeypatch.setattr(service_module, "cover_frame", fake_cover)
    monkeypatch.setattr(service_module, "measure", fake_measure)
    monkeypatch.setattr(service_module, "judge", lambda *a, **k: {"score": 100, "issues": []})
    opening = tmp_path / "hook-opening.mp4"
    opening.write_bytes(b"mp4")
    await service.build_video(PRODUCT_ID, tmp_path, variant="hook_1", hook="Bạn đã thử chưa?", opening_clip=opening)
    assert stitched == [opening, tmp_path / f"clips/{PRODUCT_ID}/shot_1.mp4"]


async def test_the_first_frame_goes_only_under_the_fields_that_are_set() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "v1"})

    wide = VideoClient(
        base_url="https://api.example/v1",
        api_key="k",
        model="m",
        frame_fields=("image", "input_reference", "image_url"),
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await _client(handler).submit("p", b"x", 6)
    await wide.submit("p", b"x", 6)
    narrow, wide = bodies
    assert "image" in narrow and "input_reference" not in narrow and "image_url" not in narrow
    assert narrow["image"] == wide["image"] == wide["input_reference"] == wide["image_url"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stitch_slides_a_sticker_in_instead_of_popping_it(tmp_path, monkeypatch) -> None:
    from PIL import Image

    monkeypatch.setenv("AIC_BGM_PATH", str(tmp_path / "no-music.wav"))
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", seconds=4, audio=False)
    sticker = tmp_path / "sticker.png"
    Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(sticker)
    output = tmp_path / "out.mp4"
    await stitch([StitchClip(clip, 3.0, stickers=(sticker,))], output)

    def white_pixels(moment: float) -> int:
        frame = tmp_path / f"frame_{moment}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(moment), "-i", str(output),
             "-frames:v", "1", str(frame)],
            check=True,
        )  # fmt: skip
        pixels = Image.open(frame).convert("RGB").getdata()
        return sum(1 for r, g, b in pixels if r > 240 and g > 240 and b > 240)

    before, sliding, settled = white_pixels(0.3), white_pixels(0.6), white_pixels(1.5)
    assert before == 0
    assert 0 < sliding < settled

    later = tmp_path / "later.mp4"
    await stitch([StitchClip(clip, 3.0, stickers=(sticker,), sticker_at=1.5)], later)
    output = later
    assert white_pixels(1.0) == 0  # the sticker waits for the moment it is told
    assert white_pixels(1.9) > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stickers_come_in_one_after_another_and_slide_out_at_the_end(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("AIC_BGM_PATH", str(tmp_path / "no-music.wav"))
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", seconds=4, audio=False)
    white, blue = tmp_path / "white.png", tmp_path / "blue.png"
    Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(white)
    Image.new("RGBA", (200, 100), (0, 0, 255, 255)).save(blue)
    output = tmp_path / "out.mp4"
    await stitch([StitchClip(clip, 3.0, stickers=(white, blue), sticker_at=1.0)], output)

    def pixels_of(moment: float, color: tuple[int, int, int]) -> int:
        frame = tmp_path / f"frame_{moment}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(moment), "-i", str(output),
             "-frames:v", "1", str(frame)],
            check=True,
        )  # fmt: skip
        found = Image.open(frame).convert("RGB").getdata()
        return sum(1 for px in found if all(abs(a - b) < 20 for a, b in zip(px, color, strict=True)))

    assert pixels_of(1.2, (255, 255, 255)) > pixels_of(1.2, (0, 0, 255)) > 0  # the second is behind
    settled = pixels_of(1.9, (255, 255, 255))
    assert pixels_of(1.9, (0, 0, 255)) == settled  # both have landed by now
    leaving = shot_seconds(3.0) - 0.3 - 0.12
    assert pixels_of(leaving, (255, 255, 255)) < settled  # sliding out, not popping out


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_still_tail_measures_a_clip_that_ends_frozen(tmp_path) -> None:
    moving, frozen = tmp_path / "moving.mp4", tmp_path / "frozen.mp4"
    for path, extra in ((moving, []), (frozen, ["-vf", "tpad=stop_mode=clone:stop_duration=2"])):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x284:d=2:r=24",
             *extra, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )  # fmt: skip
    assert await still_tail_seconds(moving) == 0.0
    assert 1.5 < await still_tail_seconds(frozen) < 2.5


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_loudnorm_is_filled_in_with_the_audios_own_measurements(tmp_path) -> None:
    voice, silence = tmp_path / "voice.wav", tmp_path / "silence.wav"
    for path, source in ((voice, "sine=frequency=300:duration=3"), (silence, "anullsrc=d=3")):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, str(path)], check=True
        )
    measured = await _measured_loudnorm(["-i", str(voice)], "[0:a]anull[pre]")
    assert "measured_I=" in measured and "linear=true" in measured
    plain = await _measured_loudnorm(["-i", str(silence)], "[0:a]anull[pre]")
    assert plain == "loudnorm=I=-14:LRA=11:TP=-1"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_every_part_lasts_as_long_as_its_voice_over_so_later_shots_do_not_drift(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("AIC_BGM_PATH", str(tmp_path / "no-music.wav"))
    clips = []
    for index, (color, voiced) in enumerate((("red", 1.0), ("blue", 1.5), ("green", 1.0))):
        path = tmp_path / f"c{index}.mp4"
        _make_clip(path, color, seconds=4, audio=False)
        clips.append(StitchClip(path, clip_seconds_for(voiced)))
    output = tmp_path / "out" / "out.mp4"
    await stitch(clips, output)
    assert abs(float(_probe(output, "format=duration")) - 3.5) < 0.12


async def test_a_flagged_clip_is_made_again_with_only_its_problem_to_fix(tmp_path) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    first = video.submitted[0][0]
    assert "No morphing, warping, flicker or ghosting" in first
    assert "One continuous take with no cuts or dissolves" in first
    assert "no icon, symbol, logo or graphic drawn on the picture" in first
    assert "Keep the product's exact shape" in first and "fix only this problem" not in first

    clip = (await service._repository.list_clips(PRODUCT_ID))[0]
    problem = "Frame 3: the left hand has six fingers."
    await service._repository.save_clip({**clip, "qa_problem": problem})
    await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    assert f"fix only this problem of the last version: {problem}" in video.submitted[-1][0]

    await service._repository.save_clip({**clip, "qa_problem": NOT_CHECKED})
    await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    last = video.submitted[-1][0]
    assert "fix only this problem" not in last  # nothing was found, nothing to fix


async def test_the_prompt_sent_for_a_clip_is_kept_next_to_it(tmp_path) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    kept = (tmp_path / "clips" / PRODUCT_ID / "shot_0.prompt.txt").read_text(encoding="utf-8")
    assert kept == video.submitted[0][0]


async def test_a_clip_shorter_than_asked_for_is_remembered_with_its_real_length(
    tmp_path, monkeypatch
) -> None:
    from ai_content.domains.marketing.products import service as service_module

    video = _FakeVideo()
    service = await _service(tmp_path, video)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    video.states["job0"] = JobState("completed", video_url="https://x/clip.mp4")

    async def real_length(_path) -> float:
        return 12.4

    monkeypatch.setattr(service_module, "video_seconds", real_length)
    [clip, *_] = await service.clips(PRODUCT_ID, tmp_path)
    assert clip["status"] == "ready" and clip["seconds"] == 12


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_video_seconds_reads_the_real_length_and_zero_when_unreadable(tmp_path) -> None:
    from ai_content.domains.marketing.products.clips import video_seconds

    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", seconds=3, audio=False)
    assert abs(await video_seconds(clip) - 3.0) < 0.1
    broken = tmp_path / "b.mp4"
    broken.write_bytes(b"mp4-bytes")
    assert await video_seconds(broken) == 0.0


async def test_a_clip_flagged_only_because_its_script_changed_is_not_given_a_problem_to_fix(
    tmp_path,
) -> None:
    video = _FakeVideo()
    service = await _service(tmp_path, video)
    await service.generate_clips(PRODUCT_ID, tmp_path)
    clip = (await service._repository.list_clips(PRODUCT_ID))[0]
    stale = "The script of this scene changed after it was filmed"
    await service._repository.save_clip({**clip, "qa_problem": stale})
    await service.generate_clips(PRODUCT_ID, tmp_path, shot_index=0)
    assert "fix only this problem" not in video.submitted[-1][0]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_the_picture_moves_closer_only_in_the_windows_it_is_given(
    tmp_path, monkeypatch
) -> None:
    from PIL import Image, ImageChops, ImageStat

    monkeypatch.setenv("AIC_BGM_PATH", str(tmp_path / "no-music.wav"))
    clip = tmp_path / "c.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x568:d=5:r=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip
    output = tmp_path / "out.mp4"
    await stitch([StitchClip(clip, clip_seconds_for(3.0), zoom=((1.5, 2.5),))], output)

    def frame(moment: float) -> Image.Image:
        path = tmp_path / f"f_{moment}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(moment), "-i", str(output),
             "-frames:v", "1", str(path)],
            check=True,
        )  # fmt: skip
        return Image.open(path).convert("RGB")

    def change(a: Image.Image, b: Image.Image) -> float:
        return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3

    wide, still_wide, closer = frame(0.5), frame(0.6), frame(2.0)
    assert change(wide, still_wide) < 8 < change(wide, closer)  # the test picture barely moves by itself


def _loudest(path, start: float, length: float) -> float:
    """The peak level in dB of `length` seconds of a file's audio from `start`."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(length), "-i", str(path),
         "-af", "volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    found = re.search(r"max_volume: (-?[\d.]+|-inf) dB", result.stderr)
    return -120.0 if found is None else float(found.group(1))


def _silent_voice(path, seconds: int) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=d={seconds}", str(path)],
        check=True,
    )  # fmt: skip


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_a_whoosh_is_heard_on_the_cut_between_shots(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIC_BGM_PATH", str(tmp_path / "no-music.wav"))
    first, second = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _make_clip(first, "red", seconds=5, audio=False)
    _make_clip(second, "blue", seconds=5, audio=False)
    voice = tmp_path / "voice.wav"
    _silent_voice(voice, 8)
    output = tmp_path / "out.mp4"
    await stitch([StitchClip(first, 3.0), StitchClip(second, 3.0)], output, voiceover=voice)
    cut = shot_seconds(3.0)
    assert _loudest(output, cut - 0.3, 0.5) > -40  # the swell on the cut
    assert _loudest(output, 0.0, 1.0) < -60  # and nothing where nothing happens


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_the_music_can_be_left_out(tmp_path, monkeypatch) -> None:
    music = tmp_path / "music.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=5",
         str(music)],
        check=True,
    )  # fmt: skip
    monkeypatch.setenv("AIC_BGM_PATH", str(music))
    clip = tmp_path / "c.mp4"
    _make_clip(clip, "red", seconds=5, audio=False)
    voice = tmp_path / "voice.wav"
    _silent_voice(voice, 4)
    with_music, without = tmp_path / "with.mp4", tmp_path / "without.mp4"
    await stitch([StitchClip(clip, 3.0)], with_music, voiceover=voice)
    await stitch([StitchClip(clip, 3.0)], without, voiceover=voice, music=False)
    assert _loudest(with_music, 0.5, 1.0) > -30
    assert _loudest(without, 0.5, 1.0) < -60


def test_stickers_stay_between_the_status_bar_and_the_captions() -> None:
    from ai_content.domains.marketing.products.captions import CAPTION_BOTTOM

    assert _STICKER_TOP >= 168
    assert min(_STICKER_TOPS) >= 168
    assert _STICKER_BOTTOM_LIMIT <= CAPTION_BOTTOM - 2 * 100  # two caption lines are about 200 px
