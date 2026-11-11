"""Learn how a well-selling ad is built: sampled frames and measured cuts go to the screening model.

Only the structure is kept (hook, pace, text position, ending), as rules for a human to approve.
The video itself is never stored and none of its words or pictures are copied.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

FRAME_COUNT = 40
FRAME_WIDTH = 320
CUT_THRESHOLD = 0.3
MAX_SECONDS = 180
MAX_RULES = 6


class ReferenceAdUnavailable(RuntimeError):
    """The video could not be read, or ffmpeg is missing."""


class _BamlAdClient(Protocol):
    async def AnalyzeAdStructure(
        self, frames: list[BamlImage], frame_times: str, cut_times: str
    ) -> baml_types.AdStructure: ...


async def _ffmpeg(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-nostats", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    _, stderr = await process.communicate()
    if process.returncode:
        logger.warning("ffmpeg failed: {}", stderr.decode(errors="replace")[-300:])
        raise ReferenceAdUnavailable("ffmpeg could not read the video")
    return stderr.decode(errors="replace")


async def _duration(video: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError as error:
        raise ReferenceAdUnavailable("ffprobe could not read the video") from error


async def sample(video: Path, folder: Path) -> tuple[list[bytes], list[float], list[float]]:
    """Return evenly spaced small frames, the time of each, and the measured cut times."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise ReferenceAdUnavailable("ffmpeg is not installed on this machine")
    seconds = await _duration(video)
    if not 1 <= seconds <= MAX_SECONDS:
        raise ReferenceAdUnavailable(f"Use a video between 1 and {MAX_SECONDS} seconds long")
    await _ffmpeg(
        "-y", "-i", str(video), "-vf", f"fps={FRAME_COUNT / seconds:.5f},scale={FRAME_WIDTH}:-2",
        "-frames:v", str(FRAME_COUNT), str(folder / "frame_%03d.jpg"),
    )  # fmt: skip
    frames = [path.read_bytes() for path in sorted(folder.glob("frame_*.jpg"))]
    times = [round(i * seconds / FRAME_COUNT, 1) for i in range(len(frames))]
    log = await _ffmpeg(
        "-i", str(video), "-vf", f"select='gt(scene,{CUT_THRESHOLD})',showinfo", "-f", "null", "-"
    )
    cuts = [round(float(t), 1) for t in re.findall(r"pts_time:([\d.]+)", log)]
    return frames, times, cuts


class AdAnalyzer:
    """Ask the BAML screening model how a sampled ad is built."""

    def __init__(self, client: _BamlAdClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> AdAnalyzer:
        registry = build_client_registry(
            name="ReferenceAd",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
            max_output_tokens=4000,
        )
        return cls(b.with_options(client_registry=registry))

    async def analyze(self, video: Path) -> list[str] | None:
        """Return the structure rules, or None when the model did not answer."""
        with tempfile.TemporaryDirectory() as scratch:
            frames, times, cuts = await sample(video, Path(scratch))
        if not frames:
            raise ReferenceAdUnavailable("No picture could be read from the video")
        try:
            result = await self._client.AnalyzeAdStructure(
                [
                    BamlImage.from_base64("image/jpeg", base64.b64encode(frame).decode("ascii"))
                    for frame in frames
                ],
                json.dumps(times),
                json.dumps(cuts),
            )
        except BamlError as error:
            logger.warning("Reference ad analysis failed: {}", str(error)[:300])
            return None
        return [rule.strip() for rule in result.rules if rule.strip()][:MAX_RULES]
