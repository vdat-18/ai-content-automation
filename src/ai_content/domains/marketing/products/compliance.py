"""Heuristic check of ad text against words TikTok Shop Vietnam is reported to flag.

The list comes from third-party articles about TikTok Shop Vietnam word bans, not
from TikTok's own policy, so a hit is a warning for a human to read, never an automatic block.
"""

from __future__ import annotations

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


def brief_warnings(brief: dict[str, Any]) -> list[str]:
    texts = [(field, str(brief.get(field) or "")) for field in _BRIEF_TEXT_FIELDS]
    for index, shot in enumerate(brief.get("shots") or [], start=1):
        texts += [
            (f"shot {index} {field}", str(shot.get(field) or "")) for field in _SHOT_TEXT_FIELDS
        ]
    return _warnings(texts)


def package_warnings(package: dict[str, Any]) -> list[str]:
    texts = [(f"caption {i}", text) for i, text in enumerate(package.get("captions") or [], 1)]
    texts.append(("hashtags", " ".join(package.get("hashtags") or [])))
    return _warnings(texts)
