from pathlib import Path

import pytest

from ai_content.domains.marketing.products.pipeline import PipelineStopped, run_pipeline

PRODUCT_ID = "1730000000000000001"


def _keyframe(index: int, status: str, qa_problem: str = "", error: str | None = None) -> dict:
    return {"shot_index": index, "status": status, "qa_problem": qa_problem, "error": error}


def _clip(index: int, status: str, qa_problem: str = "", error: str | None = None) -> dict:
    return {"shot_index": index, "status": status, "qa_problem": qa_problem, "error": error}


class _FakeService:
    def __init__(self, shots: int = 2) -> None:
        self.calls: list[str] = []
        self.shots = shots
        self.brief_status = "draft"
        self.keyframes: list[dict] = []
        self.made_keyframes = [_keyframe(i, "ready") for i in range(shots)]
        self.clip_states: list[list[dict]] = [[_clip(i, "ready") for i in range(shots)]]
        self.has_brief = False
        self.restarted: list[int] = []

    def _record(self) -> dict:
        brief = {"shots": [{}] * self.shots}
        return {"product_id": PRODUCT_ID, "status": self.brief_status, "brief": brief}

    async def get_brief(self, product_id):
        return self._record() if self.has_brief else None

    async def persona_photos(self, product_id, media_root):
        return [b"face"]

    async def create_brief(self, product_id, idea, video_seconds, person_photos):
        self.calls.append(f"create_brief:{video_seconds}:{len(person_photos)}")
        self.has_brief = True
        return self._record()

    async def update_brief(self, product_id, changes, status):
        self.calls.append(f"update_brief:{status}")
        self.brief_status = status
        return self._record()

    async def list_keyframes(self, product_id):
        return self.keyframes

    async def generate_keyframes(self, product_id, media_root, shot_index=None):
        self.calls.append(f"generate_keyframes:{shot_index}")
        return self.made_keyframes

    async def set_keyframe_status(self, product_id, index, status):
        self.calls.append(f"keyframe:{index}:{status}")
        return True

    async def clips(self, product_id, media_root):
        self.calls.append("clips")
        states = self.clip_states
        return states.pop(0) if len(states) > 1 else states[0]

    async def generate_clips(self, product_id, media_root, shot_index=None):
        self.calls.append("generate_clips")
        if shot_index is not None:
            self.restarted.append(shot_index)

    async def create_voiceover(self, product_id, media_root, voice):
        self.calls.append(f"voiceover:{voice}")

    async def build_video(self, product_id, media_root, captions):
        self.calls.append("build_video")

    async def create_post_package(self, product_id):
        self.calls.append("post_package")


async def _run(service: _FakeService, steps: list[str] | None = None) -> None:
    await run_pipeline(
        service,  # type: ignore[arg-type]
        PRODUCT_ID,
        Path("."),
        idea="",
        video_seconds=30,
        voice="hamy.mp3",
        report=(steps if steps is not None else []).append,
        poll_seconds=0,
        busy_wait_seconds=0,
    )


async def test_a_fresh_run_goes_through_every_stage_in_order() -> None:
    service = _FakeService()
    service.clip_states = [[], [_clip(0, "ready"), _clip(1, "ready")]]
    steps: list[str] = []
    await _run(service, steps)
    assert service.calls == [
        "create_brief:30:1",
        "update_brief:approved",
        "generate_keyframes:0",
        "keyframe:0:approved",
        "generate_keyframes:None",
        "keyframe:1:approved",
        "clips",
        "generate_clips",
        "clips",
        "voiceover:hamy.mp3",
        "build_video",
        "post_package",
    ]
    assert steps[0] == "Writing storyboard brief" and steps[-1].startswith("Writing TikTok")


async def test_a_repeated_run_keeps_what_is_already_made() -> None:
    service = _FakeService()
    service.has_brief = True
    service.brief_status = "approved"
    service.keyframes = [_keyframe(0, "approved")]
    service.made_keyframes = [_keyframe(0, "approved"), _keyframe(1, "approved")]
    service.clip_states = [[_clip(0, "ready"), _clip(1, "processing")]]
    service.clip_states.append([_clip(0, "ready"), _clip(1, "ready")])
    await _run(service)
    assert not any(call.startswith("create_brief") for call in service.calls)
    assert "generate_clips" not in service.calls
    assert not any(call.startswith("keyframe:") for call in service.calls)
    assert service.calls.count("generate_keyframes:0") == 0
    assert service.calls[-3:] == ["voiceover:hamy.mp3", "build_video", "post_package"]


