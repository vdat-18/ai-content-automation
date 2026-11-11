"""Heuristic check of ad text against words TikTok Shop Vietnam is reported to flag.

The list comes from third-party articles about TikTok Shop Vietnam word bans, not
from TikTok's own policy, so a hit is a warning for a human to read, never an automatic block.
"""

from __future__ import annotations

import json
import re
from typing import Any

AI_LABEL_REMINDER = "Video này do AI tạo. Hãy bật nhãn nội dung do AI tạo khi đăng lên TikTok."

_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "absolute claim",
        (
            "tốt nhất",
            "rẻ nhất",
            "số 1",
            "số một",
            "duy nhất",
            "tuyệt đối",
            "hoàn toàn",
            "100%",
            "chắc chắn",
            "cam kết hiệu quả",
        ),
    ),
    ("health claim", ("chữa khỏi", "điều trị", "trị dứt điểm", "hết bệnh", "thần dược")),
    ("other platform", ("shopee", "lazada", "tiki", "facebook", "instagram", "youtube", "zalo")),
    (
        "misleading call to action",
        (
            "ấn vào link để nhận thưởng",
            "nhấn vào đây để nhận quà",
            "đặt mua ngay để nhận giá ưu đãi",
        ),
    ),
)
_PATTERNS = [
    (kind, term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE))
    for kind, terms in _RULES
    for term in terms
]
_BRIEF_TEXT_FIELDS = ("title", "selling_angle")
_SHOT_TEXT_FIELDS = ("on_screen_text", "voiceover")


def find_flagged_terms(text: str) -> list[tuple[str, str]]:
    """Return (kind, term) for every flagged word or phrase found in the text."""
    return [(kind, term) for kind, term, pattern in _PATTERNS if pattern.search(text)]


def _warnings(texts: list[tuple[str, str]]) -> list[str]:
    return [
        f'{where}: "{term}" ({kind})'
        for where, text in texts
        for kind, term in find_flagged_terms(text)
    ]


_NUMBER = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)*)\s*(%|k|nghìn|ngàn|triệu|tr|đ|₫)?(?!\w)", re.I)
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_MULTIPLIER = {"k": 1e3, "nghìn": 1e3, "ngàn": 1e3, "triệu": 1e6, "tr": 1e6}
_FACT_FIELDS = (
    "title",
    "categories",
    "price",
    "sold_count",
    "rating",
    "review_count",
    "description",
    "specifications",
    "variants",
)


def _numbers(text: str) -> list[tuple[str, str, float]]:
    """(as written, unit, value) for each number in the text; 199k and 199.000 are both 199000."""
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


def product_facts(detail: dict[str, Any], user_idea: str = "") -> str:
    """The text a claim in an ad may be checked against: product data and the user's own idea."""
    data = {field: detail.get(field) for field in _FACT_FIELDS}
    return f"{json.dumps(data, ensure_ascii=False, default=str)}\n{user_idea}"


def unsupported_numbers(text: str, facts: str) -> list[str]:
    """Numbers an ad says that appear nowhere in the product data.

    Only figures worth checking count: percentages, amounts of money and plain numbers from 100
    up. A count may be rounded down ("over 3,000" for 3,200); a percentage or price must match.
    """
    known = [value for _, _, value in _numbers(facts)]
    missing = []
    for written, unit, value in _numbers(text):
        if not unit and value < 100:
            continue
        rounded_down = not unit and any(0.8 * known_ <= value <= known_ for known_ in known)
        if not rounded_down and not any(abs(value - k) <= 0.01 * k for k in known):
            missing.append(written)
    return missing


def brief_warnings(brief: dict[str, Any], facts: str = "") -> list[str]:
    texts = [(field, str(brief.get(field) or "")) for field in _BRIEF_TEXT_FIELDS]
    for index, shot in enumerate(brief.get("shots") or [], start=1):
        texts += [
            (f"shot {index} {field}", str(shot.get(field) or "")) for field in _SHOT_TEXT_FIELDS
        ]
    warnings = _warnings(texts)
    if facts.strip():
        warnings += [
            f'{where}: "{number}" is not in the product data (unverified number)'
            for where, text in texts
            for number in unsupported_numbers(text, facts)
        ]
    return warnings


def package_warnings(package: dict[str, Any]) -> list[str]:
    texts = [(f"caption {i}", text) for i, text in enumerate(package.get("captions") or [], 1)]
    texts.append(("hashtags", " ".join(package.get("hashtags") or [])))
    return _warnings(texts)
