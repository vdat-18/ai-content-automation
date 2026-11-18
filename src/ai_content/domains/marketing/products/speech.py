"""Read each shot's voice-over with a text-to-speech model and lay the readings on one track."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
from loguru import logger

from .clips import TRIM_SECONDS, StitchUnavailable, _run, clip_speed
from .lip_alignment import GuideMismatch, align_to_guide, speech_end
from .word_timing import Timing

WordTimer = Callable[[Path, str], Awaitable[Timing]]  # audio, text -> when each word starts
_TIMEOUT = 120
MAX_SPEEDUP = 1.5
VOICE_LUFS = -16.0  # every reading is brought to this loudness
MAX_GAIN_DB = 12.0
TAIL_SECONDS = 0.4  # quiet kept after the last word of a shot before the hard cut: a natural beat
MIN_SHOT_SECONDS = 2.5  # the shortest a shot may be cut to, so a very short line is still seen


def tts_speed() -> float:
    """Pace the voice-over is read at (AIC_TTS_SPEED); ad voice-overs are brisk."""
    try:
        return min(max(float(os.environ.get("AIC_TTS_SPEED", "1.1")), 1.0), MAX_SPEEDUP)
    except ValueError:
        return 1.1


_DEFAULT_VOICE = "auto"

# Voices the marketplace's Vietnamese model offers (GET /models, model_options.voice).
VOICES: dict[str, str] = {
    "auto": "Tự chọn",
    "kimoanh.mp3": "Kim Oanh",
    "maichi.mp3": "Mai Chi",
    "hamy.mp3": "Hà My",
    "tiendat.mp3": "Tiến Đạt",
    "huuduc.mp3": "Hữu Đức",
    "giongadam.mp3": "Giọng Adam",
}
DEFAULT_VOICE = "giongadam.mp3"  # every video is read in this voice



class SpeechError(RuntimeError):
    """The text-to-speech service did not return audio."""


class SpeechClient:
    """OpenAI-style /audio/speech: text in, mp3 bytes out."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        voice: str = "",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/audio/speech"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model
        self._voice = voice or _DEFAULT_VOICE
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT)

    async def speak(self, text: str, voice: str | None = None) -> bytes:
        body = {
            "model": self.model,
            "input": text,
            "voice": voice or self._voice,
            "response_format": "mp3",
        }
        try:
            response = await self._http.post(self._url, json=body, headers=self._headers)
        except httpx.HTTPError as error:
            raise SpeechError(f"request failed: {error!r}"[:200]) from error
        if response.status_code != 200 or response.content[:1] == b"{":
            raise SpeechError(f"HTTP {response.status_code}: {response.text[:150]}")
        return response.content


