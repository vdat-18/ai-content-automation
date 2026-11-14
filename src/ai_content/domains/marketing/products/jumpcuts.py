"""Jump cuts inside a talking shot: the picture moves closer at every other phrase.

A shot of one person speaking is a single take, so the picture is the same for seconds on end. Showing
it a little closer from one phrase to the next, cut on the word that starts the phrase, gives it the
rhythm of an edited reel at no cost, because the closer picture is only a crop of the same clip.
"""

from __future__ import annotations

from collections.abc import Sequence

ZOOM = 1.15  # how much closer the closer picture is
ANCHOR_Y = 0.3  # the closer picture keeps this height of the frame fixed, so the face stays in it
FIRST_CUT = 0.9  # the first cut is not before this many seconds into the shot
MIN_SEGMENT = 1.3  # no picture, closer or not, lasts less than this long
_PHRASE_ENDS = ",.;:!?…"


def zoom_windows(
    words: Sequence[str], starts: Sequence[float], seconds: float
) -> tuple[tuple[float, float], ...]:
    """(start, end) seconds of the shot shown closer: every second phrase, from its first word.

    `starts` is when each word is spoken. Without them (or when their count differs from the
    words) nothing is cut.
    """
    if len(starts) != len(words):
        return ()
    cuts: list[float] = []
    for word, following in zip(words[:-1], starts[1:], strict=True):
        room = FIRST_CUT <= following <= seconds - MIN_SEGMENT
        if word[-1:] in _PHRASE_ENDS and room and (not cuts or following - cuts[-1] >= MIN_SEGMENT):
            cuts.append(following)
    return tuple(
        (start, cuts[number + 1] if number + 1 < len(cuts) else seconds)
        for number, start in enumerate(cuts)
        if number % 2 == 0
    )


def zoom_filter(windows: Sequence[tuple[float, float]]) -> str:
    """The ffmpeg filter showing the picture closer during the windows; empty without any."""
    if not windows:
        return ""
    inside = "+".join(f"between(it,{start:.3f},{end:.3f})" for start, end in windows)
    return (
        f"zoompan=z='if(gt({inside},0),{ZOOM},1)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*{ANCHOR_Y}'"
        ":d=1:s=1080x1920:fps=24"
    )
