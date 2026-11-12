"""Turn approved keyframes into short video clips and stitch the clips into one video."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from loguru import logger

from .captions import Cue, ass_document

CLIP_SECONDS = 15
ASPECT = "9:16"
_TIMEOUT = 120
_OUTPUT_SIZE = "1080:1920"  # TikTok vertical spec
_FPS = "24"
TRIM_SECONDS = 0.125
_CAPTION_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
CHECK_FRAMES = 6  # stills of a clip the quality check looks at
_STICKER_TOP = 130  # small and high, above the face of a person who fills the frame
_STICKER_STEP = 130  # space for one sticker
_PART_ENCODES = 2
_COLOR_GRADE = "eq=contrast=1.03:brightness=0.01:saturation=1.05"



class ClipGenerationError(RuntimeError):
    """The video service rejected a job or could not be reached."""


class StitchUnavailable(RuntimeError):
    """The clips cannot be stitched yet; the message says what to do first."""


_BUSY_MARKERS = ("HTTP 429", "HTTP 503", "lượng lớn")


def is_busy_error(message: str | None) -> bool:
    """True when the video service refused a job only because it is overloaded right now."""
    return bool(message) and any(marker in str(message) for marker in _BUSY_MARKERS)


@dataclass(frozen=True)
class JobState:
    status: str
    error: str | None = None
    video_url: str | None = None


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


async def _run(*args: str, cwd: Path | None = None) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )
    _, stderr = await process.communicate()
    if process.returncode:
        logger.warning("ffmpeg failed: {}", stderr.decode(errors="replace")[-500:])
        raise StitchUnavailable("ffmpeg could not process the clips")


def clip_speed() -> float:
    """How much faster than generated the clips play (AIC_CLIP_SPEED); video models drift slowly."""
    try:
        return min(max(float(os.environ.get("AIC_CLIP_SPEED", "1.1")), 1.0), 2.0)
    except ValueError:
        return 1.1


def _source_seconds(duration: float) -> float:
    return max(0.5, duration - 2 * TRIM_SECONDS)


def shot_seconds(duration: float) -> float:
    """Length a shot has in the stitched video once trimmed and sped up."""
    return _source_seconds(duration) / clip_speed()


def clip_seconds_for(shot_length: float) -> float:
    """The part of a clip to use so that the shot lasts shot_length in the stitched video."""
    return shot_length * clip_speed() + 2 * TRIM_SECONDS


@dataclass(frozen=True)
class StitchClip:
    path: Path
    duration: float
    caption: str = ""
    cues: tuple[Cue, ...] = ()  # spoken words; when present they replace the caption
    stickers: tuple[Path, ...] = ()  # label images laid over the shot, stacked from the top


def caption_font() -> Path | None:
    """First font file that can draw Vietnamese captions (AIC_CAPTION_FONT overrides)."""
    override = os.environ.get("AIC_CAPTION_FONT")
    for candidate in ([Path(override)] if override else []) + [Path(f) for f in _CAPTION_FONTS]:
        if candidate.is_file():
            return candidate
    return None


def find_bgm() -> Path | None:
    """Find the default background music loop if available (AIC_BGM_PATH overrides)."""
    override = os.environ.get("AIC_BGM_PATH")
    candidates = [Path(override)] if override else [
        Path("config/default_bgm.wav"),
        Path("config/default_bgm.mp3"),
        Path("/app/config/default_bgm.wav"),
        Path("/app/config/default_bgm.mp3"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None



def _font_family(font: Path) -> str:
    """The family name subtitles ask for; libass finds the file through its folder."""
    name = font.stem.lower()
    return "DejaVu Sans" if "dejavu" in name else "Arial" if "arial" in name else font.stem


def _spoken_filter(font: Path, subtitle_file: str) -> str:
    folder = font.parent.as_posix().replace(":", r"\:")
    return f"ass={subtitle_file}:fontsdir='{folder}'"


def _caption_filter(font: Path, textfile: str, end: float) -> str:
    font_path = font.as_posix().replace(":", r"\:")
    return (
        f"drawtext=fontfile='{font_path}':textfile='{textfile}':fontcolor=white:fontsize=69"
        f":box=1:boxcolor=black@0.55:boxborderw=24:line_spacing=0:x=(w-text_w)/2:y=h*0.64"
        f":enable='between(t,0.3,{end:.2f})'"
    )


async def cover_frame(video: Path, output: Path) -> None:
    """Save the frame one second into the video as its cover picture."""
    if shutil.which("ffmpeg") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    await _run(
        "ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(video),
        "-frames:v", "1", "-q:v", "2", output.name, cwd=output.parent,
    )  # fmt: skip


async def clip_frames(video: Path, seconds: float) -> list[bytes]:
    """Stills spread evenly over the clip, in time order, for the automatic quality check."""
    if shutil.which("ffmpeg") is None:
        return []
    frames: list[bytes] = []
    last = max(seconds - 1.0, 1.0)
    moments = [1.0 + (last - 1.0) * i / (CHECK_FRAMES - 1) for i in range(CHECK_FRAMES)]
    for number, moment in enumerate(moments):
        still = video.parent / f"{video.stem}_check_{number}.jpg"
        try:
            await _run(
                "ffmpeg", "-v", "error", "-y", "-ss", f"{moment:.2f}", "-i", video.name,
                "-frames:v", "1", "-q:v", "3", still.name, cwd=video.parent,
            )  # fmt: skip
            if still.is_file():
                frames.append(still.read_bytes())
        finally:
            still.unlink(missing_ok=True)
    return frames


async def stitch(
    clips: list[StitchClip],
    output: Path,
    voiceover: Path | None = None,
    bgm: Path | None = None,
) -> None:
    """Join the clips into one seamless mp4, burn in captions, and lay audio on top.

    The clips' own audio is dropped because it changes at every cut. The first and last frames
    of each clip are trimmed to avoid static or frozen frames.
    Clips receive subtle color-grading to ensure consistency across AI-generated scenes,
    and are joined with hard cuts.
    Background music is auto-ducked under voice-over speech when available.
    """
    if shutil.which("ffmpeg") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    if not clips:
        raise StitchUnavailable("No clip is ready to stitch")
    output.parent.mkdir(parents=True, exist_ok=True)
    font = caption_font()
    scratch: list[Path] = []
    bgm_path = bgm or (find_bgm() if voiceover is not None else None)
    try:
        limit = asyncio.Semaphore(_PART_ENCODES)

        async def encode(index: int, clip: StitchClip) -> None:
            part = output.parent / f"part_{index}.mp4"
            scratch.append(part)
            seconds = part_durations[index]
            filters = (
                f"setpts=PTS/{clip_speed():.4f},"
                f"scale={_OUTPUT_SIZE}:force_original_aspect_ratio=increase,"
                f"crop={_OUTPUT_SIZE},setsar=1,fps={_FPS},"
                f"{_COLOR_GRADE}"
            )
            if clip.cues and font is not None:
                subtitles = output.parent / f"caption_{index}.ass"
                subtitles.write_text(
                    ass_document(list(clip.cues), _font_family(font)), encoding="utf-8"
                )
                scratch.append(subtitles)
                filters += "," + _spoken_filter(font, subtitles.name)
            elif clip.caption.strip() and font is not None:
                textfile = output.parent / f"caption_{index}.txt"
                textfile.write_text(textwrap.fill(clip.caption.strip(), 20), encoding="utf-8")
                scratch.append(textfile)
                filters += "," + _caption_filter(font, textfile.name, min(seconds - 0.3, 8))
            picture = ["-vf", filters]
            sticker_inputs: list[str] = []
            if clip.stickers:
                graph, last = f"[0:v]{filters}[base]", "base"
                for number, sticker in enumerate(clip.stickers, start=1):
                    sticker_inputs += ["-loop", "1", "-i", str(sticker)]
                    graph += (
                        f";[{last}][{number}:v]overlay=x=40:y={_STICKER_TOP + (number - 1) * _STICKER_STEP}"
                        f":shortest=1:enable='between(t,0.5,{max(seconds - 0.3, 1):.2f})'[s{number}]"
                    )
                    last = f"s{number}"
                picture = ["-filter_complex", graph, "-map", f"[{last}]"]
            async with limit:
                await _run(
                    "ffmpeg", "-v", "error", "-y", "-ss", f"{TRIM_SECONDS:g}", "-i", str(clip.path),
                    *sticker_inputs, "-t", f"{_source_seconds(clip.duration):.3f}", "-an", *picture,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-maxrate", "12M",
                    "-bufsize", "24M", "-pix_fmt", "yuv420p", part.name,
                    cwd=output.parent,
                )  # fmt: skip

        part_durations = [shot_seconds(clip.duration) for clip in clips]
        parts = [output.parent / f"part_{index}.mp4" for index in range(len(clips))]
        async with asyncio.TaskGroup() as group:
            for index, clip in enumerate(clips):
                group.create_task(encode(index, clip))

        # Hard cuts: a fade would shorten the video and drift the voice-over out of sync
        has_audio = voiceover is not None or bgm_path is not None
        silent = output.parent / "silent.mp4" if has_audio else output
        if has_audio:
            scratch.append(silent)

        listing = output.parent / "parts.txt"
        listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
        scratch.append(listing)
        await _run(
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing.name,
            "-c", "copy", "-movflags", "+faststart", silent.name, cwd=output.parent,
        )  # fmt: skip

        # Audio mix: Voiceover + BGM Auto-Ducking (or voiceover only)
        if voiceover is not None and bgm_path is not None:
            # Sidechain compression: Voice ducking BGM
            audio_filter = (
                "[1:a]loudnorm=I=-14:LRA=11:TP=-1,asplit=2[voice_main][voice_sc];"
                "[2:a]volume=0.25[music_base];"
                "[music_base][voice_sc]sidechaincompress=threshold=0.08:ratio=4:attack=50:release=300[music_ducked];"
                "[voice_main][music_ducked]amix=inputs=2:duration=first:dropout_transition=2,"
                "loudnorm=I=-14:LRA=11:TP=-1[aout]"
            )
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", silent.name, "-i", str(voiceover),
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-filter_complex", audio_filter,
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest",
                "-movflags", "+faststart", output.name, cwd=output.parent,
            )  # fmt: skip
        elif voiceover is not None:
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", silent.name, "-i", str(voiceover),
                "-map", "0:v", "-map", "1:a", "-af", "loudnorm=I=-14:LRA=11:TP=-1",
                "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest",
                "-movflags", "+faststart", output.name, cwd=output.parent,
            )  # fmt: skip
        elif bgm_path is not None:
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", silent.name,
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-map", "0:v", "-map", "1:a", "-af", "volume=0.35",
                "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest",
                "-movflags", "+faststart", output.name, cwd=output.parent,
            )  # fmt: skip
    finally:
        for path in scratch:
            path.unlink(missing_ok=True)

