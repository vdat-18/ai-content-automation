"""Bend a reading to the pace of the speech Grok made with a clip, so the mouth fits the voice.

Grok draws the mouth for words it speaks itself, in its own voice and rhythm. That speech is
only a timing guide: the reading of the same words is stretched piece by piece to follow it, and
Grok's sound is dropped.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import numpy as np

from .clips import StitchUnavailable, _run

_RATE = 16_000
_HOP = 160  # 10 ms
_WINDOW = 400
_MELS = 40
_COEFFICIENTS = 20
_KNOT = 25  # frames between two stretch points, 0.25 s (finer granularity for Vietnamese syllables)
_MIN_RATE, _MAX_RATE = 0.65, 1.5  # a piece stretched further sounds unnatural
_QUIET = 0.06  # a frame this much quieter than the loudest one is not speech


async def _decode(path: Path) -> np.ndarray:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(_RATE),
        "-f", "f32le", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    if process.returncode:
        raise StitchUnavailable("ffmpeg could not read the audio")
    return np.frombuffer(stdout, dtype=np.float32)


def _frames(samples: np.ndarray) -> np.ndarray:
    samples = np.pad(samples, (0, max(0, _WINDOW - len(samples))))
    count = 1 + (len(samples) - _WINDOW) // _HOP
    index = np.arange(_WINDOW)[None, :] + _HOP * np.arange(count)[:, None]
    return samples[index] * np.hanning(_WINDOW)


def _speech(frames: np.ndarray) -> tuple[int, int] | None:
    """First and last frame that carry speech, None when the audio is silent."""
    loudness = np.sqrt((frames**2).mean(axis=1))
    if loudness.max() < 1e-4:
        return None
    active = np.flatnonzero(loudness > loudness.max() * _QUIET)
    return int(active[0]), int(active[-1]) + 1


def _mel_filters() -> np.ndarray:
    def to_mel(hertz: float) -> float:
        return 2595 * np.log10(1 + hertz / 700)

    points = 700 * (10 ** (np.linspace(0, to_mel(_RATE / 2), _MELS + 2) / 2595) - 1)
    bins = np.fft.rfftfreq(_WINDOW, 1 / _RATE)
    filters = np.zeros((_MELS, len(bins)))
    for i in range(_MELS):
        low, middle, high = points[i : i + 3]
        filters[i] = np.clip(
            np.minimum((bins - low) / (middle - low), (high - bins) / (high - middle)), 0, None
        )
    return filters


def _features(frames: np.ndarray) -> np.ndarray:
    """Unit length cepstral vectors, normalised per recording so two voices can be compared."""
    mel = np.log((np.abs(np.fft.rfft(frames, axis=1)) ** 2) @ _mel_filters().T + 1e-10)
    basis = np.cos(
        np.pi / _MELS * (np.arange(_MELS)[None, :] + 0.5) * np.arange(1, _COEFFICIENTS + 1)[:, None]
    )
    cepstrum = mel @ basis.T
    cepstrum = (cepstrum - cepstrum.mean(axis=0)) / (cepstrum.std(axis=0) + 1e-6)
    return cepstrum / (np.linalg.norm(cepstrum, axis=1, keepdims=True) + 1e-9)


def _path(reading: np.ndarray, guide: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dynamic time warping: for every frame of the reading, the frame of the guide it matches."""
    cost = 1.0 - reading @ guide.T
    rows, columns = cost.shape
    total = np.full((rows, columns), np.inf)
    step = np.zeros((rows, columns), dtype=np.int8)
    total[0, 0] = cost[0, 0]
    for i in range(1, rows):
        diagonal = np.full(columns, np.inf)
        diagonal[1:] = total[i - 1, :-1]
        wide = np.full(columns, np.inf)
        wide[2:] = total[i - 1, :-2]
        tall = np.full(columns, np.inf)
        if i >= 2:
            tall[1:] = total[i - 2, :-1]
        options = np.stack([diagonal, wide, tall])
        best = options.argmin(axis=0)
        total[i] = cost[i] + options[best, np.arange(columns)]
        step[i] = best
    if not np.isfinite(total[-1, -1]):
        raise StitchUnavailable("The speech in the clip and the reading differ too much in length")
    i, j = rows - 1, columns - 1
    path = [(i, j)]
    while (i, j) != (0, 0):
        move = step[i, j]
        i, j = (i - 1, j - 1) if move == 0 else (i - 1, j - 2) if move == 1 else (i - 2, j - 1)
        path.append((i, j))
    pairs = np.array(path[::-1])
    return pairs[:, 0], pairs[:, 1]


async def align_to_guide(reading: Path, guide: Path, output: Path) -> None:
    """Write the reading to `output` on the guide's timeline: it starts where the guide's speech
    starts and each piece lasts as long as the matching piece of the guide's speech."""
    if shutil.which("ffmpeg") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    voice_frames = _frames(await _decode(reading))
    guide_frames = _frames(await _decode(guide))
    voice_speech, guide_speech = _speech(voice_frames), _speech(guide_frames)
    if guide_speech is None:
        raise StitchUnavailable("The clip has no speech to follow")
    if voice_speech is None:
        raise StitchUnavailable("The reading is silent")
    (v0, v1), (g0, g1) = voice_speech, guide_speech
    voice_at, guide_at = _path(_features(voice_frames[v0:v1]), _features(guide_frames[g0:g1]))
    knots = np.append(np.arange(0, v1 - v0 - 1, _KNOT), v1 - v0 - 1)
    matching = np.interp(knots, voice_at, guide_at)
    lengths = np.clip(np.diff(matching), np.diff(knots) / _MAX_RATE, np.diff(knots) / _MIN_RATE)
    pieces = [
        f"[0:a]atrim=start={(v0 + a) * _HOP / _RATE:.3f}:end={(v0 + b) * _HOP / _RATE:.3f},"
        f"asetpts=PTS-STARTPTS,atempo={(b - a) / length:.4f}[p{n}]"
        for n, (a, b, length) in enumerate(zip(knots[:-1], knots[1:], lengths, strict=True))
    ]
    joined = "".join(f"[p{n}]" for n in range(len(pieces)))
    delay = round(g0 * _HOP / _RATE * 1000)
    graph = ";".join([*pieces, f"{joined}concat=n={len(pieces)}:v=0:a=1,adelay={delay}:all=1[out]"])
    await _run(
        "ffmpeg", "-v", "error", "-y", "-i", str(reading), "-filter_complex", graph,
        "-map", "[out]", "-ar", "24000", "-ac", "1", output.name, cwd=output.parent,
    )  # fmt: skip
