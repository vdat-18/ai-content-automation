"""Word-by-word captions: short lines that appear as the voice-over says them."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_WORDS = 4
_PAUSE_MARKS = ",.;:!?…"
_PAUSE_WEIGHT = 4  # a mark at the end of a word costs about this many letters of speaking time
_HIGHLIGHT = r"{\c&H00D7FF&}"  # ASS colours are BGR: this is amber
_PLAIN = r"{\c&HFFFFFF&}"
_MAX_HIGHLIGHTS = 2


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def spoken_cues(text: str, speech_seconds: float) -> list[Cue]:
    """Spread the words of one shot over the time its voice-over is actually speaking.

    The voice-over is read per shot and starts with the shot, so the shot's text is timed from 0
    to speech_seconds, each word taking time in proportion to its letters (a pause after a
    comma or full stop counts as a few more). A line breaks after MAX_WORDS words or a pause.
    """
    words = text.split()
    if not words or speech_seconds <= 0:
        return []
    weights = [len(w) + (_PAUSE_WEIGHT if w[-1] in _PAUSE_MARKS else 0) for w in words]
    unit = speech_seconds / sum(weights)
    lines: list[tuple[list[str], float, float]] = []
    clock = 0.0
    current: list[str] = []
    started = 0.0
    for word, weight in zip(words, weights, strict=True):
        if not current:
            started = clock
        current.append(word)
        clock += weight * unit
        if len(current) == MAX_WORDS or word[-1] in _PAUSE_MARKS:
            lines.append((current, started, clock))
            current = []
    if current:
        lines.append((current, started, clock))
    return [Cue(start, end, _styled(line)) for line, start, end in lines]


def _styled(line: list[str]) -> str:
    """Colour the words with a digit (prices, amounts, sizes), at most two per line."""
    marked = 0
    out = []
    for word in line:
        if marked < _MAX_HIGHLIGHTS and re.search(r"\d", word):
            marked += 1
            out.append(f"{_HIGHLIGHT}{_escape(word)}{_PLAIN}")
        else:
            out.append(_escape(word))
    return " ".join(out)


def _escape(word: str) -> str:
    return word.replace("\\", "").replace("{", "(").replace("}", ")")


def _stamp(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    return f"{hours}:{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}"


def ass_document(cues: list[Cue], font_family: str, width: int = 1080, height: int = 1920) -> str:
    """An ASS subtitle file: big white bold text with a dark outline, in the lower middle."""
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_family},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,6,2,2,60,60,520,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = "".join(
        f"Dialogue: 0,{_stamp(cue.start)},{_stamp(cue.end)},Default,,0,0,0,,{cue.text}\n"
        for cue in cues
    )
    return header + events
