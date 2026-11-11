from ai_content.domains.marketing.products.captions import ass_document, spoken_cues


def test_words_are_spread_over_the_speaking_time_at_most_four_to_a_line() -> None:
    cues = spoken_cues("Một hai ba bốn năm sáu bảy", 7.0)
    assert [c.text for c in cues] == ["Một hai ba bốn", "năm sáu bảy"]
    assert cues[0].start == 0 and abs(cues[-1].end - 7.0) < 1e-6
    assert cues[0].end == cues[1].start  # a line stays until the next one starts


def test_a_pause_mark_ends_the_line_and_takes_extra_time() -> None:
    cues = spoken_cues("Xin chào, bạn ơi", 4.0)
    assert [c.text for c in cues] == ["Xin chào", "bạn ơi"]
    assert cues[0].end > 4.0 * len("Xin chào,") / len("Xin chào,bạn ơi")


def test_digit_words_are_highlighted_at_most_twice_a_line() -> None:
    [cue] = spoken_cues("199k còn 2 cái", 3.0)[:1]
    assert cue.text.count(r"{\c&H00D7FF&}") == 2


def test_no_text_or_no_speech_gives_no_caption() -> None:
    assert spoken_cues("", 3.0) == [] and spoken_cues("xin chào", 0) == []


def test_the_subtitle_file_lists_each_line_with_its_times() -> None:
    document = ass_document(spoken_cues("Gấp gọn trong 3 giây", 2.5), "DejaVu Sans")
    assert "Style: Default,DejaVu Sans," in document
    assert "Dialogue: 0,0:00:00.00,0:00:" in document
    assert "PlayResY: 1920" in document


def test_captions_use_the_usual_spelling_not_the_read_aloud_one():
    texts = [c.text for c in spoken_cues("Áo cốt-tông phom đẹp, Phom vừa vặn", 5.0)]
    joined = " ".join(texts)
    assert "cotton" in joined and "form" in joined and "Form" in joined
    assert "phom" not in joined.lower() and "cốt-tông" not in joined


def test_a_phrase_is_split_into_even_lines():
    texts = [c.text for c in spoken_cues("một hai ba bốn năm", 5.0)]
    assert [len(t.split()) for t in texts] == [3, 2]
