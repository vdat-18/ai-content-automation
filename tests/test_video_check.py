import shutil
import subprocess

import pytest

from ai_content.domains.marketing.products.video_check import Measures, judge, measure


def _good(**changes) -> Measures:
    values = {
        "width": 1080, "height": 1920, "seconds": 30.0, "has_audio": True,
        "loudness": -14.2, "true_peak": -1.5, "silences": [], "freezes": [],
    }  # fmt: skip
    return Measures(**{**values, **changes})


def _judge(measures: Measures, **changes) -> dict:
    options = {"expected_seconds": 30.0, "hook_text": "Look at this", "burned_texts": []}
    return judge(measures, **{**options, **changes})


def test_a_clean_video_scores_100() -> None:
    assert _judge(_good()) == {"score": 100, "issues": []}


def test_wrong_size_or_missing_sound_are_major_problems() -> None:
    result = _judge(_good(width=720, height=1280, has_audio=False))
    assert [i["severity"] for i in result["issues"]] == ["major", "major"]
    assert result["score"] == 50
    assert _judge(_good(has_audio=False), wants_audio=False)["score"] == 100


def test_loudness_peak_silence_and_still_picture_are_minor_problems() -> None:
    result = _judge(
        _good(loudness=-20.0, true_peak=-0.2, silences=[1.2, 3.0], freezes=[6.5]),
    )
    assert len(result["issues"]) == 4 and result["score"] == 60
    assert all(issue["severity"] == "minor" for issue in result["issues"])


def test_missing_hook_and_long_on_screen_text_are_reported() -> None:
    result = _judge(_good(), hook_text=" ", burned_texts=["một hai ba bốn năm sáu"])
    messages = [issue["message"] for issue in result["issues"]]
    assert any("no hook" in m for m in messages) and any("too long" in m for m in messages)


def test_a_length_far_from_the_plan_is_reported_but_a_small_drift_is_not() -> None:
    assert _judge(_good(seconds=29.0))["issues"] == []
    assert len(_judge(_good(seconds=24.0))["issues"]) == 1


def test_score_never_goes_below_zero() -> None:
    result = _judge(
        _good(width=1, height=1, has_audio=False, seconds=1),
        hook_text="",
        burned_texts=["a b c d e f"] * 5,
    )
    assert result["score"] == 0


def test_a_shot_whose_picture_changes_away_from_its_voice_over_is_a_major_problem() -> None:
    # the voice-over says shot 2 starts at 5.2 s and shot 3 at 14.3 s
    drifted = _judge(_good(cuts=[5.7, 15.7]), shot_starts=[5.2, 14.3])
    assert [(i["code"], i["severity"]) for i in drifted["issues"]] == [
        ("sync", "major"),
        ("sync", "major"),
    ]
    assert "shot 3 starts at 15.7 s but its voice-over starts at 14.3 s" in (
        drifted["issues"][1]["message"]
    )
    assert _judge(_good(cuts=[5.21, 14.25]), shot_starts=[5.2, 14.3])["issues"] == []
    # no cut found near a start (two similar shots) says nothing either way
    assert _judge(_good(cuts=[]), shot_starts=[5.2, 14.3])["issues"] == []


def test_a_jump_in_the_middle_of_a_shot_is_a_minor_problem() -> None:
    result = _judge(_good(cuts=[5.2, 9.9]), shot_starts=[5.2])
    assert [(i["code"], i["severity"]) for i in result["issues"]] == [("cut", "minor")]
    assert "jumps at 9.9 s" in result["issues"][0]["message"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_the_measure_finds_where_the_picture_cuts(tmp_path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=160x284:d=2:r=24",
         "-f", "lavfi", "-i", "color=blue:s=160x284:d=2:r=24",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(video)],
        check=True,
    )  # fmt: skip
    measures = await measure(video)
    assert len(measures.cuts) == 1 and abs(measures.cuts[0] - 2.0) < 0.1
