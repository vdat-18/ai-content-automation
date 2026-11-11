import re

from ai_content.domains.marketing.products.captions import ass_document, spoken_cues


def plain(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "", text)


def lines(text: str, seconds: float) -> list[str]:
    """The distinct lines on screen, in order (each word of a line has its own cue)."""
    shown: list[str] = []
    for cue in spoken_cues(text, seconds):
        if not shown or shown[-1] != plain(cue.text):
            shown.append(plain(cue.text))
    return shown


def test_words_are_spread_over_the_speaking_time_at_most_four_to_a_line() -> None:
    cues = spoken_cues("Một hai ba bốn năm sáu bảy", 7.0)
    assert lines("Một hai ba bốn năm sáu bảy", 7.0) == ["Một hai ba bốn", "năm sáu bảy"]
    assert cues[0].start == 0 and abs(cues[-1].end - 7.0) < 1e-6
    assert all(a.end == b.start for a, b in zip(cues, cues[1:], strict=False))


def test_a_pause_mark_ends_the_line_and_takes_extra_time() -> None:
    assert lines("Xin chào, bạn ơi", 4.0) == ["Xin chào", "bạn ơi"]
    cues = spoken_cues("Xin chào, bạn ơi", 4.0)
    assert cues[1].end > 4.0 * len("Xin chào,") / len("Xin chào,bạn ơi")


def test_the_word_being_said_is_marked_and_digit_words_stay_amber() -> None:
    cues = spoken_cues("199k còn 2 cái", 3.0)
    assert r"\fscx115" in cues[1].text and cues[1].text.index("còn") > cues[1].text.index(
        r"\fscx115"
    )
    assert cues[0].text.count(r"{\c&H00D7FF&}") >= 2  # 199k said now, 2 amber too


def test_no_text_or_no_speech_gives_no_caption() -> None:
    assert spoken_cues("", 3.0) == [] and spoken_cues("xin chào", 0) == []


def test_the_subtitle_file_lists_each_line_with_its_times() -> None:
    document = ass_document(spoken_cues("Gấp gọn trong 3 giây", 2.5), "DejaVu Sans")
    assert "Style: Default,DejaVu Sans," in document
    assert "Dialogue: 0,0:00:00.00,0:00:" in document
    assert "PlayResY: 1920" in document


def test_captions_use_the_usual_spelling_not_the_read_aloud_one() -> None:
    joined = " ".join(lines("Áo cốt-tông phom đẹp, Phom vừa vặn", 5.0))
    assert "cotton" in joined and "form" in joined and "Form" in joined
    assert "phom" not in joined.lower() and "cốt-tông" not in joined


def test_a_phrase_is_split_into_even_lines() -> None:
    assert [len(t.split()) for t in lines("một hai ba bốn năm", 5.0)] == [3, 2]
