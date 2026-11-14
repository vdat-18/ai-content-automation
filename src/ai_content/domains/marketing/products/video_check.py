"""Automatic technical check of the finished video: format, sound, gaps and text length.

It measures with ffprobe and ffmpeg only (no AI, no cost) and reports problems with a score.
It does not judge how the video looks, and it only reports; nothing is fixed automatically.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger

TARGET_SIZE = (1080, 1920)
TARGET_LUFS = -14.0
LUFS_TOLERANCE = 3.0
MAX_TRUE_PEAK = -1.0
MAX_SILENCE_SECONDS = 2.5
VOICE_SILENCE_DB = -38
MAX_FROZEN_SECONDS = 6.0
MAX_LENGTH_DRIFT = 2.0
MAX_CAPTION_WORDS = 5
CUT_SCENE_SCORE = 0.25  # how different two frames must be to count as a cut
MAX_CUT_DRIFT = 0.25  # a shot may start this long before or after its voice-over
CUT_WINDOW = 2.0  # a cut this near the start of a shot is that shot's own cut
_PENALTY = {"major": 25, "minor": 10}
# Problems a better script can prevent: what to tell the next script when they keep coming back.
LESSONS = {
    "no_hook": "Start the first scene with spoken words or on-screen text, such as a question or "
    "a number, so the first 2 seconds hook the viewer.",
    "long_text": "Keep on-screen text to 5 words or fewer so it can be read in a glance.",
    "silence": "Give every scene a voice-over line so the video never goes quiet for 2 seconds.",
}


class VideoCheckUnavailable(RuntimeError):
    """The video could not be measured (ffmpeg is missing or could not read it)."""


@dataclass(frozen=True)
class Measures:
    width: int
    height: int
    seconds: float
    has_audio: bool
    loudness: float | None = None  # integrated, LUFS
    true_peak: float | None = None  # dBTP
    silences: list[float] = field(default_factory=list)  # lengths of quiet gaps, seconds
    freezes: list[float] = field(default_factory=list)  # lengths of stretches without motion
    cuts: list[float] = field(default_factory=list)  # seconds where the picture jumps


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # "major" or "minor"
    message: str


def judge(
    measures: Measures,
    *,
    expected_seconds: float,
    hook_text: str,
    burned_texts: list[str],
    wants_audio: bool = True,
    shot_starts: list[float] | None = None,
) -> dict:
    """Turn the measurements into issues and a 0-100 score."""
    issues: list[Issue] = []
    if (measures.width, measures.height) != TARGET_SIZE:
        issues.append(
            Issue(
                "size",
                "major",
                f"Picture is {measures.width}x{measures.height}, not 1080x1920 (9:16)",
            )
        )
    if abs(measures.seconds - expected_seconds) > MAX_LENGTH_DRIFT:
        issues.append(
            Issue(
                "length",
                "minor",
                f"Video is {measures.seconds:.1f} s long, expected about {expected_seconds:.1f} s",
            )
        )
    if not measures.has_audio:
        if wants_audio:
            issues.append(Issue("no_audio", "major", "The video has no sound"))
    else:
        if measures.loudness is not None and abs(measures.loudness - TARGET_LUFS) > LUFS_TOLERANCE:
            issues.append(
                Issue(
                    "loudness",
                    "minor",
                    f"Loudness is {measures.loudness:.1f} LUFS, TikTok expects -14",
                )
            )
        if measures.true_peak is not None and measures.true_peak > MAX_TRUE_PEAK:
            issues.append(
                Issue("peak", "minor", f"Sound peaks at {measures.true_peak:.1f} dB and may clip")
            )
        longest = max(measures.silences, default=0.0)
        if longest >= MAX_SILENCE_SECONDS:
            issues.append(
                Issue("silence", "minor", f"There is {longest:.1f} s of silence in the middle")
            )
    still = max(measures.freezes, default=0.0)
    if still >= MAX_FROZEN_SECONDS:
        issues.append(Issue("frozen", "minor", f"The picture hardly moves for {still:.1f} s"))
    if not hook_text.strip():
        issues.append(
            Issue(
                "no_hook",
                "minor",
                "The first scene has no words, so the first 2 seconds have no hook",
            )
        )
    for text in burned_texts:
        if len(text.split()) > MAX_CAPTION_WORDS:
            issues.append(
                Issue("long_text", "minor", f'On-screen text is too long to read fast: "{text}"')
            )
    issues += _cut_issues(measures.cuts, shot_starts or [])
    score = max(0, 100 - sum(_PENALTY[issue.severity] for issue in issues))
    return {"score": score, "issues": [asdict(issue) for issue in issues]}


def _cut_issues(cuts: list[float], shot_starts: list[float]) -> list[Issue]:
    """A shot whose picture changes away from its voice-over, and a jump inside a shot.

    shot_starts are the seconds at which the second and later shots begin in the voice-over.
    """
    issues: list[Issue] = []
    for number, start in enumerate(shot_starts, start=2):
        near = [cut for cut in cuts if abs(cut - start) <= CUT_WINDOW]
        if near and (cut := min(near, key=lambda c: abs(c - start))) and (
            abs(cut - start) > MAX_CUT_DRIFT
        ):
            issues.append(
                Issue(
                    "sync",
                    "major",
                    f"The picture of shot {number} starts at {cut:.1f} s but its voice-over "
                    f"starts at {start:.1f} s",
                )
            )
    issues += [
        Issue("cut", "minor", f"The picture jumps at {cut:.1f} s in the middle of a shot")
        for cut in cuts
        if all(abs(cut - start) > CUT_WINDOW for start in shot_starts)
    ]
    return issues


async def _output(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        logger.warning("{} failed: {}", args[0], stderr.decode(errors="replace")[-300:])
        raise VideoCheckUnavailable("ffmpeg could not read the video")
    return (stdout + b"\n" + stderr).decode(errors="replace")


def _last_number(pattern: str, text: str) -> float | None:
    found = re.findall(pattern, text)
    return float(found[-1]) if found else None


async def measure(video: Path, voice: Path | None = None) -> Measures:
    """Read the format with ffprobe, then loudness, quiet gaps and still stretches with ffmpeg.

    Quiet gaps are measured on the voice-over alone when it is given, because music under it
    would hide a stretch where nobody speaks.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise VideoCheckUnavailable("ffmpeg is not installed on this machine")
    probe = json.loads(await _probe_json(video))
    streams = probe.get("streams") or []
    picture = next((s for s in streams if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    measures = Measures(
        int(picture.get("width") or 0),
        int(picture.get("height") or 0),
        float((probe.get("format") or {}).get("duration") or 0),
        has_audio,
    )
    sound = ["-af", "ebur128=peak=true,silencedetect=n=-45dB:d=1"] if has_audio else ["-an"]
    log = await _output(
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
        "-vf", f"freezedetect=n=0.003:d=3,select='gt(scene,{CUT_SCENE_SCORE})',showinfo",
        *sound, "-f", "null", "-",
    )  # fmt: skip
    quiet = log
    if voice is not None and has_audio:
        quiet = await _output(
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(voice),
            "-af", f"silencedetect=n={VOICE_SILENCE_DB}dB:d=1", "-f", "null", "-",
        )  # fmt: skip
    return Measures(
        measures.width,
        measures.height,
        measures.seconds,
        has_audio,
        _last_number(r"\bI:\s+(-?[\d.]+) LUFS", log) if has_audio else None,
        _last_number(r"\bPeak:\s+(-?[\d.]+) dBFS", log) if has_audio else None,
        [float(n) for n in re.findall(r"silence_duration: ([\d.]+)", quiet)],
        [float(n) for n in re.findall(r"freeze_duration: ([\d.]+)", log)],
        [float(n) for n in re.findall(r"pts_time:([\d.]+)", log)],
    )


async def _probe_json(video: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
        str(video), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    if process.returncode:
        raise VideoCheckUnavailable("ffprobe could not read the video")
    return stdout.decode()
