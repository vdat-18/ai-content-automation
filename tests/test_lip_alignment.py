import shutil
import subprocess

import numpy as np
import pytest
from tests.test_product_speech import _write_wav

from ai_content.domains.marketing.products.clips import StitchUnavailable
from ai_content.domains.marketing.products.lip_alignment import align_to_guide

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _onsets(path) -> list[float]:
    """Seconds at which sound starts after at least a third of a second of quiet."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    samples = np.frombuffer(raw, dtype=np.float32)
    loud = np.sqrt((samples[: len(samples) // 320 * 320].reshape(-1, 320) ** 2).mean(axis=1)) > 0.01
    found, quiet = [], 99
    for frame, on in enumerate(loud):
        if on and quiet >= 17:
            found.append(frame * 0.02)
        quiet = 0 if on else quiet + 1
    return found


@needs_ffmpeg
async def test_the_reading_is_bent_to_start_each_sound_where_the_guide_does(tmp_path) -> None:
    guide, reading = tmp_path / "guide.wav", tmp_path / "reading.wav"
    # the same three sounds in the same order, but spoken at another pace
    _write_wav(guide, [(0.4, 1.0, 150), (1.6, 2.4, 220), (3.2, 3.8, 300)], 4.5)
    _write_wav(reading, [(0.2, 0.7, 150), (1.1, 1.9, 220), (2.4, 3.0, 300)], 3.4)
    aligned = tmp_path / "aligned.wav"
    await align_to_guide(reading, guide, aligned)
    starts = _onsets(aligned)
    assert len(starts) == 3
    assert all(abs(got - want) < 0.35 for got, want in zip(starts, [0.4, 1.6, 3.2], strict=True))


@needs_ffmpeg
async def test_a_guide_without_speech_is_refused(tmp_path) -> None:
    guide, reading = tmp_path / "guide.wav", tmp_path / "reading.wav"
    _write_wav(guide, [], 3.0)
    _write_wav(reading, [(0.2, 1.0, 150)], 2.0)
    with pytest.raises(StitchUnavailable, match="no speech to follow"):
        await align_to_guide(reading, guide, tmp_path / "aligned.wav")
