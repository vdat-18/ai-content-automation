"""Run the whole video pipeline for one product on the server, one stage after another."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from .briefing import BriefGenerationError, BriefUnavailable
from .clips import StitchUnavailable, is_busy_error
from .posting import PostingPackageError
from .references import ProfileGenerationError
from .service import KeyframeUnavailable, ProductCatalogService

CLIP_POLL_SECONDS = 5.0
CLIP_WAIT_SECONDS = 20 * 60
# The video service sometimes refuses jobs for a while ("busy, retry"); wait and send them again.
CLIP_BUSY_WAIT_SECONDS = 60.0
CLIP_BUSY_RETRIES = 15

# Stops that are expected: the message tells the user what to do before running again.
EXPECTED_STOPS = (
    BriefUnavailable,
    BriefGenerationError,
    ProfileGenerationError,
    KeyframeUnavailable,
    StitchUnavailable,
    PostingPackageError,
)


class PipelineStopped(RuntimeError):
    """The run cannot go on without the user; the message says what to look at."""


async def run_pipeline(
    service: ProductCatalogService,
    product_id: str,
    media_root: Path,
    *,
    idea: str,
    video_seconds: int,
    voice: str | None,
    report: Callable[[str], None],
    poll_seconds: float = CLIP_POLL_SECONDS,
    busy_wait_seconds: float = CLIP_BUSY_WAIT_SECONDS,
    until: str = "video",
) -> None:
    """Brief, person, keyframes, clips, voice-over, video and post text, resuming what exists.

    Anything already approved or made is kept. The run stops with PipelineStopped when a
    result needs a human look (a failed or flagged image or clip) instead of paying for more.
    With until="images" it ends once every image exists, leaving the follow-up shots for review.
    """
    record = await service.get_brief(product_id)
    if record is None:
        report("Writing storyboard brief")
        record = await service.create_brief(
            product_id,
            idea,
            video_seconds,
            await service.persona_photos(product_id, media_root),
        )
        if record is None:
            raise PipelineStopped("Product not captured")
    if record["status"] != "approved":
        report("Approving brief")
        record = await service.update_brief(product_id, {}, "approved")
        assert record is not None
    brief = record["brief"]
    shot_count = len(brief.get("shots") or [])

    keyframes = {k["shot_index"]: k for k in await service.list_keyframes(product_id)}
    if keyframes.get(0, {}).get("status") != "approved":
        report("Generating master keyframe")
        made = {
            k["shot_index"]: k
            for k in await service.generate_keyframes(product_id, media_root, 0) or []
        }
        master = made.get(0, {})
        if master.get("status") != "ready":
            raise PipelineStopped(
                f"Master keyframe failed: {master.get('error') or 'no image'}. "
                "Retry it in the Images step"
            )
        if master.get("qa_problem") and until != "images":
            raise PipelineStopped(
                f"Master keyframe needs a look ({master['qa_problem']}). "
                "Review it in the Images step, then run again"
            )
        await service.set_keyframe_status(product_id, 0, "approved")

    report("Generating remaining scene keyframes")
    rest = {
        k["shot_index"]: k for k in await service.generate_keyframes(product_id, media_root) or []
    }
    if until == "images":
        return
    to_review: list[int] = []
    for index in range(1, shot_count):
        keyframe = rest.get(index, {})
        if keyframe.get("status") == "approved":
            continue
        if keyframe.get("status") == "ready" and not keyframe.get("qa_problem"):
            await service.set_keyframe_status(product_id, index, "approved")
        else:
            to_review.append(index + 1)
    if to_review:
        shots = ", ".join(str(number) for number in to_review)
        raise PipelineStopped(
            f"Review the images of shot {shots} (failed or flagged by the image check), "
            "then run again"
        )

    report("Creating video clips (this takes a few minutes)")
    clips = await service.clips(product_id, media_root)
    if sum(clip["status"] in ("ready", "processing") for clip in clips) < shot_count:
        await service.generate_clips(product_id, media_root)
    await _wait_for_clips(
        service, product_id, media_root, shot_count, poll_seconds, report, busy_wait_seconds
    )

    report("Synthesizing voiceover")
    await service.create_voiceover(product_id, media_root, voice)
    report("Stitching final video with transitions and music")
    await service.build_video(product_id, media_root, False)
    report("Writing TikTok caption and hashtags")
    await service.create_post_package(product_id)


async def _wait_for_clips(
    service: ProductCatalogService,
    product_id: str,
    media_root: Path,
    shot_count: int,
    poll_seconds: float,
    report: Callable[[str], None],
    busy_wait_seconds: float,
) -> None:
    waited = 0.0
    busy_retries: dict[int, int] = {}
    while True:
        # each call also collects the video jobs that have finished
        clips = await service.clips(product_id, media_root)
        failed = [clip for clip in clips if clip["status"] == "failed"]
        broken = [clip for clip in failed if not is_busy_error(clip["error"])]
        if broken:
            shots = ", ".join(str(clip["shot_index"] + 1) for clip in broken)
            raise PipelineStopped(
                f"The clip of shot {shots} failed: {broken[0]['error'] or 'video job failed'}. "
                "Retry it in the Clips step"
            )
        busy = [clip["shot_index"] for clip in failed]
        if busy:
            if any(busy_retries.get(index, 0) >= CLIP_BUSY_RETRIES for index in busy):
                raise PipelineStopped(
                    "The video service stayed overloaded and refused the clips "
                    "(no credit was used). Try again later"
                )
            report("Video service is busy, trying again shortly")
            await asyncio.sleep(busy_wait_seconds)
            for index in busy:  # one at a time: a burst is what gets refused
                busy_retries[index] = busy_retries.get(index, 0) + 1
                await service.generate_clips(product_id, media_root, index)
            continue
        if sum(clip["status"] == "ready" for clip in clips) >= shot_count:
            flagged = [clip for clip in clips if clip["qa_problem"]]
            if flagged:
                shots = ", ".join(str(clip["shot_index"] + 1) for clip in flagged)
                raise PipelineStopped(
                    f"The clip of shot {shots} looks wrong ({flagged[0]['qa_problem']}). "
                    "Make it again in the Clips step, or continue from the Voice and video step"
                )
            return
        if waited >= CLIP_WAIT_SECONDS:
            raise PipelineStopped("The clips are still being made; check the Clips step later")
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds
