import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from ai_content.domains.marketing.research_crawler.identity import canonicalize_media_url
from ai_content.domains.marketing.research_crawler.models import (
    MediaFingerprint,
    ResearchMediaAsset,
    ResearchScreening,
    StoredResearchRecord,
)
from ai_content.domains.marketing.research_crawler.perceptual_hash import (
    is_duplicate_hash,
    perceptual_hash,
)
from ai_content.domains.marketing.research_crawler.repositories import (
    SqliteResearchCrawlRepository,
)
from ai_content.domains.marketing.research_crawler.service import _duplicate_of


def _picture(size: int, *, shift: int = 0) -> bytes:
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    scale = size / 100
    draw.rectangle([20 * scale, 30 * scale, 70 * scale, 80 * scale], fill="black")
    draw.ellipse([(55 + shift) * scale, 5 * scale, (90 + shift) * scale, 40 * scale], fill="gray")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_same_picture_at_another_size_is_a_duplicate_but_a_different_one_is_not() -> None:
    small, large = perceptual_hash(_picture(236)), perceptual_hash(_picture(736))
    other = perceptual_hash(_picture(236, shift=-45))
    assert small and large and other
    assert is_duplicate_hash(small, large)
    assert not is_duplicate_hash(small, other)
    assert perceptual_hash(b"not an image") is None


def test_media_urls_ignore_expiring_signatures_and_pinterest_sizes() -> None:
    meta = "https://scontent.xx.fbcdn.net/v/t39/a.jpg"
    assert canonicalize_media_url(f"{meta}?_nc_ohc=abc&oe=1") == meta
    assert canonicalize_media_url(f"{meta}?_nc_ohc=zzz&oe=2") == meta
    small = "https://i.pinimg.com/236x/ab/cd/ef.jpg"
    assert canonicalize_media_url(small) == canonicalize_media_url(
        "https://i.pinimg.com/736x/ab/cd/ef.jpg"
    )
    assert canonicalize_media_url(" https://example.com/a.png?x=1 ") == (
        "https://example.com/a.png?x=1"
    )


def test_duplicate_lookup_matches_file_or_picture_and_skips_itself() -> None:
    known = [
        MediaFingerprint(record_key="a", sha256="s1", perceptual_hash="0" * 16),
        MediaFingerprint(record_key="b", sha256="s2", perceptual_hash="f" * 16),
    ]
    same_file = [MediaFingerprint(record_key="new", sha256="s2", perceptual_hash="1" * 16)]
    near = [MediaFingerprint(record_key="new", sha256="s9", perceptual_hash="0" * 15 + "3")]
    far = [MediaFingerprint(record_key="new", sha256="s9", perceptual_hash="a" * 16)]
    assert _duplicate_of(same_file, known) == "b"
    assert _duplicate_of(near, known) == "a"
    assert _duplicate_of(far, known) is None
    assert _duplicate_of([MediaFingerprint(record_key="a", sha256="s1")], known) is None


def _stored(key: str, phash: str, *, screened: bool, reason: str = "ok") -> StoredResearchRecord:
    return StoredResearchRecord(
        record_key=key,
        workspace_id="w",
        brand_id="AuraSleep",
        platform="meta",
        external_id=key,
        record_type="ad",
        media_assets=[
            ResearchMediaAsset(
                media_id="m",
                media_kind="image",
                source_url_fingerprint="f",
                source_url="https://example.com/a.png",
                status="available",
                artifact_ref="a",
                sha256=f"sha-{key}",
                perceptual_hash=phash,
            )
        ],
        screening=ResearchScreening(
            status="completed",
            prompt_version="v",
            model="m",
            content_hash="h",
            usable=reason == "ok",
            reason_code=reason,
            reason="r",
            confidence=1,
        )
        if screened
        else None,
        first_seen_at="2026-10-01T00:00:00Z",
        last_seen_at="2026-10-01T00:00:00Z",
        latest_run_id="r",
        content_hash=key,
    )


def test_known_fingerprints_only_include_screened_originals(tmp_path: Path) -> None:
    repository = SqliteResearchCrawlRepository(tmp_path / "state.db")
    records = [
        _stored("screened", "1" * 16, screened=True),
        _stored("fresh", "2" * 16, screened=False),
        _stored("copy", "3" * 16, screened=True, reason="duplicate_media"),
    ]

    async def run() -> list[str]:
        with repository._connection:
            for record in records:
                repository._connection.execute(
                    "INSERT INTO research_records (record_key, workspace_id, brand_id, platform, "
                    "external_id, record_type, text, screening_status, review_status, has_images, "
                    "has_videos, content_hash, latest_run_id, version_count, first_seen_at, "
                    "last_seen_at, payload) VALUES (?, 'w', 'AuraSleep', 'meta', ?, 'ad', '', "
                    "'kept', 'pending_review', 1, 0, 'h', 'r', 1, 't', 't', ?)",
                    (record.record_key, record.record_key, record.model_dump_json()),
                )
        found = await repository.known_media_fingerprints("w", "AuraSleep", exclude_record_key="")
        return [item.record_key for item in found]

    assert asyncio.run(run()) == ["screened"]