async def _probe_seconds(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError as error:
        raise StitchUnavailable("ffprobe could not read the voice-over audio") from error


async def _read_whole(
    client: SpeechClient,
    text: str,
    voice: str | None,
    target: Path,
    folder: Path,
    index: int,
    scratch: list[Path],
) -> float:
    """Read the text in one request, as a voice reads a whole sentence more naturally."""
    raw = folder / f"voice_raw_{index}.mp3"
    scratch.append(raw)
    raw.write_bytes(await client.speak(text.strip(), voice))
    seconds = await _probe_seconds(raw)
    await _run(
        "ffmpeg", "-v", "error", "-y", "-i", raw.name, "-ar", "24000", "-ac", "1", target.name,
        cwd=folder,
    )  # fmt: skip
    return seconds


async def _trim_silence(part: Path, seconds: float) -> float:
    """Cut the quiet after the last word of a reading; returns how long the shot now lasts."""
    end = await speech_end(part)
    keep = min(seconds, max(end + TAIL_SECONDS, MIN_SHOT_SECONDS))
    if keep >= seconds - 0.2:
        return seconds
    shorter = part.with_name(f"short_{part.name}")
    await _run(
        "ffmpeg", "-v", "error", "-y", "-i", part.name, "-t", f"{keep:.3f}", "-ar", "24000",
        "-ac", "1", shorter.name, cwd=part.parent,
    )  # fmt: skip
    shorter.replace(part)
    return keep


async def _time_words(
    timer: WordTimer | None, part: Path, segments: list[Reading], index: int
) -> None:
    """Listen to one finished reading and note when each of its words is spoken."""
    if timer is None:
        return
    try:
        timing = await timer(part, segments[index].text)
    except Exception as error:  # noqa: BLE001 - the model may be missing or fail to download
        raise StitchUnavailable(
            f"The words of shot {index + 1} could not be timed: {error}"
        ) from error
    segments[index] = replace(segments[index], starts=tuple(timing.starts), heard=timing.heard)


async def _loudness(path: Path) -> float | None:
    """Integrated loudness of a reading in LUFS, or None when there is nothing to measure."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    _, stderr = await process.communicate()
    found = re.findall(r"\bI:\s+(-?[\d.]+) LUFS", stderr.decode(errors="replace"))
    return float(found[-1]) if found and float(found[-1]) > -60 else None


async def _level(part: Path) -> None:
    """Bring one reading to the common voice loudness so no shot is louder than another."""
    measured = await _loudness(part)
    if measured is None:
        return
    gain = min(max(VOICE_LUFS - measured, -MAX_GAIN_DB), MAX_GAIN_DB)
    if abs(gain) < 0.3:
        return
    leveled = part.with_name(f"leveled_{part.name}")
    await _run(
        "ffmpeg", "-v", "error", "-y", "-i", part.name,
        "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89", "-ar", "24000", "-ac", "1", leveled.name,
        cwd=part.parent,
    )  # fmt: skip
    leveled.replace(part)


@dataclass(frozen=True)
class Reading:
    text: str
    seconds: float  # how long the shot plays in the finished video
    guide: Path | None = None  # the clip whose own speech sets the pace of a talking shot
    starts: tuple[float, ...] = ()  # when each word of `text` is spoken in the shot, if measured
    heard: float | None = None  # share of the words of `text` heard as written, if measured


def spoken_seconds(length: float, seconds: float, guided: bool = False) -> float:
    """How long the words of one reading are actually heard inside its shot (before the padding)."""
    if guided:
        return min(length / clip_speed(), seconds)
    speed = min(max(length / seconds, tts_speed()), MAX_SPEEDUP)
    return min(length / speed, seconds)


async def make_voiceover(
    client: SpeechClient,
    segments: list[Reading],
    output: Path,
    voice: str | None = None,
    timer: WordTimer | None = None,
) -> list[float]:
    """Read each text so it starts with its shot, and join the readings into one mp3.

    Each reading is spoken in one request, and each
    shot's voice is brought to the same loudness. Every reading is sped up to the brisk pace of
    AIC_TTS_SPEED, and one longer than its shot
    further, to at most 1.5x, and then cut; a shorter one is
    padded with silence, so every shot's words begin where the shot begins. A talking shot has a
    guide clip: its reading is read at the natural pace and bent to follow the speech in the clip,
    so the mouth in the picture fits the voice. When the clip's speech is too different in length
    to follow, the shot is read like any other and its guide is dropped from `segments`. A shot
    whose words end well before the shot does is cut short after them, and its new length is
    written back to `segments`, so the picture can be cut to match. Returns the natural length of each reading so a
    caller can tell which shots need shorter text. With a `timer`, the finished reading of each
    shot is listened to and the time each word is spoken is written back to `segments`.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    if not segments:
        raise StitchUnavailable("No shot has a voice-over text")
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch: list[Path] = []
    lengths: list[float] = []
    parts: list[Path] = []
    try:
        for index, (text, seconds, guide) in enumerate(
            (r.text, r.seconds, r.guide) for r in segments
        ):
            part = output.parent / f"voice_part_{index}.wav"
            scratch.append(part)
            parts.append(part)
            if not text.strip():
                lengths.append(0.0)
                await _run(
                    "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}", part.name,
                    cwd=output.parent,
                )  # fmt: skip
                continue
            if guide is not None:
                raw = output.parent / f"voice_raw_{index}.mp3"
                scratch.append(raw)
                raw.write_bytes(await client.speak(text.strip(), voice))
                length = await _probe_seconds(raw)
                aligned = output.parent / f"voice_aligned_{index}.wav"
                scratch.append(aligned)
                try:
                    await align_to_guide(raw, guide, aligned)
                except GuideMismatch as error:
                    logger.warning("Shot {} is read at its own pace: {}", index + 1, error)
                    segments[index] = replace(segments[index], guide=None)
                else:
                    lengths.append(length)
                    # the clip is trimmed and sped up in the video, so the voice gets the same
                    await _run(
                        "ffmpeg", "-v", "error", "-y", "-ss", f"{TRIM_SECONDS:g}", "-i",
                        aligned.name, "-af", f"atempo={clip_speed():.4f},apad=whole_dur={seconds:.3f}",
                        "-t", f"{seconds:.3f}", "-ar", "24000", "-ac", "1", part.name,
                        cwd=output.parent,
                    )  # fmt: skip
                    await _level(part)
                    segments[index] = replace(
                        segments[index], seconds=await _trim_silence(part, seconds)
                    )
                    await _time_words(timer, part, segments, index)
                    continue
            phrased = output.parent / f"voice_phrased_{index}.wav"
            scratch.append(phrased)
            length = await _read_whole(client, text, voice, phrased, output.parent, index, scratch)
            lengths.append(length)
            speed = min(max(length / seconds, tts_speed()), MAX_SPEEDUP)
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", phrased.name,
                "-af", f"atempo={speed:.4f},apad=whole_dur={seconds:.3f}",
                "-t", f"{seconds:.3f}", "-ar", "24000", "-ac", "1", part.name,
                cwd=output.parent,
            )  # fmt: skip
            await _level(part)
            segments[index] = replace(segments[index], seconds=await _trim_silence(part, seconds))
            await _time_words(timer, part, segments, index)
        listing = output.parent / "voice_parts.txt"
        scratch.append(listing)
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        await _run(
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing.name,
            "-c:a", "libmp3lame", "-q:a", "3", output.name, cwd=output.parent,
        )  # fmt: skip
    finally:
        for path in scratch:
            path.unlink(missing_ok=True)
    return lengths
