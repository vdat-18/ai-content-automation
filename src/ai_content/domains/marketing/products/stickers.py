"""Price, sales and rating stickers drawn from the product's own data.

A sticker only shows a figure the product data holds, so it can never invent a number. It appears
in the shot whose words mention that figure; the price also appears in the last shot when no
shot mentions it, because that is where the call to action is.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .compliance import numbers_in

STICKER_COLOR = (255, 215, 0, 235)  # amber, the same as the highlighted caption words
TEXT_COLOR = (20, 20, 20, 255)
_PADDING = 28
_RADIUS = 26
_BIG, _SMALL = 66, 40


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _vnd(amount: float) -> str:
    return f"{round(amount):,}".replace(",", ".") + "đ"


def sticker_lines(detail: dict[str, Any]) -> dict[str, tuple[tuple[str, ...], float]]:
    """Per sticker kind: the lines to draw and the figure a shot must mention to show it."""
    found: dict[str, tuple[tuple[str, ...], float]] = {}
    price = detail.get("price") or {}
    sale = _number(price.get("sale"))
    if sale and sale >= 1000:
        lines = (_vnd(sale),)
        original = _number(price.get("original"))
        if original and original > sale:
            lines += (f"Giá gốc {_vnd(original)}",)
        found["price"] = (lines, sale)
    sold = _number(detail.get("sold_count"))
    if sold and sold >= 1:
        found["sold"] = ((f"Đã bán {round(sold):,}".replace(",", "."),), sold)
    rating = _number(detail.get("rating"))
    if rating and 0 < rating <= 5:
        found["rating"] = ((f"{rating:.1f}".replace(".", ",") + " / 5 sao",), rating)
    return found


def _mentions(text: str, kind: str, figure: float) -> bool:
    lowered = text.casefold()
    if kind == "sold" and re.search(r"đã bán|lượt bán", lowered):
        return True
    if kind == "rating" and re.search(r"đánh giá|\d[.,]\d\s*sao", lowered):
        return True
    return any(abs(value - figure) <= 0.01 * figure for _, _, value in numbers_in(text))


def stickers_by_shot(
    lines: dict[str, tuple[tuple[str, ...], float]], shot_texts: list[str]
) -> list[list[str]]:
    """For each shot, which sticker kinds to show; every kind appears in one shot at most."""
    chosen: list[list[str]] = [[] for _ in shot_texts]
    for kind, (_, figure) in lines.items():
        for index, text in enumerate(shot_texts):
            if _mentions(text, kind, figure):
                chosen[index].append(kind)
                break
        else:
            if kind == "price" and chosen:
                chosen[-1].append(kind)
    return chosen


def render_sticker(lines: tuple[str, ...], font: Path, output: Path) -> None:
    """Draw a rounded amber label with the first line large and the others small."""
    fonts = [ImageFont.truetype(str(font), _BIG if i == 0 else _SMALL) for i in range(len(lines))]
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    boxes = [measure.textbbox((0, 0), line, font=f) for line, f in zip(lines, fonts, strict=True)]
    width = max(box[2] - box[0] for box in boxes) + 2 * _PADDING
    height = sum(box[3] - box[1] for box in boxes) + _PADDING * (len(lines) + 1)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), _RADIUS, fill=STICKER_COLOR)
    y = _PADDING
    for line, f, box in zip(lines, fonts, boxes, strict=True):
        draw.text((_PADDING - box[0], y - box[1]), line, font=f, fill=TEXT_COLOR)
        y += box[3] - box[1] + _PADDING
    image.save(output)
