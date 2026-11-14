"""Price, sales and rating stickers drawn from the product's own data.

A sticker only shows a figure the product data holds, so it can never invent a number. It appears
in the shot whose words mention that figure; the price also appears in the last shot when no
shot mentions it, because that is where the call to action is.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .compliance import numbers_in

RED = (254, 44, 85, 255)
AMBER = (255, 214, 10, 255)
WHITE = (255, 255, 255, 255)
SOFT_WHITE = (255, 255, 255, 215)
DARK = (18, 18, 22, 170)
SCALE = 3  # drawn three times larger and scaled down, so the edges are smooth
_PAD, _GAP, _RADIUS = 22, 12, 24
_BIG, _MEDIUM, _SMALL = 50, 34, 28  # nothing under 28 px, the smallest a phone shows readably
_LEAD = 0.2  # a sticker starts sliding in this long before its figure is said
_EARLIEST = 0.3  # and never before the shot has settled
_CLEARLY_CALMER = 0.7  # a lower slot must have under this share of the first slot's edges


class Sticker(NamedTuple):
    lines: tuple[str, ...]
    figure: float  # the number a shot must mention to show this sticker
    badge: str = ""  # a small label beside the first line, such as the percentage off


def _number(value: Any) -> float | None:
    """A figure as the product data writes it: 122.147 is 122147 and 4.7 is 4.7."""
    found = numbers_in(str(value))
    return found[0][2] if found else None


def _vnd(amount: float) -> str:
    return f"{round(amount):,}".replace(",", ".") + "đ"


def _short_count(count: float) -> str:
    """3200 stays 3.200; 225222 becomes 225,2k+ (more than that, never rounded up)."""
    if count < 10_000:
        return f"{round(count):,}".replace(",", ".")
    return f"{int(count // 100) / 10:.1f}".replace(".", ",") + "k+"


def sticker_lines(detail: dict[str, Any]) -> dict[str, Sticker]:
    """Per sticker kind: what to draw, from the product data only."""
    found: dict[str, Sticker] = {}
    price = detail.get("price") or {}
    sale = _number(price.get("sale"))
    if sale and sale >= 1000:
        lines, badge = (_vnd(sale),), ""
        original = _number(price.get("original"))
        if original and original > sale:
            lines += (f"Giá gốc {_vnd(original)}",)
            percent = int((original - sale) / original * 100)
            badge = f"-{percent}%" if percent >= 1 else ""
        found["price"] = Sticker(lines, sale, badge)
    sold = _number(detail.get("sold_count"))
    if sold and sold >= 1:
        found["sold"] = Sticker((f"Đã bán {_short_count(sold)}",), sold)
    rating = _number(detail.get("rating"))
    if rating and 0 < rating <= 5:
        found["rating"] = Sticker((f"{rating:.1f}".replace(".", ",") + " / 5 sao",), rating)
    return found


def _mentions(text: str, kind: str, figure: float) -> bool:
    lowered = text.casefold()
    if kind == "sold" and re.search(r"đã bán|lượt bán", lowered):
        return True
    if kind == "rating" and re.search(r"đánh giá|\d[.,]\d\s*sao", lowered):
        return True
    return any(abs(value - figure) <= 0.01 * figure for _, _, value in numbers_in(text))


def stickers_by_shot(lines: dict[str, Sticker], shot_texts: list[str]) -> list[list[str]]:
    """For each shot, which sticker kinds to show; every kind appears in one shot at most."""
    chosen: list[list[str]] = [[] for _ in shot_texts]
    for kind, sticker in lines.items():
        for index, text in enumerate(shot_texts):
            if _mentions(text, kind, sticker.figure):
                chosen[index].append(kind)
                break
        else:
            if kind == "price" and chosen:
                chosen[-1].append(kind)
    return chosen


def mention_word(text: str, kind: str, figure: float) -> int | None:
    """Index of the first word of `text` that starts the mention of the figure, if it has one."""
    words = text.split()
    for end in range(1, len(words) + 1):
        if _mentions(" ".join(words[:end]), kind, figure):
            for begin in range(end - 1, -1, -1):
                if _mentions(" ".join(words[begin:end]), kind, figure):
                    return begin
    return None


def sticker_start(
    kinds: list[str], lines: dict[str, Sticker], voiceover: str, starts: Sequence[float]
) -> float | None:
    """Seconds into the shot where the voice first says a figure the stickers show, if it is
    spoken and timed; the sticker then lands as the figure is said."""
    if len(starts) != len(voiceover.split()):
        return None
    spoken = [
        starts[index]
        for kind in kinds
        if (index := mention_word(voiceover, kind, lines[kind].figure)) is not None
    ]
    return max(min(spoken) - _LEAD, _EARLIEST) if spoken else None


def quietest_spot(
    frames: Sequence[Image.Image], size: tuple[int, int], spots: Sequence[tuple[int, int]]
) -> tuple[int, int]:
    """The (left, top) among `spots`, the first being preferred, where a sticker of `size` hides
    the least of the pictures (frames spread over the time it is shown). A busy area (a product,
    a face) has many edges and a plain wall or shirt has few, so another spot is only taken when
    it is clearly calmer than the first, in the worst of the frames."""
    edges = [frame.convert("L").filter(ImageFilter.FIND_EDGES) for frame in frames]
    width, height = size

    def busyness(spot: tuple[int, int]) -> float:
        left, top = spot
        box = (left, top, left + width, top + height)
        return max(sum(e.crop(box).tobytes()) / max(width * height, 1) for e in edges)

    best = spots[0]
    best_busyness = busyness(best)
    for spot in spots[1:]:
        value = busyness(spot)
        if value < best_busyness * _CLEARLY_CALMER:
            best, best_busyness = spot, value
    return best


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size * SCALE)


def _width(text: str, font: ImageFont.FreeTypeFont) -> int:
    return round(font.getlength(text))


def _ink(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int, int, int]:
    return font.getbbox(text)


def _price_card(sticker: Sticker, path: Path) -> Image.Image:
    """A red card: the price large, a yellow percentage badge, the old price struck through."""
    pad, gap = _PAD * SCALE, _GAP * SCALE
    big, medium, small = _font(path, _BIG), _font(path, _MEDIUM), _font(path, _SMALL)
    price = sticker.lines[0]
    price_box = _ink(big, price)
    price_h = price_box[3] - price_box[1]
    badge_w = badge_h = 0
    if sticker.badge:
        badge_w = _width(sticker.badge, medium) + 2 * gap
        badge_h = _ink(medium, sticker.badge)[3] - _ink(medium, sticker.badge)[1] + gap
    row_h = max(price_h, badge_h)
    old = sticker.lines[1:]
    old_h = [_ink(small, line)[3] - _ink(small, line)[1] for line in old]
    width = max(
        [_width(price, big) + (gap + badge_w if badge_w else 0), *(_width(x, small) for x in old)]
    )
    height = row_h + sum(h + gap // 2 for h in old_h)
    card = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((0, 0, card.width - 1, card.height - 1), _RADIUS * SCALE, fill=RED)
    draw.text((pad, pad + (row_h - price_h) // 2 - price_box[1]), price, font=big, fill=WHITE)
    if badge_w:
        x0 = pad + _width(price, big) + gap
        y0 = pad + (row_h - badge_h) // 2
        draw.rounded_rectangle((x0, y0, x0 + badge_w, y0 + badge_h), badge_h // 2, fill=AMBER)
        box = _ink(medium, sticker.badge)
        draw.text((x0 + gap, y0 + gap // 2 - box[1]), sticker.badge, font=medium, fill=RED)
    y = pad + row_h + gap // 2
    for line, h in zip(old, old_h, strict=True):
        draw.text((pad, y - _ink(small, line)[1]), line, font=small, fill=SOFT_WHITE)
        number = line.rsplit(" ", 1)[-1]  # only the old price is struck through
        start = pad + _width(line[: len(line) - len(number)], small)
        draw.line((start, y + h // 2, start + _width(number, small), y + h // 2), SOFT_WHITE, 3)
        y += h + gap // 2
    return card


def _pill(sticker: Sticker, kind: str, path: Path) -> Image.Image:
    """A dark rounded pill; the figures in it are amber, a star leads the rating."""
    pad, gap = _PAD * SCALE * 2 // 3, _GAP * SCALE
    font = _font(path, _MEDIUM)
    tokens = sticker.lines[0].split(" ")
    colors = [AMBER if any(c.isdigit() for c in t) else WHITE for t in tokens]
    space = _width("a a", font) - _width("aa", font)
    height = _ink(font, "Âgy")[3] - _ink(font, "Âgy")[1]
    star = height if kind == "rating" else 0
    width = sum(_width(t, font) for t in tokens) + space * (len(tokens) - 1)
    width += star + gap if star else 0
    pill = Image.new("RGBA", (width + 2 * _PAD * SCALE // 1, height + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pill)
    draw.rounded_rectangle((0, 0, pill.width - 1, pill.height - 1), pill.height // 2, fill=DARK)
    x = _PAD * SCALE
    if star:
        _star(draw, x + star // 2, pad + height // 2, star // 2)
        x += star + gap
    for token, color in zip(tokens, colors, strict=True):
        draw.text((x, pad - _ink(font, "Âgy")[1]), token, font=font, fill=color)
        x += _width(token, font) + space
    return pill


def _star(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int) -> None:
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = radius if i % 2 == 0 else radius * 0.45
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=AMBER)


def render_stickers(items: list[tuple[str, Sticker]], font: Path, output: Path) -> None:
    """Draw the stickers of one shot one above the other with a soft shadow, as one picture."""
    cards = [
        _price_card(sticker, font) if kind == "price" else _pill(sticker, kind, font)
        for kind, sticker in items
    ]
    margin, gap = 14 * SCALE, 14 * SCALE
    width = max(card.width for card in cards) + 2 * margin
    height = sum(card.height for card in cards) + gap * (len(cards) - 1) + 2 * margin
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
    y = margin
    for card in cards:
        shadow.paste((0, 0, 0, 110), (margin, y + 5 * SCALE), card.getchannel("A"))
        y += card.height + gap
    sheet.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6 * SCALE)))
    y = margin
    for card in cards:
        sheet.alpha_composite(card, (margin, y))
        y += card.height + gap
    sheet.resize((width // SCALE, height // SCALE), Image.LANCZOS).save(output)
