"""When each word of a reading is actually spoken, measured with faster-whisper.

Whisper listens to the finished reading of one shot and says when it heard each word. It may
hear other words than the script (numbers, brand names, spelling), so what it heard is matched
to the script's words and a script word it did not match is placed between its matched neighbours.
"""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

_MODEL = "small"  # CPU, int8: about 1 s per shot reading and about 1.5 GB of memory


@cache
def _model(model_dir: Path):  # noqa: ANN202
    from faster_whisper import WhisperModel  # heavy: loaded on first use only

    return WhisperModel(_MODEL, device="cpu", compute_type="int8", download_root=str(model_dir))


def _heard(audio: Path, model_dir: Path) -> list[tuple[str, float]]:
    segments, _ = _model(model_dir).transcribe(
        str(audio), language="vi", word_timestamps=True, vad_filter=True
    )
    return [(w.word, float(w.start)) for s in segments for w in s.words if w.word.strip()]


def _key(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def align(words: list[str], heard: list[tuple[str, float]]) -> list[float]:
    """The start of every script word, in seconds: heard where Whisper matched the word, spread by
    letters between the matched neighbours where it did not. Never decreasing."""
    if not words or not heard:
        return []
    matcher = SequenceMatcher(
        None, [_key(w) for w in words], [_key(w) for w, _ in heard], autojunk=False
    )
    known: dict[int, float] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            known[block.a + offset] = heard[block.b + offset][1]
    known.setdefault(0, heard[0][1])
    known.setdefault(len(words) - 1, heard[-1][1])
    anchors = sorted(known)
    starts = dict(known)
    for before, after in zip(anchors, anchors[1:], strict=False):
        letters = sum(len(words[i]) for i in range(before, after))
        passed = 0
        for i in range(before + 1, after):
            passed += len(words[i - 1])
            starts[i] = known[before] + (known[after] - known[before]) * passed / letters
    result: list[float] = []
    for i in range(len(words)):
        result.append(max(starts[i], result[-1]) if result else starts[i])
    return result


async def word_starts(audio: Path, text: str, model_dir: Path) -> list[float]:
    """Seconds into `audio` where each word of `text` starts; empty when nothing was heard."""
    heard = await asyncio.to_thread(_heard, audio, model_dir)
    return align(text.split(), heard)
