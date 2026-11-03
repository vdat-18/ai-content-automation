"""Turn approved keyframes into short video clips and stitch the clips into one video."""

from __future__ import annotations

import asyncio
import base64
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from loguru import logger

CLIP_SECONDS = (6, 15)
ASPECT = "9:16"
_TIMEOUT = 120
_OUTPUT_SIZE = "720:1280"
_FPS = "24"


class ClipGenerationError(RuntimeError):
    """The video service rejected a job or could not be reached."""


class StitchUnavailable(RuntimeError):
    """The clips cannot be stitched yet; the message says what to do first."""


@dataclass(frozen=True)
class JobState:
    status: str
    error: str | None = None
    video_url: str | None = None


def clip_seconds(duration: int | float | None) -> int:
    """Pick the shortest supported clip length that covers the shot duration."""
    for seconds in CLIP_SECONDS:
        if (duration or 0) <= seconds:
            return seconds
    return CLIP_SECONDS[-1]


def _media_type(content: bytes) -> str:
    if content[:4] == b"\x89PNG":
        return "image/png"
    return "image/webp" if content[:4] == b"RIFF" else "image/jpeg"


class VideoClient:
    """Image-to-video jobs on an OpenAI-style /videos endpoint (submit, poll, download)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)

    async def submit(self, prompt: str, image: bytes, seconds: int) -> tuple[str, str]:
        """Start a job from a first-frame image; return (job id, model name to poll with)."""
        frame = f"data:{_media_type(image)};base64,{base64.b64encode(image).decode()}"
        body = {
            "model": self._model,
            "prompt": prompt,
            "seconds": seconds,
            "size": ASPECT,
            "image": frame,
            "input_reference": frame,
            "image_url": frame,
        }
        try:
            response = await self._http.post(
                f"{self._base}/videos", json=body, headers=self._headers
            )
        except httpx.HTTPError as error:
            raise ClipGenerationError(f"request failed: {error!r}"[:200]) from error
        if response.status_code != 200:
            raise ClipGenerationError(f"HTTP {response.status_code}: {response.text[:200]}")
        job = response.json()
        if not job.get("id"):
            raise ClipGenerationError(f"no job id in the response: {response.text[:200]}")
        return str(job["id"]), str(job.get("model") or self._model)

    async def status(self, job_id: str, job_model: str) -> JobState:
        url = f"{self._base}/videos/{job_id}?model={quote(job_model, safe='')}"
        try:
            response = await self._http.get(url, headers=self._headers)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ClipGenerationError(f"status check failed: {error!r}"[:200]) from error
        job = response.json()
        error = (job.get("error") or {}).get("message")
        return JobState(str(job.get("status")), error, job.get("video_url"))

    async def download(self, video_url: str) -> bytes:
        try:
            response = await self._http.get(video_url, headers=self._headers)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ClipGenerationError(f"download failed: {error!r}"[:200]) from error
        return response.content


async def _run(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode:
        logger.warning("ffmpeg failed: {}", stderr.decode(errors="replace")[-500:])
        raise StitchUnavailable("ffmpeg could not process the clips")


async def stitch(clips: list[tuple[Path, float]], output: Path) -> None:
    """Trim each clip to its shot duration, normalize them and join them into one mp4."""
    if shutil.which("ffmpeg") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    if not clips:
        raise StitchUnavailable("No clip is ready to stitch")
    output.parent.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for index, (source, duration) in enumerate(clips):
        part = output.parent / f"part_{index}.mp4"
        await _run(
            "ffmpeg", "-v", "error", "-y", "-i", str(source), "-t", f"{duration:g}",
            "-vf", f"scale={_OUTPUT_SIZE}:force_original_aspect_ratio=increase,"
            f"crop={_OUTPUT_SIZE},setsar=1,fps={_FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2",
            str(part),
        )  # fmt: skip
        parts.append(part)
    listing = output.parent / "parts.txt"
    listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
    try:
        await _run(
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(output),
        )  # fmt: skip
    finally:
        for part in [*parts, listing]:
            part.unlink(missing_ok=True)
