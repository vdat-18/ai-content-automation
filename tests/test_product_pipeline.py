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
        self.matched = True  # a new script has no references until they are matched
        self.restarted: list[int] = []

    def _record(self) -> dict:
        references = ["ref" if self.matched else None] * self.shots
        brief = {"shots": [{}] * self.shots, "shot_references": references}
        return {"product_id": PRODUCT_ID, "status": self.brief_status, "brief": brief}

    async def get_brief(self, product_id):
        return self._record() if self.has_brief else None

    async def brief_persona(self, media_root, persona_id=None):
        return "p1", [b"face"]

    async def create_brief(self, product_id, idea, video_seconds, person_photos, persona_id):
        self.calls.append(f"create_brief:{video_seconds}:{len(person_photos)}")
        self.has_brief = True
        self.matched = False
        return self._record()

    async def match_references(self, product_id):
        self.calls.append("match_references")
        self.matched = True
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

    async def build_video(self, product_id, media_root, captions, stickers):
        self.calls.append("build_video")
        self.built_with = (captions, stickers)

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
    )


def _ready_to_film(service: _FakeService) -> _FakeService:
    """A product whose script exists and whose every image a person has approved."""
    service.has_brief = True
    service.keyframes = [_keyframe(i, "approved") for i in range(service.shots)]
    return service


async def test_a_run_goes_through_every_stage_in_order_once_the_images_are_approved() -> None:
    service = _ready_to_film(_FakeService())
    service.clip_states = [[], [_clip(0, "ready"), _clip(1, "ready")]]
    steps: list[str] = []
    await _run(service, steps)
    assert service.calls == [
        "clips",
        "generate_clips",
        "clips",
        "generate_clips",
        "clips",
        "voiceover:hamy.mp3",
        "build_video",
        "post_package",
    ]
    assert steps[0].startswith("Creating video clips") and steps[-1].startswith("Writing TikTok")
    assert service.restarted == [0]  # the first clip is made alone, then the rest


async def test_a_bad_first_clip_stops_the_run_before_the_rest_are_made() -> None:
    service = _ready_to_film(_FakeService())
    service.clip_states = [[], [_clip(0, "ready", qa_problem="the product is missing")]]
    with pytest.raises(PipelineStopped, match="shot 1 looks wrong"):
        await _run(service)
    assert service.calls.count("generate_clips") == 1


async def test_a_repeated_run_keeps_what_is_already_made() -> None:
    service = _ready_to_film(_FakeService())
    service.clip_states = [[_clip(0, "ready"), _clip(1, "processing")]]
    service.clip_states.append([_clip(0, "ready"), _clip(1, "ready")])
    await _run(service)
    assert not any(call.startswith(("create_brief", "match_references")) for call in service.calls)
    assert "generate_clips" not in service.calls
    assert not any(call.startswith(("keyframe:", "generate_keyframes")) for call in service.calls)
    assert service.calls[-3:] == ["voiceover:hamy.mp3", "build_video", "post_package"]
    assert service.built_with == (True, True)  # captions and stickers are on by default


async def test_a_run_to_the_video_stops_while_an_image_is_not_approved_and_approves_nothing() -> None:
    service = _FakeService(shots=3)
    service.has_brief = True
    service.keyframes = [_keyframe(0, "approved"), _keyframe(1, "ready"), _keyframe(2, "approved")]
    with pytest.raises(PipelineStopped, match="Approve the images of shot 2"):
        await _run(service)
    assert service.calls == []

    first = _FakeService()
    first.has_brief = True
    first.keyframes = [_keyframe(0, "ready")]
    with pytest.raises(PipelineStopped, match="Approve the first image"):
        await _run(first)
    assert first.calls == []  # nothing is made or approved behind the person's back


async def test_failed_or_flagged_clips_stop_the_run_before_the_voice() -> None:
    failed = _ready_to_film(_FakeService())
    failed.clip_states = [[_clip(0, "ready"), _clip(1, "failed", error="job failed")]]
    with pytest.raises(PipelineStopped, match="clip of shot 2 failed: job failed"):
        await _run(failed)

    flagged = _ready_to_film(_FakeService())
    flagged.clip_states = [[_clip(0, "ready", "melted product"), _clip(1, "ready")]]
    with pytest.raises(PipelineStopped, match="shot 1 looks wrong"):
        await _run(flagged)
    assert not any(call.startswith("voiceover") for call in flagged.calls)


async def test_a_clip_the_video_service_refused_stops_the_run_with_its_message() -> None:
    service = _ready_to_film(_FakeService(shots=3))
    service.clip_states = [
        [_clip(0, "ready"), _clip(1, "failed", error="HTTP 503: overloaded"), _clip(2, "ready")],
    ]
    with pytest.raises(PipelineStopped, match="shot 2 failed: HTTP 503: overloaded"):
        await _run(service)
    assert service.restarted == [] and not any(c.startswith("voiceover") for c in service.calls)


async def _run_until(service: _FakeService, until: str) -> None:
    await run_pipeline(
        service,  # type: ignore[arg-type]
        PRODUCT_ID,
        Path("."),
        idea="",
        video_seconds=30,
        voice=None,
        report=lambda step: None,
        poll_seconds=0,
        until=until,
    )


async def test_a_run_until_the_script_writes_it_and_chooses_the_references_only() -> None:
    service = _FakeService()
    await _run_until(service, "script")
    assert service.calls == ["create_brief:30:1", "match_references"]
    assert service.brief_status == "draft"  # a person approves the script


async def test_a_script_left_without_references_gets_them_on_the_next_run() -> None:
    service = _FakeService()
    service.has_brief = True
    service.matched = False  # the run that wrote this script stopped before matching
    await _run_until(service, "images")
    assert service.calls[:2] == ["match_references", "generate_keyframes:0"]


async def test_a_fresh_run_until_images_makes_the_first_image_and_stops_for_a_person() -> None:
    service = _FakeService()
    await _run_until(service, "images")
    assert service.calls == ["create_brief:30:1", "match_references", "generate_keyframes:0"]
    assert service.brief_status == "draft"


async def test_a_flagged_first_image_is_left_for_the_person_not_approved() -> None:
    service = _FakeService()
    service.made_keyframes = [_keyframe(0, "ready", "faint skin marks"), _keyframe(1, "ready")]
    await _run_until(service, "images")
    assert not any(call.startswith("keyframe:") for call in service.calls)
    assert "generate_keyframes:None" not in service.calls


async def test_a_failed_first_image_stops_the_run() -> None:
    service = _FakeService()
    service.made_keyframes = [_keyframe(0, "failed", error="HTTP 503")]
    with pytest.raises(PipelineStopped, match="Master keyframe failed: HTTP 503"):
        await _run_until(service, "images")


async def test_the_other_images_wait_until_the_first_one_is_approved() -> None:
    service = _FakeService()
    service.has_brief = True
    service.keyframes = [_keyframe(0, "ready")]
    with pytest.raises(PipelineStopped, match="Approve the first image"):
        await _run_until(service, "images")
    assert service.calls == []

    approved = _FakeService()
    approved.has_brief = True
    approved.keyframes = [_keyframe(0, "approved")]
    await _run_until(approved, "images")
    assert approved.calls == ["generate_keyframes:None"]  # and none of them is approved for you