@pytest.mark.parametrize(
    ("made", "message"),
    [
        ([_keyframe(0, "failed", error="HTTP 503")], "Master keyframe failed: HTTP 503"),
        ([_keyframe(0, "ready", "wrong color")], "Master keyframe needs a look (wrong color)"),
    ],
)
async def test_a_bad_master_keyframe_stops_the_run_before_it_is_approved(made, message) -> None:
    service = _FakeService()
    service.made_keyframes = made
    with pytest.raises(PipelineStopped, match=message.replace("(", r"\(").replace(")", r"\)")):
        await _run(service)
    assert "keyframe:0:approved" not in service.calls


async def test_flagged_and_failed_follow_up_keyframes_are_not_approved() -> None:
    service = _FakeService(shots=3)
    service.keyframes = [_keyframe(0, "approved")]
    service.made_keyframes = [
        _keyframe(0, "approved"),
        _keyframe(1, "ready"),
        _keyframe(2, "ready", "extra hand"),
    ]
    with pytest.raises(PipelineStopped, match="shot 3"):
        await _run(service)
    assert "keyframe:1:approved" in service.calls
    assert "keyframe:2:approved" not in service.calls
    assert "generate_clips" not in service.calls


async def test_failed_or_flagged_clips_stop_the_run_before_the_voice() -> None:
    failed = _FakeService()
    failed.clip_states = [[_clip(0, "ready"), _clip(1, "failed", error="job failed")]]
    with pytest.raises(PipelineStopped, match="clip of shot 2 failed: job failed"):
        await _run(failed)

    flagged = _FakeService()
    flagged.clip_states = [[_clip(0, "ready", "melted product"), _clip(1, "ready")]]
    with pytest.raises(PipelineStopped, match="shot 1 looks wrong"):
        await _run(flagged)
    assert not any(call.startswith("voiceover") for call in flagged.calls)


_BUSY = "Hệ thống đang xử lý lượng lớn yêu cầu cùng lúc. Vui lòng thử lại"


async def test_clips_refused_as_busy_are_sent_again_one_at_a_time_until_they_work() -> None:
    service = _FakeService(shots=3)
    service.clip_states = [
        [],  # the first look, before any clip is started
        [_clip(0, "ready"), _clip(1, "failed", error=_BUSY), _clip(2, "failed", error=_BUSY)],
        [_clip(0, "ready"), _clip(1, "processing"), _clip(2, "failed", error=_BUSY)],
        [_clip(i, "ready") for i in range(3)],
    ]
    steps: list[str] = []
    await _run(service, steps)
    assert service.restarted == [1, 2, 2]
    assert "Video service is busy, trying again shortly" in steps
    assert service.calls[-3:] == ["voiceover:hamy.mp3", "build_video", "post_package"]


async def test_clips_that_stay_busy_stop_the_run_instead_of_retrying_forever() -> None:
    service = _FakeService()
    service.clip_states = [[_clip(0, "ready"), _clip(1, "failed", error=_BUSY)]]
    with pytest.raises(PipelineStopped, match="stayed overloaded"):
        await _run(service)
    assert len(service.restarted) == 15
    assert not any(call.startswith("voiceover") for call in service.calls)


async def test_a_run_until_images_stops_with_the_follow_up_shots_left_for_review() -> None:
    service = _FakeService()
    service.made_keyframes = [_keyframe(0, "ready", "faint skin marks"), _keyframe(1, "ready")]
    steps: list[str] = []
    await run_pipeline(
        service,  # type: ignore[arg-type]
        PRODUCT_ID,
        Path("."),
        idea="",
        video_seconds=30,
        voice=None,
        report=steps.append,
        poll_seconds=0,
        until="images",
    )
    assert service.calls == [
        "create_brief:30:1",
        "update_brief:approved",
        "generate_keyframes:0",
        "keyframe:0:approved",
        "generate_keyframes:None",
    ]
