"""Turn approved keyframes into short video clips and stitch the clips into one video."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import shutil
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path
from urllib.parse import quote

import httpx
from loguru import logger
from PIL import Image, ImageFilter, ImageFont, ImageStat

from .captions import CAPTION_BOTTOM, CAPTION_SIZE, Cue, ass_document
from .jumpcuts import zoom_filter
from .sounds import effects_track_args, sound_events
from .stickers import quietest_spot

# The video model is billed per request, not per second or pixel (docs/model-limits.md), so every
# clip is asked for at the longest length it accepts and cut afterwards
CLIP_SECONDS = 15
ASPECT = "9:16"
_TIMEOUT = 120
_OUTPUT_SIZE = "1080:1920"  # TikTok vertical spec
_FPS = "24"
# The video service takes the first frame under `image`; AIC_VIDEO_FRAME_FIELDS lists more fields
# (comma separated) for a service that names it differently
FRAME_FIELDS = ("image",)
TRIM_SECONDS = 0.125
_CAPTION_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
CHECK_FRAMES = 6  # stills of a clip the quality check looks at
_STICKER_TOP = 170  # small and high, below the status bar TikTok draws over the top 168 px
_STICKER_STEP = 130  # space for one sticker
# Other tops a sticker may take when the first would cover the product. It stays on the left,
# because the voice-over may say where the price is, and ends above the two lines of captions
_STICKER_LEFT = 40
_STICKER_TOPS = (_STICKER_TOP, 560, 900)
_STICKER_BOTTOM_LIMIT = CAPTION_BOTTOM - 230
_PART_ENCODES = 2
_COVER_MOMENTS = (0.5, 1.0, 1.5, 2.0, 2.5)  # seconds in; the sharpest becomes the cover
_COLOR_GRADE = "eq=contrast=1.03:brightness=0.01:saturation=1.05"
# Light grain, a little extra sharpness and soft dark corners: a phone-camera look instead of
# the smooth, evenly lit picture that gives AI video away
_FILM_LOOK = "unsharp=5:5:0.5,noise=alls=6:allf=t,vignette=PI/6"



class ClipGenerationError(RuntimeError):
    """The video service rejected a job or could not be reached."""


class StitchUnavailable(RuntimeError):
    """The clips cannot be stitched yet; the message says what to do first."""


# A refused job costs nothing. A gateway error (502, 504) may rarely hide a job that did start, a
# risk taken so that a hiccup of the service does not stop a whole run.
_BUSY_MARKERS = ("HTTP 429", "HTTP 502", "HTTP 503", "HTTP 504", "lượng lớn")


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
        frame_fields: tuple[str, ...] = FRAME_FIELDS,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._frame_fields = frame_fields
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)

    async def submit(self, prompt: str, image: bytes, seconds: int) -> tuple[str, str]:
        """Start a job from a first-frame image; return (job id, model name to poll with)."""
        frame = f"data:{_media_type(image)};base64,{base64.b64encode(image).decode()}"
        body = {
            "model": self.model,
            "prompt": prompt,
            "seconds": seconds,
            "size": ASPECT,
            **dict.fromkeys(self._frame_fields, frame),
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
        return str(job["id"]), str(job.get("model") or self.model)

    async def status(self, job_id: str, job_model: str) -> JobState:
        url = f"{self._base}/videos/{job_id}?model={quote(job_model, safe='')}"
        try:
            response = await self._http.get(url, headers=self._headers)
            if response.status_code == 404:  # the service forgot the job, so it will never finish
                return JobState("failed", "The video job was lost; make the scene again")
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


async def still_tail_seconds(video: Path) -> float:
    """How long the end of a clip stays frozen; 0 when it keeps moving or cannot be measured."""
    if shutil.which("ffmpeg") is None:
        return 0.0
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
        "-vf", "freezedetect=n=0.003:d=0.5", "-an", "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    _, stderr = await process.communicate()
    if process.returncode:
        return 0.0
    log = stderr.decode(errors="replace")
    starts = re.findall(r"freeze_start: ([\d.]+)", log)
    ends = re.findall(r"freeze_end: ([\d.]+)", log)
    if len(starts) <= len(ends):  # the last freeze ended, so the clip ends in motion
        return 0.0
    duration = re.findall(r"Duration: (\d+):(\d+):([\d.]+)", log)
    if not duration:
        return 0.0
    hours, minutes, seconds = duration[0]
    return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds) - float(starts[-1]))


async def video_seconds(video: Path) -> float:
    """The real length of a video file in seconds; 0 when it cannot be read."""
    if shutil.which("ffprobe") is None:
        return 0.0
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
        str(video), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0


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
    sticker_at: float = 0.5  # seconds into the shot where the stickers start to slide in
    zoom: tuple[tuple[float, float], ...] = ()  # seconds of the shot shown a little closer


def caption_font() -> Path | None:
    """First font file that can draw Vietnamese captions (AIC_CAPTION_FONT overrides)."""
    override = os.environ.get("AIC_CAPTION_FONT")
    for candidate in ([Path(override)] if override else []) + [Path(f) for f in _CAPTION_FONTS]:
        if candidate.is_file():
            return candidate
    return None


def caption_measure(font: Path | None) -> Callable[[str], float] | None:
    """The pixel width of a caption text drawn in the caption font, or None without a font."""
    if font is None:
        return None
    return ImageFont.truetype(str(font), CAPTION_SIZE).getlength


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



_SPRING_DAMPING = 8.0  # how fast the sticker's bounce dies out (per second)
_SPRING_RATE = 10.7  # how fast it swings; with the damping this overshoots by about a tenth


_STICKER_STAGGER = 0.15  # seconds between one sticker sliding in and the next
_STICKER_EXIT = 0.25  # seconds a sticker takes to slide back out before it goes


def _slide_in(start: float, left: int = 40, leave: float | None = None) -> str:
    """An overlay x expression: the sticker springs in from the left edge, overshoots a little,
    and, when `leave` is given, slides back out to the left edge starting at that time."""
    tau = f"max(0,t-{start:g})"
    swing = (
        f"exp(-{_SPRING_DAMPING:g}*{tau})*(cos({_SPRING_RATE:g}*{tau})"
        f"+{_SPRING_DAMPING / _SPRING_RATE:.3f}*sin({_SPRING_RATE:g}*{tau}))"
    )
    if leave is not None:
        swing += f"+pow(min(1,max(0,t-{leave:g})/{_STICKER_EXIT:g}),2)"
    return f"'{left}-(overlay_w+{left})*({swing})'"


_FLOAT_REACH = 5  # pixels a settled sticker drifts up and down
_FLOAT_RATE = 2.4  # radians per second, about one bob every 2.6 s
_SHAKE_MARGIN = 12  # pixels of picture kept in reserve on each side for the handheld drift


def _float_y(top: int, start: float, phase: float) -> str:
    """An overlay y expression: after the spring settles, the sticker bobs like it is floating."""
    ease = f"min(1,max(0,t-{start:g}-0.5)/0.5)"
    return f"'{top}+{_FLOAT_REACH}*{ease}*sin({_FLOAT_RATE:g}*t+{phase:g})'"


def _handheld() -> str:
    """Crop filter that drifts the picture a few pixels, slowly, like a hand holding the phone."""
    m = _SHAKE_MARGIN
    width, height = (int(side) for side in _OUTPUT_SIZE.split(":"))
    return (
        f"scale={width + 2 * m}:{height + 2 * m},crop={width}:{height}"
        f":x='{m}+{m / 2:g}*sin(2.1*t)+{m / 4:g}*sin(5.3*t)'"
        f":y='{m}+{m / 2:g}*sin(1.7*t+1)+{m / 4:g}*sin(4.1*t+2)'"
    )


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


def sharpness(frame: Path) -> float:
    """How crisp a picture is: the mean strength of its edges, which blur and shut eyes lower."""
    with Image.open(frame) as image:
        edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).mean[0]


async def cover_frame(video: Path, output: Path) -> None:
    """Save the sharpest of a few frames from the first seconds as the video's cover picture."""
    if shutil.which("ffmpeg") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    candidates = [output.parent / f"{output.stem}_try_{n}.jpg" for n in range(len(_COVER_MOMENTS))]
    try:
        for moment, still in zip(_COVER_MOMENTS, candidates, strict=True):
            await _run(
                "ffmpeg", "-v", "error", "-y", "-ss", str(moment), "-i", str(video),
                "-frames:v", "1", "-q:v", "2", still.name, cwd=output.parent,
            )  # fmt: skip
        made = [still for still in candidates if still.is_file()]
        if not made:  # the video is shorter than every moment
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", str(video),
                "-frames:v", "1", "-q:v", "2", output.name, cwd=output.parent,
            )  # fmt: skip
            return
        shutil.copyfile(max(made, key=sharpness), output)
    finally:
        for still in candidates:
            still.unlink(missing_ok=True)


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


