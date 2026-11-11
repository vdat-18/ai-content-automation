from ai_content.domains.marketing.products.video_check import Measures, judge


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
