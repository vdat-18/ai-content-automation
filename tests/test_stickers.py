import shutil
import subprocess

import pytest
from PIL import Image

from ai_content.domains.marketing.products.clips import StitchClip, caption_font, stitch
from ai_content.domains.marketing.products.stickers import (
    mention_word,
    quietest_spot,
    render_stickers,
    sticker_lines,
    sticker_start,
    stickers_by_shot,
)

DETAIL = {
    "price": {"sale": "199000", "original": "299000"},
    "sold_count": 3200,
    "rating": 4.6,
}


def test_stickers_only_hold_figures_from_the_product_data() -> None:
    lines = sticker_lines(DETAIL)
    assert lines["price"][0] == ("199.000đ", "Giá gốc 299.000đ")
    assert lines["price"].badge == "-33%"  # worked out from the two prices
    assert lines["sold"][0] == ("Đã bán 3.200",)
    assert lines["rating"][0] == ("4,6 / 5 sao",)
    assert sticker_lines({"price": {"sale": "1"}, "sold_count": 0}) == {}
    assert sticker_lines({"price": {"sale": "99000"}}).keys() == {"price"}


def test_prices_written_with_a_dot_for_thousands_are_read_correctly() -> None:
    lines = sticker_lines(
        {"price": {"sale": "122.147", "original": "211.796"}, "sold_count": "225.222"}
    )
    assert lines["price"][0] == ("122.147đ", "Giá gốc 211.796đ")
    assert lines["price"].badge == "-42%"
    assert lines["sold"][0] == ("Đã bán 225,2k+",)  # never rounded up


def test_each_sticker_goes_to_the_shot_that_mentions_it() -> None:
    texts = ["Áo gì mà mát vậy", "Đã bán hơn 3.200 cái, đánh giá 4,6 sao", "Chỉ 199k, bấm giỏ hàng"]
    assert stickers_by_shot(sticker_lines(DETAIL), texts) == [[], ["sold", "rating"], ["price"]]


def test_a_figure_is_found_at_the_word_where_it_starts_being_said() -> None:
    price = sticker_lines(DETAIL)["price"]
    assert mention_word("Áo mát lắm, chỉ 199k thôi nha", "price", price.figure) == 4
    spelled = "Giá chỉ một trăm chín mươi chín nghìn thôi"
    assert mention_word(spelled, "price", price.figure) == 2  # "một", where the number begins
    assert mention_word("Áo mát lắm", "price", price.figure) is None


def test_the_sticker_lands_as_its_figure_is_said() -> None:
    lines = sticker_lines(DETAIL)
    script = "Áo mát lắm chỉ 199k thôi"
    starts = [0.0, 0.3, 0.6, 1.0, 1.4, 1.9]
    assert sticker_start(["price"], lines, script, starts) == pytest.approx(1.2)  # 1.4 - 0.2
    assert sticker_start(["price"], lines, script, [0.0, 0.1]) is None  # words not timed
    assert sticker_start(["price"], lines, "Áo mát lắm", starts[:3]) is None  # figure not spoken
    assert sticker_start(["price"], lines, "199k ngay", [0.0, 0.5]) == pytest.approx(0.3)


def test_the_price_falls_back_to_the_last_shot_and_others_are_left_out() -> None:
    assert stickers_by_shot(sticker_lines(DETAIL), ["Mát lắm", "Mua đi"]) == [[], ["price"]]
    assert stickers_by_shot({}, ["a", "b"]) == [[], []]


@pytest.mark.skipif(caption_font() is None, reason="no caption font on this machine")
def test_the_stickers_of_a_shot_are_drawn_as_one_transparent_picture(tmp_path) -> None:
    output = tmp_path / "stickers.png"
    lines = sticker_lines(DETAIL)
    render_stickers([(k, lines[k]) for k in ("price", "sold", "rating")], caption_font(), output)  # type: ignore[arg-type]
    image = Image.open(output)
    assert image.mode == "RGBA" and image.width > 200 and image.height > 150
    assert image.getpixel((0, 0))[3] == 0  # the corner is see-through
    assert image.getchannel("A").getextrema()[1] > 200  # the cards themselves are solid


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_stickers_are_laid_over_the_shot_they_belong_to(tmp_path) -> None:
    clip, label, out = tmp_path / "c.mp4", tmp_path / "s.png", tmp_path / "out" / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=720x1280:d=8:r=24",
         str(clip)], check=True,
    )  # fmt: skip
    Image.new("RGBA", (200, 100), (255, 215, 0, 255)).save(label)
    await stitch([StitchClip(clip, 5.0, stickers=(label,))], out)
    frame = tmp_path / "f.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", str(out), "-frames:v", "1", str(frame)],
        check=True,
    )
    picture = Image.open(frame).convert("RGB")
    assert picture.getpixel((100, 180))[0] > 200 and picture.getpixel((900, 1500)) == (0, 0, 0)


def _frame_busy_at(top: int, bottom: int) -> Image.Image:
    """A plain grey picture whose rows between top and bottom are a fine black and white grid."""
    frame = Image.new("RGB", (400, 800), (120, 120, 120))
    for y in range(top, bottom):
        for x in range(0, 400, 2):
            frame.putpixel((x, y), (0, 0, 0) if (x // 2 + y) % 2 else (255, 255, 255))
    return frame


def test_the_sticker_moves_off_a_busy_place_to_a_calmer_one() -> None:
    frame = _frame_busy_at(100, 260)  # a product held up high
    assert quietest_spot([frame], (200, 100), [(40, 130), (40, 400), (40, 600)]) == (40, 400)


def test_the_sticker_stays_high_when_nothing_is_calmer() -> None:
    plain = Image.new("RGB", (400, 800), (120, 120, 120))
    spots = [(40, 130), (40, 400), (40, 600)]
    assert quietest_spot([plain], (200, 100), spots) == (40, 130)
    busy = _frame_busy_at(0, 800)
    assert quietest_spot([busy], (200, 100), spots) == (40, 130)


def test_a_spot_that_is_busy_in_any_frame_is_not_taken() -> None:
    early, late = _frame_busy_at(100, 260), _frame_busy_at(400, 560)
    spots = [(40, 130), (40, 400), (40, 650)]
    assert quietest_spot([early, late], (200, 100), spots) == (40, 650)
