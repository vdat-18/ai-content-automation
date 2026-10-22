"""Rank and diversify approved research references for one product."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from .models import StoredResearchRecord

_RELEVANCE_WEIGHT = 0.55
_QUALITY_WEIGHT = 0.25
_FRESHNESS_WEIGHT = 0.20
_FRESHNESS_HALF_LIFE_DAYS = 60.0
_DIVERSITY_LAMBDA = 0.7


@dataclass(frozen=True)
class ShortlistedReference:
    reference_id: str
    record_key: str
    media_id: str
    artifact_ref: str
    platform: str
    title: str
    summary: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    reference_id: str
    record: StoredResearchRecord
    media_id: str
    artifact_ref: str
    sha256: str
    relevance_terms: frozenset[str]
    style_terms: frozenset[str]
    quality: float


def _terms(*values: str | tuple[str, ...]) -> frozenset[str]:
    words: set[str] = set()
    for value in values:
        parts = value if isinstance(value, tuple) else (value,)
        for part in parts:
            words.update(word for word in _split(part) if len(word) > 2)
    return frozenset(words)


def _split(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return cleaned.split()


def _candidates(records: list[StoredResearchRecord]) -> list[_Candidate]:
    seen_hashes: set[str] = set()
    result: list[_Candidate] = []
    for record in sorted(records, key=lambda item: item.last_seen_at, reverse=True):
        screening = record.screening
        profile = screening.profile if screening is not None else None
        if record.review_status != "approved" or record.screening_status != "kept":
            continue
        if profile is None or screening is None:
            continue
        for media in record.media_assets:
            if (
                media.media_kind != "image"
                or media.status != "available"
                or media.artifact_ref is None
                or media.sha256 is None
                or media.sha256 in seen_hashes
            ):
                continue
            seen_hashes.add(media.sha256)
            result.append(
                _Candidate(
                    reference_id=f"research:{record.record_key}:{media.media_id}",
                    record=record,
                    media_id=media.media_id,
                    artifact_ref=media.artifact_ref,
                    sha256=media.sha256,
                    relevance_terms=_terms(
                        profile.product_categories,
                        profile.primary_subject,
                        profile.summary,
                        profile.relevance_to_project,
                    ),
                    style_terms=_terms(
                        profile.reference_types,
                        profile.visual_style,
                        profile.composition,
                        profile.setting,
                        profile.hook,
                    ),
                    quality=screening.confidence,
                )
            )
    return result


def _similarity(first: frozenset[str], second: frozenset[str]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def shortlist_references(
    records: list[StoredResearchRecord],
    *,
    product_text: str,
    limit: int = 5,
    now: datetime | None = None,
) -> list[ShortlistedReference]:
    """Pick up to ``limit`` relevant references that differ from each other."""
    moment = now or datetime.now(UTC)
    product_terms = _terms(product_text)
    scored: list[tuple[_Candidate, float, tuple[str, ...]]] = []
    for candidate in _candidates(records):
        matched = sorted(product_terms & candidate.relevance_terms)
        relevance = len(matched) / len(product_terms) if product_terms else 0.0
        age_days = max((moment - candidate.record.last_seen_at).total_seconds() / 86400, 0.0)
        freshness = math.exp(-math.log(2) * age_days / _FRESHNESS_HALF_LIFE_DAYS)
        score = (
            _RELEVANCE_WEIGHT * relevance
            + _QUALITY_WEIGHT * candidate.quality
            + _FRESHNESS_WEIGHT * freshness
        )
        reasons = (
            f"matches product terms: {', '.join(matched)}"
            if matched
            else "no direct product match",
            f"screening confidence {candidate.quality:.2f}",
            f"seen {int(age_days)} days ago",
        )
        scored.append((candidate, score, reasons))

    chosen: list[tuple[_Candidate, float, tuple[str, ...]]] = []
    advertisers: set[str] = set()
    pool = list(scored)
    while pool and len(chosen) < limit:

        def marginal(entry: tuple[_Candidate, float, tuple[str, ...]]) -> float:
            overlap = max(
                (_similarity(entry[0].style_terms, picked[0].style_terms) for picked in chosen),
                default=0.0,
            )
            return _DIVERSITY_LAMBDA * entry[1] - (1 - _DIVERSITY_LAMBDA) * overlap

        best = max(pool, key=marginal)
        pool.remove(best)
        advertiser = best[0].record.advertiser or best[0].record.record_key
        if advertiser in advertisers:
            continue
        advertisers.add(advertiser)
        overlap = max(
            (_similarity(best[0].style_terms, picked[0].style_terms) for picked in chosen),
            default=0.0,
        )
        reasons = (*best[2], f"style overlap with earlier picks {overlap:.2f}")
        chosen.append((best[0], best[1], reasons))

    return [
        ShortlistedReference(
            reference_id=candidate.reference_id,
            record_key=candidate.record.record_key,
            media_id=candidate.media_id,
            artifact_ref=candidate.artifact_ref,
            platform=candidate.record.platform,
            title=candidate.record.title or "",
            summary=(
                candidate.record.screening.profile.summary
                if candidate.record.screening and candidate.record.screening.profile
                else ""
            ),
            score=round(score, 4),
            reasons=reasons,
        )
        for candidate, score, reasons in chosen
    ]