_LOUDNORM = "loudnorm=I=-14:LRA=11:TP=-1"
# default_bgm.wav measures -21 LUFS, so 0.25 left it ~19 dB under the voice before ducking and
# nearly inaudible; 0.7 puts it ~10 dB under in pauses and ~16 dB under while the voice speaks
_MUSIC_VOLUME = 0.7
_MUSIC_FADE = 0.8  # the music eases out over the last seconds instead of stopping mid-beat


def _ducked_mix(
    voice: int, music: int, effects: int | None = None, ends_at: float = 0.0
) -> str:
    """The voice-over over music that dips while it speaks, plus the sound effects track when
    there is one; the result is labelled [pre]. The music fades out to end with the voice-over
    at `ends_at` seconds (no fade when that is 0)."""
    fade = f",afade=t=out:st={max(ends_at - _MUSIC_FADE, 0):.3f}:d={_MUSIC_FADE}" if ends_at else ""
    extra = "" if effects is None else f"[{effects}:a]"
    return (
        f"[{voice}:a]{_LOUDNORM},asplit=2[voice_main][voice_sc];"
        f"[{music}:a]volume={_MUSIC_VOLUME}{fade}[music_base];"
        "[music_base][voice_sc]sidechaincompress=threshold=0.08:ratio=4:attack=50:release=300"
        "[music_ducked];"
        f"[voice_main][music_ducked]{extra}"
        f"amix=inputs={2 if effects is None else 3}:duration=first:dropout_transition=2[pre]"
    )


