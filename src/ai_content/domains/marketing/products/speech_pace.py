"""How fast and when a video speaks, measured with faster-whisper.

Only numbers leave this module: when the voice starts and ends, its pace and its longest pause.
What is said is counted, never kept.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .word_timing import whisper_model


async def _has_sound(video: Path) -> bool:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
        "-of", "csv=p=0", str(video),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    return bool(stdout.strip())


def _spoken(video: Path, model_dir: Path) -> list[tuple[float, float]]:
    """(start, end) of every spoken word, in any language."""
    segments, _ = whisper_model(model_dir).transcribe(
        str(video), word_timestamps=True, vad_filter=True
    )
    return [(float(w.start), float(w.end)) for s in segments for w in s.words if w.word.strip()]


def pace(words: list[tuple[float, float]], video_seconds: float) -> dict[str, float | str]:
    """The measures of a voice from the start and end of each word; "none" when nothing is said."""
    if not words:
        return {"voice": "none"}
    first, last = words[0][0], words[-1][1]
    pauses = [later[0] - earlier[1] for earlier, later in zip(words, words[1:], strict=False)]
    return {
        "voice_starts": round(first, 1),
        "voice_ends": round(last, 1),
        "words_per_second": round(len(words) / (last - first), 1) if last > first else 0.0,
        "longest_pause": round(max(pauses, default=0.0), 1),
        "video_seconds": round(video_seconds, 1),
    }


async def measure_pace(
    video: Path, model_dir: Path, video_seconds: float
) -> dict[str, float | str]:
    if not await _has_sound(video):
        return {"voice": "none"}
    return pace(await asyncio.to_thread(_spoken, video, model_dir), video_seconds)
