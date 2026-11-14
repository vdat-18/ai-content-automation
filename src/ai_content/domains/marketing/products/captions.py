"""Word-by-word captions: short lines that appear as the voice-over says them."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import accumulate

MAX_WORDS = 4
CAPTION_SIZE = 88  # font size in the 1080 x 1920 picture
_SIDE_MARGIN = 70
# TikTok draws its own text and buttons below this line of the 1920 px picture, so the captions
# end above it, 1330 minus room for the outline and the letters' tails
CAPTION_BOTTOM = 1310
_PAUSE_MARKS = ",.;:!?…"
_PAUSE_WEIGHT = 4  # a mark at the end of a word costs about this many letters of speaking time
_MIN_WORD = 0.08  # a word heard at the same moment as the one before still shows this long
_LAST_WORD = 0.25  # seconds the last word stays highlighted when the shot's speech ends sooner
_HIGHLIGHT = r"{\c&H00D7FF&}"  # ASS colours are BGR: this is amber
_PLAIN = r"{\c&HFFFFFF&}"
# The voice-over is written the way it is read aloud; captions show the usual spelling.
_DISPLAY_SPELLING = {
    "phom": "form",
    "cốt-tông": "cotton",
    "mi-li-lít": "ml",
    "xen-ti-mét": "cm",
    "ki-lô-gam": "kg",
}


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def spoken_cues(
    text: str,
    speech_seconds: float,
    starts: Sequence[float] = (),
    measure: Callable[[str], float] | None = None,
) -> list[Cue]:
    """Time the words of one shot over the time its voice-over is actually speaking.

    The voice-over is read per shot and starts with the shot. With `starts`, the time each word
    was heard, a word is shown from its start to the start of the next. Without them (or when
    their count differs from the words), the shot's text is spread from 0 to speech_seconds, each
    word taking time in proportion to its letters (a pause after a comma or full stop counts as a
    few more). A line breaks after MAX_WORDS words or a pause, and with `measure` (the width of a
    text in pixels at CAPTION_SIZE) also where it would not fit between the side margins.
    """
    words = text.split()
    if not words or speech_seconds <= 0:
        return []
    if len(starts) == len(words):
        edges = [0.0, *starts[1:]]
        for i in range(1, len(edges)):
            edges[i] = max(edges[i], edges[i - 1] + _MIN_WORD)
        edges.append(max(speech_seconds, edges[-1] + _LAST_WORD))
    else:
        weights = [len(w) + (_PAUSE_WEIGHT if w[-1] in _PAUSE_MARKS else 0) for w in words]
        unit = speech_seconds / sum(weights)
        edges = [0.0, *accumulate(w * unit for w in weights)]
    cues: list[Cue] = []
    position = 0
    for size in _fit_lines(words, _line_sizes(words), measure):
        line = [_display(w) for w in words[position : position + size]]
        for number in range(size):
            cues.append(
                Cue(edges[position + number], edges[position + number + 1], _styled(line, number))
            )
        position += size
    return cues


def _line_sizes(words: list[str]) -> list[int]:
    """Words per line: a phrase (up to a comma or full stop) is split into even lines."""
    sizes: list[int] = []
    phrase = 0
    for word in words:
        phrase += 1
        if word[-1] in _PAUSE_MARKS:
            sizes += _even(phrase)
            phrase = 0
    return sizes + (_even(phrase) if phrase else [])


def _fit_lines(
    words: list[str], sizes: list[int], measure: Callable[[str], float] | None
) -> list[int]:
    """Words per line, with a line that is too wide for the picture split in halves."""
    if measure is None:
        return sizes
    fitted: list[int] = []
    position = 0
    for size in sizes:
        fitted += _halve([_display(w) for w in words[position : position + size]], measure)
        position += size
    return fitted


def _halve(line: list[str], measure: Callable[[str], float]) -> list[int]:
    room = 1080 - 2 * _SIDE_MARGIN
    if len(line) < 2 or measure(" ".join(line)) <= room:
        return [len(line)]
    half = (len(line) + 1) // 2
    return _halve(line[:half], measure) + _halve(line[half:], measure)


def _even(count: int) -> list[int]:
    lines = -(-count // MAX_WORDS)
    base, extra = divmod(count, lines)
    return [base + (1 if i < extra else 0) for i in range(lines)]


def _display(word: str) -> str:
    """The usual spelling of a word that is written as it is read aloud."""
    core = word.rstrip(_PAUSE_MARKS)
    shown = _DISPLAY_SPELLING.get(core.lower(), core)
    if shown != core and core[:1].isupper():
        shown = shown.capitalize()
    return shown + "".join(c for c in word[len(core) :] if c in "?!…")  # no comma or full stop


def _styled(line: list[str], active: int) -> str:
    """The whole line, the word being said in amber (digit words too); sizes never change."""
    out = []
    for number, word in enumerate(line):
        if number == active or re.search(r"\d", word):
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
    """An ASS subtitle file: big white bold text with a dark outline, ending at CAPTION_BOTTOM."""
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_family},{CAPTION_SIZE},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,"
        f"-1,0,0,0,100,100,1,0,1,9,5,2,{_SIDE_MARGIN},{_SIDE_MARGIN},{height - CAPTION_BOTTOM},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = "".join(
        f"Dialogue: 0,{_stamp(cue.start)},{_stamp(cue.end)},Default,,0,0,0,,{cue.text}\n"
        for cue in cues
    )
    return header + events
