"""Small sound effects made by ffmpeg itself (no sound files, so no licences to track).

A whoosh sits on each cut between shots and a pop on each sticker that slides in, so the picture's
motion is also heard. They stay far below the voice-over.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

SoundKind = Literal["whoosh", "pop"]

_WHOOSH_LEAD = 0.12  # the swell starts this long before the cut and peaks on it
_SOURCES: dict[SoundKind, tuple[str, float]] = {
    # filtered noise that swells and fades, over 0.4 s
    "whoosh": (
        "anoisesrc=d=0.4:c=pink:a=0.6:r=44100,highpass=f=500,lowpass=f=7000,"
        "afade=t=in:d=0.25,afade=t=out:st=0.25:d=0.15",
        0.35,
    ),
    # a short tone whose pitch drops quickly, over 0.12 s
    "pop": ("aevalsrc='sin(2*PI*(1100-6000*t)*t)*exp(-28*t)':d=0.12:s=44100", 0.4),
}


def sound_events(
    cut_times: list[float], sticker_times: list[float]
) -> list[tuple[SoundKind, float]]:
    """(kind, start second) of every effect: a whoosh into each cut, a pop per sticker."""
    events: list[tuple[SoundKind, float]] = [
        ("whoosh", max(cut - _WHOOSH_LEAD, 0.0)) for cut in cut_times
    ]
    events += [("pop", max(moment, 0.0)) for moment in sticker_times]
    return sorted(events, key=lambda event: event[1])


def effects_graph(events: list[tuple[SoundKind, float]], first_input: int) -> str:
    """The filter graph that places each effect (one lavfi input each, from `first_input`) at its
    time and mixes them into one track labelled [sfx]."""
    pieces = []
    for number, (kind, start) in enumerate(events):
        gain = _SOURCES[kind][1]
        milliseconds = round(start * 1000)
        pieces.append(
            f"[{first_input + number}:a]aformat=channel_layouts=stereo,volume={gain},"
            f"adelay={milliseconds}|{milliseconds}[e{number}]"
        )
    labels = "".join(f"[e{number}]" for number in range(len(events)))
    mix = f"{labels}amix=inputs={len(events)}:normalize=0:duration=longest[sfx]"
    return ";".join([*pieces, mix])


def effect_inputs(events: list[tuple[SoundKind, float]]) -> list[str]:
    """The ffmpeg input arguments that generate each effect."""
    inputs: list[str] = []
    for kind, _ in events:
        inputs += ["-f", "lavfi", "-i", _SOURCES[kind][0]]
    return inputs


def effects_track_args(events: list[tuple[SoundKind, float]], output: Path) -> list[str]:
    """The ffmpeg arguments that write the whole effects track to `output` (a wav file)."""
    return [
        "-v", "error", "-y", *effect_inputs(events),
        "-filter_complex", effects_graph(events, 0), "-map", "[sfx]", str(output),
    ]  # fmt: skip