def _voice_mix(voice: int, effects: int | None = None) -> str:
    """The voice-over alone, or with the sound effects track laid under it; labelled [pre]."""
    if effects is None:
        return f"[{voice}:a]anull[pre]"
    return f"[{voice}:a][{effects}:a]amix=inputs=2:normalize=0:duration=first[pre]"


async def _measured_loudnorm(inputs: list[str], graph: str) -> str:
    """The loudness filter filled in with this audio's own measured levels.

    A first run measures the audio (`graph` ends in the label [pre]); the real run then corrects
    it exactly instead of estimating as it goes. Falls back to the plain filter when it cannot
    measure, for example on silence.
    """
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-nostats", *inputs,
        "-filter_complex", f"{graph};[pre]{_LOUDNORM}:print_format=json[m]",
        "-map", "[m]", "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    _, stderr = await process.communicate()
    blocks = re.findall(r"\{[^{}]*\}", stderr.decode(errors="replace"))
    try:
        data = json.loads(blocks[-1])
        measured = {
            key: float(data[key])
            for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        }
    except (IndexError, KeyError, ValueError):
        return _LOUDNORM
    if process.returncode or not all(math.isfinite(value) for value in measured.values()):
        return _LOUDNORM
    return (
        f"{_LOUDNORM}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )


def _sticker_shown_from(clip: StitchClip, seconds: float) -> float:
    """Seconds into the part where its stickers start to slide in."""
    return min(clip.sticker_at, max(seconds - 1.0, 0.5))


async def _sticker_spot(
    clip: StitchClip, shown_from: float, seconds: float, look: Path
) -> tuple[int, int]:
    """Where the stickers rest: the usual high place on the left, or a calmer one when frames of
    the shot, from where the sticker has landed to its end, show that place is busy, say a
    product held up there."""
    first, last = shown_from + 0.6, max(seconds - 0.4, shown_from + 0.6)
    frames: list[Image.Image] = []
    for moment in (first, (first + last) / 2, last):
        await _run(
            "ffmpeg", "-v", "error", "-y", "-ss", f"{TRIM_SECONDS + moment * clip_speed():.3f}",
            "-i", str(clip.path), "-frames:v", "1", "-vf",
            f"scale={_OUTPUT_SIZE}:force_original_aspect_ratio=increase,crop={_OUTPUT_SIZE}",
            look.name, cwd=look.parent,
        )  # fmt: skip
        if look.is_file():
            with Image.open(look) as frame:
                frames.append(frame.copy())
    if not frames:
        return _STICKER_LEFT, _STICKER_TOP
    with Image.open(clip.stickers[0]) as card:
        height = card.height + (len(clip.stickers) - 1) * _STICKER_STEP
        spots = [
            (_STICKER_LEFT, top)
            for top in _STICKER_TOPS
            if top + height <= _STICKER_BOTTOM_LIMIT
        ]
        return quietest_spot(frames, (card.width, height), spots or [(_STICKER_LEFT, _STICKER_TOP)])


async def stitch(
    clips: list[StitchClip],
    output: Path,
    voiceover: Path | None = None,
    bgm: Path | None = None,
    music: bool = True,
) -> None:
    """Join the clips into one seamless mp4, burn in captions, and lay audio on top.

    The clips' own audio is dropped because it changes at every cut. The first and last frames
    of each clip are trimmed to avoid static or frozen frames.
    Clips receive subtle color-grading to ensure consistency across AI-generated scenes,
    and are joined with hard cuts.
    Background music is auto-ducked under voice-over speech when available; `music=False` leaves
    it out, for someone who adds their own sound on the platform. With a voice-over, a whoosh is
    laid on each cut and a pop on each sticker.
    """
    if not clips:
        raise StitchUnavailable("No clip is ready to stitch")
    if shutil.which("ffmpeg") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    output.parent.mkdir(parents=True, exist_ok=True)
    font = caption_font()
    scratch: list[Path] = []
    bgm_path = (bgm or find_bgm()) if music else None
    try:
        limit = asyncio.Semaphore(_PART_ENCODES)

        async def encode(index: int, clip: StitchClip) -> None:
            part = output.parent / f"part_{index}.mp4"
            scratch.append(part)
            seconds = part_durations[index]
            filters = (
                f"setpts=PTS/{clip_speed():.4f},"
                f"scale={_OUTPUT_SIZE}:force_original_aspect_ratio=increase,"
                f"crop={_OUTPUT_SIZE},setsar=1,fps={_FPS},{_handheld()},"
                f"{zoom_filter(clip.zoom) + ',' if clip.zoom else ''}"
                f"{_COLOR_GRADE},{_FILM_LOOK}"
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
                shown_from = _sticker_shown_from(clip, seconds)
                look = output.parent / f"look_{index}.jpg"
                scratch.append(look)
                left, top = await _sticker_spot(clip, shown_from, seconds, look)
                gone = max(seconds - 0.3, 1)
                for number, sticker in enumerate(clip.stickers, start=1):
                    sticker_inputs += ["-loop", "1", "-i", str(sticker)]
                    start = shown_from + (number - 1) * _STICKER_STAGGER
                    leave = max(gone - _STICKER_EXIT, start + 0.6)
                    graph += (
                        f";[{last}][{number}:v]overlay=x={_slide_in(start, left, leave)}"
                        f":y={_float_y(top + (number - 1) * _STICKER_STEP, start, number)}"
                        f":shortest=1:enable='between(t,{start:.2f},{gone:.2f})'[s{number}]"
                    )
                    last = f"s{number}"
                picture = ["-filter_complex", graph, "-map", f"[{last}]"]
            async with limit:
                await _run(
                    "ffmpeg", "-v", "error", "-y", "-ss", f"{TRIM_SECONDS:g}", "-i", str(clip.path),
                    *sticker_inputs, "-t", f"{seconds:.3f}", "-an", *picture,
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

        effects = output.parent / "effects.wav" if voiceover is not None else None
        events = sound_events(
            list(accumulate(part_durations[:-1])),
            [
                start + _sticker_shown_from(clip, seconds)
                for clip, seconds, start in zip(
                    clips, part_durations, accumulate([0.0, *part_durations]), strict=False
                )
                if clip.stickers
            ],
        )
        if effects is not None and events:
            scratch.append(effects)
            await _run("ffmpeg", *effects_track_args(events, effects), cwd=output.parent)
        else:
            effects = None

        listing = output.parent / "parts.txt"
        listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
        scratch.append(listing)
        await _run(
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing.name,
            "-c", "copy", "-movflags", "+faststart", silent.name, cwd=output.parent,
        )  # fmt: skip

        # Audio mix: Voiceover + BGM Auto-Ducking (or voiceover only)
        if voiceover is not None and bgm_path is not None:
            backing = ["-stream_loop", "-1", "-i", str(bgm_path)]
            extra = ["-i", effects.name] if effects is not None else []
            ends_at = await video_seconds(voiceover)
            final = await _measured_loudnorm(
                ["-i", str(voiceover), *backing, *extra],
                _ducked_mix(0, 1, None if effects is None else 2, ends_at),
            )
            mixed = _ducked_mix(1, 2, None if effects is None else 3, ends_at)
            audio_filter = f"{mixed};[pre]{final}[aout]"
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", silent.name, "-i", str(voiceover), *backing,
                *extra, "-filter_complex", audio_filter,
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest",
                "-movflags", "+faststart", output.name, cwd=output.parent,
            )  # fmt: skip
        elif voiceover is not None:
            extra = ["-i", effects.name] if effects is not None else []
            final = await _measured_loudnorm(
                ["-i", str(voiceover), *extra], _voice_mix(0, None if effects is None else 1)
            )
            mixed = _voice_mix(1, None if effects is None else 2)
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", silent.name, "-i", str(voiceover), *extra,
                "-filter_complex", f"{mixed};[pre]{final}[aout]",
                "-map", "0:v", "-map", "[aout]",
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

