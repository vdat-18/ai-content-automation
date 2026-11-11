import shutil
import subprocess

import pytest
from PIL import Image

from ai_content.domains.marketing.products.clips import StitchClip, caption_font, stitch
from ai_content.domains.marketing.products.stickers import (
    render_stickers,
    sticker_lines,
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
