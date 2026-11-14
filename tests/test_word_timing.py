import shutil
import subprocess

import pytest

from ai_content.domains.marketing.products.captions import spoken_cues
from ai_content.domains.marketing.products.clips import StitchUnavailable
from ai_content.domains.marketing.products.speech import Reading, make_voiceover
from ai_content.domains.marketing.products.word_timing import MISREAD_BELOW, Timing, _matched, align

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _heard(words: str, start: float = 0.5, step: float = 0.4) -> list[tuple[str, float]]:
    return [(w, start + i * step) for i, w in enumerate(words.split())]


def test_matched_words_take_the_time_whisper_heard_them() -> None:
    starts = align(["Áo", "mát", "lắm."], _heard("áo mát lắm"))
    assert starts == pytest.approx([0.5, 0.9, 1.3])


def test_a_word_whisper_heard_differently_is_placed_between_its_neighbours() -> None:
    script = ["Giá", "chỉ", "99.000đ", "thôi", "nha"]
    heard = [("giá", 1.0), ("chỉ", 1.4), ("chín", 1.8), ("mươi", 2.0), ("thôi", 3.0), ("nha", 3.4)]
    starts = align(script, heard)
    assert starts[:2] == [1.0, 1.4]
    assert starts[3:] == [3.0, 3.4]
    assert 1.4 < starts[2] < 3.0


def test_the_ends_are_anchored_and_times_never_go_back() -> None:
    starts = align(["a", "b", "c", "d"], [("x", 0.2), ("c", 1.0), ("y", 0.9)])
    assert starts[0] == 0.2
    assert starts == sorted(starts)


def test_nothing_heard_gives_no_times() -> None:
    assert align(["áo", "mát"], []) == []


def test_a_tone_whisper_hears_differently_still_counts_as_the_word() -> None:
    heard = [("co", 0.5), ("giản", 0.9), ("tốt", 1.2)]
    assert sorted(_matched(["co", "giãn", "Tốt,"], heard)) == [0, 1, 2]


def test_a_reading_that_says_other_words_is_heard_with_a_low_share() -> None:
    script = ["Áo", "này", "mát", "lắm", "giá", "chỉ", "chín", "mươi", "chín", "nghìn"]
    said_right = _heard(" ".join(script))
    said_wrong = _heard("Xin chào các bạn hôm nay mình giới thiệu")
    assert len(_matched(script, said_right)) / len(script) >= MISREAD_BELOW
    assert len(_matched(script, said_wrong)) / len(script) < MISREAD_BELOW


def test_captions_follow_the_measured_starts() -> None:
    cues = spoken_cues("Áo mát lắm", 2.0, [0.4, 0.9, 1.5])
    assert [(c.start, c.end) for c in cues] == [(0.0, 0.9), (0.9, 1.5), (1.5, 2.0)]


def test_a_word_heard_with_the_one_before_still_shows_for_a_moment() -> None:
    cues = spoken_cues("Áo mát lắm", 2.0, [0.4, 1.0, 1.0])
    assert all(c.end > c.start for c in cues)
    assert cues[1].end == pytest.approx(cues[2].start)


def test_captions_estimate_when_the_starts_do_not_fit_the_words() -> None:
    assert spoken_cues("Áo mát lắm", 2.0, [0.4, 0.9]) == spoken_cues("Áo mát lắm", 2.0)


class _Tone:
    async def speak(self, text, voice=None):
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1",
             "-f", "mp3", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip


@needs_ffmpeg
async def test_make_voiceover_notes_when_each_word_starts(tmp_path) -> None:
    async def timer(audio, text):
        return Timing([0.1 * i for i, _ in enumerate(text.split())], 0.8)

    readings = [Reading("áo mát lắm", 4.0)]
    await make_voiceover(_Tone(), readings, tmp_path / "videos" / "voiceover.mp3", timer=timer)  # type: ignore[arg-type]
    assert readings[0].starts == pytest.approx((0.0, 0.1, 0.2))
    assert readings[0].heard == 0.8


@needs_ffmpeg
async def test_a_timer_failure_is_reported_not_hidden(tmp_path) -> None:
    async def timer(audio, text):
        raise OSError("model could not be downloaded")

    with pytest.raises(StitchUnavailable, match="shot 1 could not be timed.*model could not"):
        await make_voiceover(
            _Tone(),  # type: ignore[arg-type]
            [Reading("áo mát", 4.0)],
            tmp_path / "videos" / "voiceover.mp3",
            timer=timer,
        )
