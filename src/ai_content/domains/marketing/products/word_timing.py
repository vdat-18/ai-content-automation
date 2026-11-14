"""When each word of a reading is actually spoken, measured with faster-whisper.

Whisper listens to the finished reading of one shot and says when it heard each word. It may
hear other words than the script (numbers, brand names, spelling), so what it heard is matched
to the script's words and a script word it did not match is placed between its matched neighbours.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

# A reading heard with less of the script than this is flagged. A right reading scored 0.57 to
# 0.87 on a real product: Whisper writes spoken numbers as digits and mishears a few words.
MISREAD_BELOW = 0.4
_MODEL = "small"  # CPU, int8: about 1 s per shot reading and about 1.5 GB of memory


@cache
def whisper_model(model_dir: Path):  # noqa: ANN202
    from faster_whisper import WhisperModel  # heavy: loaded on first use only

    return WhisperModel(_MODEL, device="cpu", compute_type="int8", download_root=str(model_dir))


def _heard(audio: Path, model_dir: Path) -> list[tuple[str, float]]:
    segments, _ = whisper_model(model_dir).transcribe(
        str(audio), language="vi", word_timestamps=True, vad_filter=True
    )
    return [(w.word, float(w.start)) for s in segments for w in s.words if w.word.strip()]


@dataclass(frozen=True)
class Timing:
    starts: list[float]  # seconds into the audio where each script word starts
    heard: float  # share of the script words Whisper heard as written, 0 to 1


def _key(word: str) -> str:
    """A word without tone marks, case and punctuation, so a tone Whisper hears differently still
    counts as the same word."""
    plain = unicodedata.normalize("NFD", word.lower().replace("đ", "d"))
    return re.sub(r"[^\w]", "", "".join(c for c in plain if not unicodedata.combining(c)))


def _matched(words: list[str], heard: list[tuple[str, float]]) -> dict[int, float]:
    """For each script word Whisper heard as written, the time it started."""
    matcher = SequenceMatcher(
        None, [_key(w) for w in words], [_key(w) for w, _ in heard], autojunk=False
    )
    return {
        block.a + offset: heard[block.b + offset][1]
        for block in matcher.get_matching_blocks()
        for offset in range(block.size)
    }


def align(words: list[str], heard: list[tuple[str, float]]) -> list[float]:
    """The start of every script word, in seconds: heard where Whisper matched the word, spread by
    letters between the matched neighbours where it did not. Never decreasing."""
    if not words or not heard:
        return []
    known = _matched(words, heard)
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


async def word_starts(audio: Path, text: str, model_dir: Path) -> Timing:
    """When each word of `text` starts in `audio` and how much of it was heard as written."""
    words = text.split()
    heard = await asyncio.to_thread(_heard, audio, model_dir)
    return Timing(align(words, heard), len(_matched(words, heard)) / len(words) if words else 1.0)
