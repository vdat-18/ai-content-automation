from ai_content.domains.marketing.products.jumpcuts import ZOOM, zoom_filter, zoom_windows


def _words(text: str) -> list[str]:
    return text.split()


def test_every_second_phrase_is_shown_closer_from_its_first_word() -> None:
    words = _words("Một hai, ba bốn, năm sáu, bảy tám.")
    starts = [0.0, 0.4, 1.2, 1.6, 2.6, 3.0, 4.0, 4.4]
    # phrases start at 1.2, 2.6 and 4.0; the second and fourth are the closer ones
    assert zoom_windows(words, starts, 5.5) == ((1.2, 2.6), (4.0, 5.5))


def test_cuts_too_early_or_too_close_to_the_end_or_each_other_are_left_out() -> None:
    words = _words("Một, hai, ba, bốn.")
    # the first phrase would start at 0.4 (before 0.9 s) and the last at 3.5 s (too near the end of 4.0 s)
    assert zoom_windows(words, [0.0, 0.4, 1.0, 3.5], 4.0) == ((1.0, 4.0),)
    # two phrases 0.6 s apart are one: the second cut would make a picture shorter than 1.3 s
    assert zoom_windows(_words("Một, hai, ba. Bốn năm"), [0.0, 1.0, 1.6, 2.0, 3.0], 5.0) == (
        (1.0, 5.0),
    )


def test_without_measured_words_nothing_is_cut() -> None:
    assert zoom_windows(_words("Một, hai, ba."), [], 5.0) == ()
    assert zoom_windows(_words("Một, hai, ba."), [0.0, 1.0], 5.0) == ()  # the counts differ
    assert zoom_windows(_words("Một hai ba"), [0.0, 1.0, 2.0], 5.0) == ()  # no phrase end


def test_the_filter_zooms_only_inside_the_windows() -> None:
    assert zoom_filter(()) == ""
    text = zoom_filter(((1.2, 2.6), (4.0, 5.5)))
    assert text.startswith("zoompan=z='if(gt(between(it,1.200,2.600)+between(it,4.000,5.500),0)")
    assert f",{ZOOM},1)'" in text and text.endswith(":d=1:s=1080x1920:fps=24")
