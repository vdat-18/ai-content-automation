"""Structural check of a storyboard, run before any image or clip is paid for.

It catches thin, vague or repeated shots, not whether the video will be good: a clean result
still needs a person to look at it.
"""

from __future__ import annotations

import re
from typing import Any

MIN_BEATS = 3
MIN_WORDS = 15
MAX_WORDS = 45
MAX_SIMILARITY = 0.6

_BEAT = re.compile(r"\d+(?:\.\d+)?\s*(?:to|-|–)\s*\d+(?:\.\d+)?\s*s", re.IGNORECASE)
_GENERIC = (
    "amazing",
    "beautiful",
    "breathtaking",
    "dynamic",
    "elegant",
    "high quality",
    "incredible",
    "modern",
    "perfect",
    "professional",
    "sleek",
    "stunning",
    "stylish",
    "vibrant",
)
_SHOT_SIZES = {
    "close-up": r"close[- ]?up|macro",
    "medium": r"medium|waist|chest",
    "wide": r"wide|full[- ]body|full shot|establishing",
    "over-the-shoulder": r"over[- ]the[- ]shoulder",
    "overhead": r"overhead|top[- ]down|bird'?s[- ]eye",
    "low or high angle": r"low[- ]angle|high[- ]angle",
    "point of view": r"point of view|\bpov\b|first[- ]person",
}
_CAMERA_MOVES = {
    "push-in": r"push[- ]?in|dolly in|move[s]? closer",
    "pull-back": r"pull[- ]?(?:back|out)|dolly out",
    "pan": r"\bpan",
    "tilt": r"\btilt",
    "tracking": r"tracking|follow",
    "orbit": r"orbit|arc around|swing[s]? around",
    "handheld": r"handheld",
    "crane": r"crane|rise[s]? up",
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _variety(texts: list[str], kinds: dict[str, str]) -> int:
    found = {
        kind
        for text in texts
        for kind, pattern in kinds.items()
        if re.search(pattern, text, re.IGNORECASE)
    }
    return len(found)


def brief_quality_problems(brief: dict[str, Any]) -> list[str]:
    """Return what is wrong with the storyboard, as instructions for rewriting it."""
    shots = brief.get("shots") or []
    if not shots:
        return []
    problems: list[str] = []
    texts = [f"{shot.get('keyframe_prompt', '')} {shot.get('motion_prompt', '')}" for shot in shots]
    if len(shots) >= 3:
        wanted = 2 if len(shots) <= 4 else 3
        for label, kinds in (("shot size", _SHOT_SIZES), ("camera move", _CAMERA_MOVES)):
            if _variety(texts, kinds) < wanted:
                problems.append(
                    f"Use at least {wanted} different {label}s across the shots and name them "
                    "in keyframe_prompt or motion_prompt."
                )
    for number, shot in enumerate(shots, start=1):
        motion = str(shot.get("motion_prompt", ""))
        beats = len(_BEAT.findall(motion))
        if beats < MIN_BEATS:
            problems.append(
                f"Shot {number}: motion_prompt has {beats} timed beats; write at least "
                f"{MIN_BEATS} (for example '0 to 3s: ...') each with a new visible action."
            )
        vague = [word for word in _GENERIC if word in texts[number - 1].lower()]
        if len(vague) >= 2:
            problems.append(
                f"Shot {number}: replace the vague words ({', '.join(vague)}) with what is seen."
            )
        spoken = len(str(shot.get("voiceover", "")).split())
        if not MIN_WORDS <= spoken <= MAX_WORDS:
            problems.append(
                f"Shot {number}: voiceover has {spoken} words; {MIN_WORDS} to {MAX_WORDS} "
                "fit a 15 second shot."
            )
    motions = [_words(str(shot.get("motion_prompt", ""))) for shot in shots]
    for first in range(len(shots)):
        for second in range(first + 1, len(shots)):
            union = motions[first] | motions[second]
            if union and len(motions[first] & motions[second]) / len(union) >= MAX_SIMILARITY:
                problems.append(
                    f"Shots {first + 1} and {second + 1} describe almost the same motion; "
                    "give each shot its own action."
                )
    return problems
