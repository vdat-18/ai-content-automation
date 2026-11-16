"""Read the figures in a text: 199k and 199.000 are both 199000, spelled-out numbers count too."""

from __future__ import annotations

import re
import unicodedata

_NUMBER = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)*)\s*(%|k|nghìn|ngàn|triệu|tr|đ|₫)?(?!\w)", re.I)
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_MULTIPLIER = {"k": 1e3, "nghìn": 1e3, "ngàn": 1e3, "triệu": 1e6, "tr": 1e6}


_SPOKEN_DIGITS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9,
}  # fmt: skip
_SPOKEN_SCALES = {"nghìn": 1_000, "ngàn": 1_000, "triệu": 1_000_000, "tỷ": 1_000_000_000}
_SPOKEN_WORDS = (*_SPOKEN_DIGITS, "mười", "mươi", "trăm", "linh", "lẻ", *_SPOKEN_SCALES)
_SPOKEN_RUN = re.compile(
    rf"(?<!\w)(?:{'|'.join(_SPOKEN_WORDS)})(?:\s+(?:{'|'.join(_SPOKEN_WORDS)}))*(\s+phần\s+trăm)?(?!\w)",
    re.IGNORECASE,
)
# a plain digit word is too common in speech ("ba mẹ", "năm nay"): only these make a number
_SPOKEN_BIG = {"mười", "mươi", "trăm", *_SPOKEN_SCALES}


def _spoken_value(words: list[str]) -> int:
    total = group = pending = 0
    for word in words:
        if word in _SPOKEN_DIGITS:
            pending = _SPOKEN_DIGITS[word]
        elif word == "mười":
            group += 10
        elif word == "mươi":
            group, pending = group + pending * 10, 0
        elif word == "trăm":
            group, pending = group + pending * 100, 0
        elif word in _SPOKEN_SCALES:
            total, group, pending = total + (group + pending) * _SPOKEN_SCALES[word], 0, 0
    return total + group + pending


def spoken_numbers_as_digits(text: str) -> str:
    """Write the numbers a voice-over spells out as digits: "năm mươi phần trăm" becomes "50%"."""

    def convert(match: re.Match[str]) -> str:
        percent = match.group(1) is not None
        spoken = match.group(0)[: match.start(1) - match.start(0)] if percent else match.group(0)
        words = spoken.casefold().split()
        if not percent and not _SPOKEN_BIG.intersection(words):
            return match.group(0)
        value = _spoken_value(words)
        return (f"{value}%" if percent else str(value)) if value else match.group(0)

    converted = _SPOKEN_RUN.sub(convert, unicodedata.normalize("NFC", text))
    return re.sub(r"(\d)\s*phần\s+trăm", r"\1%", converted)


def numbers_in(text: str) -> list[tuple[str, str, float]]:
    """(as written, unit, value) for each number in the text; 199k and 199.000 are both 199000.

    A number the text spells out in words counts too.
    """
    text = spoken_numbers_as_digits(text)
    found = []
    for match in _NUMBER.finditer(text):
        written, unit = match.group(1), match.group(2).lower() if match.group(2) else ""
        try:
            value = (
                float(re.sub(r"[.,]", "", written))
                if _THOUSANDS.fullmatch(written)
                else float(written.replace(",", "."))
            )
        except ValueError:
            continue
        found.append((match.group().strip(), unit, value * _MULTIPLIER.get(unit, 1)))
    return found

