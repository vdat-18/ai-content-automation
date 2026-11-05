"""Ingest browser captures and export collected products."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from loguru import logger
from openpyxl import Workbook
from openpyxl.styles import Font

from .briefing import (
    MAX_PRODUCT_PHOTOS,
    MAX_REFERENCES,
    BriefGenerationError,
    BriefUnavailable,
    ContentBriefWriter,
)
from .clips import (
    CLIP_SECONDS,
    ClipGenerationError,
    StitchClip,
    StitchUnavailable,
    VideoClient,
    cover_frame,
    shot_seconds,
    stitch,
)
from .compliance import AI_LABEL_REMINDER, brief_warnings, package_warnings
from .embedding import ImageEmbedder, cosine, dhash, download_images, hamming
from .identity import PIN_SIZE_DIR, media_source_fingerprint
from .image_review import ReferenceImageReviewer
from .keyframe_check import KeyframeChecker
from .keyframes import KeyframeGenerationError, KeyframeGenerator, fetch_images
from .media import MediaDownloadReport, download_product_media
from .media_store import MediaStore, RemoteMedia
from .parsing import (
    is_feed_url,
    is_product_url,
    junk_reason,
    parse_feed_payload,
    parse_product_page,
)
from .posting import PostingPackageWriter
from .references import ProfileGenerationError, ReferenceProfile, ReferenceProfileGenerator
from .repositories import ProductRepository
from .speech import (
    MAX_SPEEDUP,
    SAMPLE_TEXT,
    VOICES,
    Reading,
    SpeechClient,
    SpeechError,
    make_voiceover,
)
from .storyboard_review import StoryboardReviewer

_PINTEREST_SEARCH = "https://www.pinterest.com/search/pins/?q="
_SCREEN_BATCH = 200


def _duplicate_similarity() -> float:
    """Embedding similarity from which two images count as the same one (AIC_DUPLICATE_SIMILARITY)."""
    try:
        return min(max(float(os.environ.get("AIC_DUPLICATE_SIMILARITY", "0.80")), 0.5), 0.99)
    except ValueError:
        return 0.80


DUPLICATE_COSINE = _duplicate_similarity()
DUPLICATE_HAMMING = 4
MAX_KEYFRAME_FIXES = 2
# The voice-over is added later, so the picture only has to look right: a talking shot shows
# natural speaking, a narrated shot keeps the mouth closed so no words seem out of sync.
_DELIVERY_RULE = {
    True: "The person speaks naturally to the camera, mouth moving like in conversation.",
    False: "Nobody speaks: lips stay closed or relaxed, no lip movement.",
}
VIDEO_LENGTHS = (15, 30, 45, 60, 75, 90)
BRIEF_ATTEMPTS = 3
PERSONA_STATUSES = frozenset({"ready", "approved", "rejected"})
KEYFRAME_REVIEW_STATUSES = frozenset({"approved", "ready", "rejected"})
BRIEF_FIELDS = (
    "title",
    "format",
    "script",
    "scene",
    "product_placement",
    "product_size",
    "selling_angle",
    "target_audience",
    "style",
    "colors",
    "shots",
)


def _product_photo_urls(brief: dict[str, Any], detail: dict[str, Any]) -> list[str]:
    """The product photos the brief picked; the first photos of the product if it picked none."""
    urls = brief.get("product_photo_urls") or [u for u in detail.get("images") or [] if u]
    return urls[:MAX_PRODUCT_PHOTOS]


def _clean_pins(pins: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep distinct images served from the Pinterest CDN."""
    cleaned: dict[str, dict[str, str]] = {}
    for pin in pins:
        url = str(pin.get("image_url") or "")
        parsed = urlsplit(url)
        title = str(pin.get("title") or "")
        if (parsed.hostname or "").endswith("pinimg.com") is False:
            continue
        image_id = media_source_fingerprint(url)
        cleaned.setdefault(
            image_id,
            {
                "image_id": image_id,
                "image_url": parsed._replace(
                    path=PIN_SIZE_DIR.sub("/736x/", parsed.path, 1)
                ).geturl(),
                "pin_url": str(pin.get("pin_url") or ""),
                "title": title,
            },
        )
    return list(cleaned.values())


def _diverse(images: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Pick images that differ most from each other, newest first, using stored embeddings.

    Images without an embedding are only used to fill the remaining slots.
    """
    embedded = [image for image in images if image.get("embedding")]
    chosen: list[dict[str, Any]] = embedded[:1]
    while len(chosen) < min(count, len(embedded)):
        taken = {image["image_id"] for image in chosen}
        rest = [image for image in embedded if image["image_id"] not in taken]
        chosen.append(
            min(
                rest,
                key=lambda image: max(cosine(image["embedding"], c["embedding"]) for c in chosen),
            )
        )
    taken = {image["image_id"] for image in chosen}
    filler = [image for image in images if image["image_id"] not in taken]
    return (chosen + filler)[:count]


VOICEOVER_TYPES = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
}


def find_voiceover(media_root: Path, product_id: str) -> Path | None:
    """The voice-over file kept beside the stitched video, if there is one."""
    folder = Path(media_root) / "videos" / product_id
    return next(
        (p for ext in VOICEOVER_TYPES.values() if (p := folder / f"voiceover.{ext}").is_file()),
        None,
    )


class KeyframeUnavailable(RuntimeError):
    """Keyframes cannot be made yet; the message says what to do first."""


class ProductCatalogService:
    def __init__(
        self,
        repository: ProductRepository,
        generator: ReferenceProfileGenerator | None = None,
        reviewer: ReferenceImageReviewer | None = None,
        briefer: ContentBriefWriter | None = None,
        embedder: ImageEmbedder | None = None,
        keyframer: KeyframeGenerator | None = None,
        checker: KeyframeChecker | None = None,
        videographer: VideoClient | None = None,
        poster: PostingPackageWriter | None = None,
        speaker: SpeechClient | None = None,
        remote_media: RemoteMedia | None = None,
        storyboard_reviewer: StoryboardReviewer | None = None,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._reviewer = reviewer
        self._briefer = briefer
        self._embedder = embedder
        self._keyframer = keyframer
        self._checker = checker
        self._videographer = videographer
        self._poster = poster
        self._speaker = speaker
        self._remote_media = remote_media
        self._storyboard_reviewer = storyboard_reviewer

    async def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store whatever a captured page or feed response contains."""
        kind = payload.get("kind")
        url = str(payload.get("url") or "")
        if kind == "page" and is_product_url(url):
            detail = parse_product_page(str(payload.get("html") or ""), url)
            if detail is None:
                return {"stored": "ignored", "reason": "no product data in page"}
            await self._repository.upsert_detail(detail)
            return {"stored": "detail", "product_id": detail["product_id"]}
        if kind == "json" and is_feed_url(url):
            items = parse_feed_payload(str(payload.get("body") or ""))
            count = await self._repository.upsert_listing(items) if items else 0
            return {"stored": "listing", "count": count}
        if kind == "pinterest":
            return await self._ingest_pins(payload)
        return {"stored": "ignored", "reason": "unsupported capture"}

    async def _ingest_pins(self, payload: dict[str, Any]) -> dict[str, Any]:
        product_type = str(payload["product_type"])
        pins = _clean_pins(list(payload.get("pins") or []))
        pins, duplicates, check_failed = await self._drop_duplicates(product_type, pins)
        added = await self._repository.add_reference_images(
            product_type, str(payload["query"]), pins
        )
        screened = await self.screen_images(_SCREEN_BATCH) if self._reviewer else None
        return {
            "stored": "reference_images",
            "received": len(payload.get("pins") or []),
            "added": added - duplicates,
            "duplicates": duplicates,
            "check_failed": check_failed,
            "screened": screened,
        }

    async def _drop_duplicates(
        self, product_type: str, pins: list[dict[str, str]]
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Fingerprint new images and mark those that repeat a known image as duplicates.

        Duplicates are still stored (status "duplicate") so a later crawl skips them by id,
        but they never reach the vision model. An image that cannot be checked is stored as
        "check_failed" and never passes as new; when the check cannot run at all it raises.
        Returns the pins to store, the number of duplicates and the number that failed the check.
        """
        if not pins:
            return [], 0, 0
        if self._embedder is None:
            raise ProfileGenerationError(
                "The duplicate check is off, so no image was stored: set AIC_EMBEDDING_MODEL"
            )
        known_ids = await self._repository.existing_image_ids([pin["image_id"] for pin in pins])
        fresh = [pin for pin in pins if pin["image_id"] not in known_ids]
        downloaded = await download_images([pin["image_url"] for pin in fresh])
        known = await self._repository.fingerprints(product_type)
        for item in known:
            item["phash_int"] = int(item["phash"], 16)
        result: list[dict[str, Any]] = [pin for pin in pins if pin["image_id"] in known_ids]
        failed = 0
        checkable: list[tuple[dict[str, str], int, bytes]] = []
        for pin in fresh:
            content = downloaded.get(pin["image_url"])
            try:
                if content is None:
                    raise ValueError("the image could not be downloaded")
                checkable.append((pin, dhash(content), content))
            except Exception as error:  # noqa: BLE001
                logger.warning("Duplicate check failed for {}: {}", pin["image_url"], error)
                failed += 1
                result.append({**pin, "status": "check_failed"})
        try:
            vectors = await self._embedder.embed_many([content for _, _, content in checkable])
        except Exception as error:
            raise ProfileGenerationError(
                f"The duplicate check failed, so no image was stored: {str(error)[:200]}"
            ) from error
        duplicates = 0
        for (pin, phash, _), vector in zip(checkable, vectors, strict=True):
            twin = next(
                (
                    item
                    for item in known
                    if hamming(phash, item["phash_int"]) <= DUPLICATE_HAMMING
                    or (item["embedding"] and cosine(vector, item["embedding"]) >= DUPLICATE_COSINE)
                ),
                None,
            )
            if twin is not None:
                duplicates += 1
                result.append({**pin, "status": "duplicate", "duplicate_of": twin["image_id"]})
                continue
            known.append({"image_id": pin["image_id"], "phash_int": phash, "embedding": vector})
            result.append({**pin, "phash": f"{phash:016x}", "embedding": vector})
        return result, duplicates, failed

    async def recheck_duplicates(self) -> dict[str, int]:
        """Apply the current similarity threshold to images that are already stored.

        Oldest first, an image that looks like an earlier one becomes a duplicate. Removed and
        rejected images still count as the earlier one, so their copies do not come back.
        """
        images = await self._repository.list_reference_images(None, None)  # oldest first
        by_type: dict[str, list[dict[str, Any]]] = {}
        for image in images:
            by_type.setdefault(image["product_type"], []).append(image)
        checked = marked = 0
        for product_type, group in by_type.items():
            prints = {
                fp["image_id"]: fp for fp in await self._repository.fingerprints(product_type)
            }
            kept: list[dict[str, Any]] = []
            for image in group:
                fingerprint = prints.get(image["image_id"])
                if fingerprint is None or image["status"] in ("duplicate", "check_failed"):
                    continue
                checked += 1
                phash = int(fingerprint["phash"], 16)
                twin = any(
                    hamming(phash, int(other["phash"], 16)) <= DUPLICATE_HAMMING
                    or (
                        other["embedding"]
                        and fingerprint["embedding"]
                        and cosine(fingerprint["embedding"], other["embedding"]) >= DUPLICATE_COSINE
                    )
                    for other in kept
                )
                if twin and image["status"] in ("pending", "live"):
                    await self._repository.set_image_status(image["image_id"], "duplicate")
                    marked += 1
                else:
                    kept.append(fingerprint)
        return {"checked": checked, "marked_duplicate": marked}

    async def backfill_fingerprints(self, limit: int = 500) -> int:
        """Fingerprint images stored before deduplication existed."""
        if self._embedder is None:
            raise ProfileGenerationError("Embedding model is disabled (AIC_EMBEDDING_MODEL)")
        pending = await self._repository.images_without_fingerprint(limit)
        downloaded = await download_images([image["image_url"] for image in pending])
        done = [image for image in pending if image["image_url"] in downloaded]
        vectors = await self._embedder.embed_many([downloaded[i["image_url"]] for i in done])
        for image, vector in zip(done, vectors, strict=True):
            phash = dhash(downloaded[image["image_url"]])
            await self._repository.set_fingerprint(image["image_id"], f"{phash:016x}", vector)
            if image.get("status") == "check_failed":
                await self._repository.set_image_status(image["image_id"], "pending")
        return len(done)

    async def reference_queue(self, limit: int) -> list[dict[str, str]]:
        """Pinterest searches of approved profiles that were not crawled yet."""
        done = await self._repository.done_searches()
        queue = [
            {
                "url": _PINTEREST_SEARCH + quote_plus(query),
                "product_type": p.product_type,
                "query": query,
            }
            for p in await self._repository.list_profiles()
            if p.status == "approved"
            for query in p.keywords
            if (p.product_type, query) not in done
        ]
        return queue[:limit]

    async def reference_images(
        self, status: str | None, product_type: str | None
    ) -> list[dict[str, Any]]:
        images = await self._repository.list_reference_images(status, product_type)
        return list(reversed(images))

    async def screen_images(self, limit: int) -> dict[str, int]:
        """Review pending images with the vision model: usable ones go live, the rest are rejected."""
        if self._reviewer is None:
            raise ProfileGenerationError("LLM is not configured (AIC_SCREENING_API_KEY)")
        pending = (await self._repository.list_reference_images("pending", None))[:limit]
        reviews = await self._reviewer.review_all(pending)
        counts = {"reviewed": 0, "usable": 0, "rejected": 0, "failed": 0}
        for image_id, review in reviews.items():
            if review is None:
                counts["failed"] += 1
                continue
            usable = bool(review["usable"])
            await self._repository.set_image_screening(
                image_id, review, "live" if usable else "rejected"
            )
            counts["reviewed"] += 1
            counts["usable" if usable else "rejected"] += 1
        return counts

    async def redescribe_images(self, limit: int) -> dict[str, int]:
        """Describe in full the images reviewed before reviews carried detail; their status stays."""
        if self._reviewer is None:
            raise ProfileGenerationError("LLM is not configured (AIC_SCREENING_API_KEY)")
        todo = [
            image
            for image in await self._repository.list_reference_images(None, None)
            if image["status"] in ("live", "rejected")
            and image["screening"] is not None
            and not image["screening"].get("setting")
        ]
        images = todo[:limit]
        reviews = await self._reviewer.review_all(images)
        counts = {"described": 0, "failed": 0, "left": len(todo) - len(images)}
        for image_id, review in reviews.items():
            if review is None:
                counts["failed"] += 1
                continue
            await self._repository.set_image_screening(image_id, review, None)
            counts["described"] += 1
        return counts

    async def create_brief(
        self, product_id: str, user_idea: str = "", video_seconds: int = CLIP_SECONDS
    ) -> dict[str, Any] | None:
        """Draft one brief for a selected product from varied live reference scenes.

        Every shot becomes one 15 second clip, so the video length sets the number of shots.
        """
        if video_seconds not in VIDEO_LENGTHS:
            raise BriefUnavailable(f"Video length must be one of {list(VIDEO_LENGTHS)} seconds")
        detail = await self._repository.get_detail(product_id)
        if detail is None:
            return None
        if self._briefer is None:
            raise ProfileGenerationError("LLM is not configured (AIC_SCREENING_API_KEY)")
        product_type = (await self._repository.selections()).get(product_id)
        if not product_type:
            raise BriefUnavailable("Select this product for content before writing a brief")
        live = await self.reference_images("live", product_type)
        vectors = {
            item["image_id"]: item["embedding"]
            for item in await self._repository.fingerprints(product_type)
        }
        varied = _diverse(
            [{**image, "embedding": vectors.get(image["image_id"])} for image in live],
            MAX_REFERENCES,
        )
        references = [{k: v for k, v in image.items() if k != "embedding"} for image in varied]
        if not references:
            raise BriefUnavailable(
                f"No usable reference image of type '{product_type}' yet; crawl Pinterest first"
            )
        shot_count = max(1, round(video_seconds / shot_seconds(CLIP_SECONDS)))
        fixes = ""
        attempts = 0
        for _ in range(BRIEF_ATTEMPTS):
            attempts += 1
            brief = await self._briefer.write(
                detail, f"{user_idea}{fixes}", references, shot_count=shot_count
            )
            count_ok = "shots" not in brief or len(brief["shots"]) == shot_count
            problems = await self._review_storyboard(detail, brief) if count_ok else []
            if count_ok and not problems:
                break
            wanted = [] if count_ok else [f"Write exactly {shot_count} shots."]
            fixes = "\n\nRewrite the storyboard and fix these problems:\n- " + "\n- ".join(
                wanted + problems
            )
        if not count_ok:
            raise BriefGenerationError(
                f"The model wrote {len(brief['shots'])} shots instead of {shot_count}; try again"
            )
        brief["quality_problems"] = problems
        brief["warnings"] = brief_warnings(brief)
        if brief.get("persona"):
            brief["persona"] = {
                "description": str(brief["persona"]),
                "image_path": None,
                "status": "none",
                "attempts": 0,
            }
        await self._repository.save_brief(product_id, user_idea.strip(), brief, "draft")
        await self._log(
            product_id,
            "brief",
            "flagged" if problems else "ok",
            f"Wrote a {video_seconds}s brief with {len(brief.get('shots') or [])} shot(s) in "
            f"{attempts} attempt(s): {brief.get('title', '')}"
            + (f". Still open: {'; '.join(problems)}" if problems else ""),
        )
        return await self._repository.get_brief(product_id)

    async def _review_storyboard(self, product: dict[str, Any], brief: dict[str, Any]) -> list[str]:
        """Problems the reviewer found; none when there is no reviewer or the review failed."""
        if self._storyboard_reviewer is None or not brief.get("shots"):
            return []
        return await self._storyboard_reviewer.review(product, brief) or []

    def media(self, media_root: Path) -> MediaStore:
        """The store of generated files: the local folder plus the remote copy, when set up."""
        return MediaStore(Path(media_root), self._remote_media)

    async def _log(
        self, product_id: str, step: str, status: str, message: str, shot_index: int | None = None
    ) -> None:
        """Add a line to the run log; the log must never break the step it describes."""
        try:
            await self._repository.add_event(product_id, step, shot_index, status, message[:600])
        except Exception as error:  # noqa: BLE001
            logger.warning("Could not write the run log: {}", error)

    async def events(self, product_id: str) -> list[dict[str, Any]]:
        return await self._repository.list_events(product_id)

    async def get_brief(self, product_id: str) -> dict[str, Any] | None:
        return await self._repository.get_brief(product_id)

    async def list_briefs(self) -> list[dict[str, Any]]:
        return await self._repository.list_briefs()

    async def update_brief(
        self, product_id: str, changes: dict[str, Any], status: str
    ) -> dict[str, Any] | None:
        """Apply human edits to a brief and set its review status."""
        current = await self._repository.get_brief(product_id)
        if current is None:
            return None
        brief = {**current["brief"], **{k: v for k, v in changes.items() if k in BRIEF_FIELDS}}
        brief["warnings"] = brief_warnings(brief)
        brief.setdefault("quality_problems", [])
        if brief.get("shots") != current["brief"].get("shots"):
            # only a changed storyboard is worth a new review, which takes a minute
            detail = await self._repository.get_detail(product_id)
            brief["quality_problems"] = (
                await self._review_storyboard(detail, brief) if detail else []
            )
        await self._repository.save_brief(product_id, current["user_idea"], brief, status)
        return await self._repository.get_brief(product_id)

    async def list_keyframes(self, product_id: str) -> list[dict[str, Any]]:
        return await self._repository.list_keyframes(product_id)

    async def set_keyframe_status(self, product_id: str, shot_index: int, status: str) -> bool:
        if status not in KEYFRAME_REVIEW_STATUSES:
            raise ValueError(f"Keyframe status must be one of {sorted(KEYFRAME_REVIEW_STATUSES)}")
        changed = await self._repository.set_keyframe_status(product_id, shot_index, status)
        if changed:
            await self._log(product_id, "keyframe", status, f"Marked {status}", shot_index)
        return changed

    async def generate_persona(
        self, product_id: str, media_root: Path, description: str | None = None
    ) -> dict[str, Any] | None:
        """Make (or remake) the portrait of the recurring person; a human approves it."""
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        if self._keyframer is None:
            raise KeyframeUnavailable("Image model is not configured (AIC_IMAGE_MODEL)")
        persona = dict(record["brief"].get("persona") or {})
        text = (
            description if description is not None else persona.get("description") or ""
        ).strip()
        if not text:
            raise KeyframeUnavailable("This brief has no person yet; regenerate the brief first")
        try:
            image = await self._keyframer.persona(text)
        except KeyframeGenerationError as error:
            await self._log(product_id, "persona", "error", str(error))
            raise KeyframeUnavailable(f"The person could not be made: {error}") from error
        relative = f"persona/{product_id}/persona.jpg"
        await self.media(media_root).write(relative, image)
        persona = {
            "description": text,
            "image_path": relative,
            "status": "ready",
            "attempts": int(persona.get("attempts") or 0) + 1,
        }
        brief = {**record["brief"], "persona": persona}
        await self._repository.save_brief(product_id, record["user_idea"], brief, record["status"])
        await self._log(
            product_id, "persona", "ok", f"Portrait made (attempt {persona['attempts']})"
        )
        return persona

    async def set_persona_status(self, product_id: str, status: str) -> bool:
        if status not in PERSONA_STATUSES:
            raise ValueError(f"Person status must be one of {sorted(PERSONA_STATUSES)}")
        record = await self._repository.get_brief(product_id)
        persona = (record or {}).get("brief", {}).get("persona")
        if record is None or not persona or not persona.get("image_path"):
            return False
        brief = {**record["brief"], "persona": {**persona, "status": status}}
        await self._repository.save_brief(product_id, record["user_idea"], brief, record["status"])
        return True

    async def generate_keyframes(
        self, product_id: str, media_root: Path, shot_index: int | None = None
    ) -> list[dict[str, Any]] | None:
        """Make the master keyframe first; after a human approves it, make the other shots.

        With shot_index None the next step runs: the master when it is not approved yet, else
        every other shot that is not approved. An explicit shot_index regenerates only that shot.
        """
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        if self._keyframer is None:
            raise KeyframeUnavailable("Image model is not configured (AIC_IMAGE_MODEL)")
        shots = record["brief"].get("shots") or []
        if not shots:
            raise KeyframeUnavailable("This brief has no storyboard; regenerate the brief first")
        existing = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        master_ready = existing.get(0, {}).get("status") == "approved"
        if shot_index is not None and not 0 <= shot_index < len(shots):
            raise KeyframeUnavailable(f"Shot {shot_index} does not exist")
        if shot_index is not None:
            wanted = [shot_index]
        elif master_ready:
            wanted = [
                i for i in range(1, len(shots)) if existing.get(i, {}).get("status") != "approved"
            ]
        else:
            wanted = [0]
        if any(i > 0 for i in wanted) and not master_ready:
            raise KeyframeUnavailable("Approve the master keyframe (shot 0) first")
        persona = record["brief"].get("persona") or {}
        persona_image: bytes | None = None
        if persona.get("description"):
            if persona.get("status") != "approved" or not persona.get("image_path"):
                raise KeyframeUnavailable("Approve the person's portrait first")
            persona_image = await self.media(media_root).read(persona["image_path"])
        detail = await self._repository.get_detail(product_id)
        photos = await fetch_images(_product_photo_urls(record["brief"], detail or {}))
        if not photos:
            raise KeyframeUnavailable("No product photo could be downloaded")
        scene = await self._primary_scene(record["brief"]) if 0 in wanted else None
        master = (
            await self.media(media_root).read(existing[0]["image_path"]) if master_ready else None
        )
        size = str(record["brief"].get("product_size") or "")
        for index in wanted:
            await self._make_keyframe(
                product_id,
                index,
                {**shots[index], "product_size": size},
                existing.get(index),
                media_root,
                photos,
                scene,
                master,
                persona_image,
            )
        return await self._repository.list_keyframes(product_id)

    async def _primary_scene(self, brief: dict[str, Any]) -> bytes | None:
        ids = brief.get("selected_reference_ids") or []
        if not ids:
            return None
        for image in await self._repository.list_reference_images(None, None):
            if image["image_id"] == ids[0]:
                found = await fetch_images([image["image_url"]])
                return found[0] if found else None
        return None

    async def _make_keyframe(
        self,
        product_id: str,
        index: int,
        shot: dict[str, Any],
        previous: dict[str, Any] | None,
        media_root: Path,
        photos: list[bytes],
        scene: bytes | None,
        master: bytes | None,
        persona: bytes | None = None,
    ) -> None:
        assert self._keyframer is not None
        attempts = (previous or {}).get("attempts", 0)
        before = await self._keyframe_before(product_id, index, media_root)
        record = {
            "product_id": product_id,
            "shot_index": index,
            "prompt": str(shot["keyframe_prompt"]),
            "image_path": (previous or {}).get("image_path"),
        }
        image: bytes | None = None
        problem = ""
        for _ in range(1 + MAX_KEYFRAME_FIXES):
            try:
                if index == 0:
                    candidate = await self._keyframer.master(shot, photos, scene, problem, persona)
                else:
                    candidate = await self._keyframer.follow_up(
                        shot, master or b"", photos, problem, persona
                    )
            except KeyframeGenerationError as error:
                attempts += 1
                await self._log(product_id, "keyframe", "error", str(error), index)
                if image is None:
                    await self._repository.save_keyframe(
                        {
                            **record,
                            "attempts": attempts,
                            "status": "failed",
                            "error": str(error),
                            "qa_problem": "",
                        }
                    )
                    return
                break
            attempts += 1
            image = candidate
            problem = await self._check_keyframe(shot, photos, image, master, persona, before) or ""
            if not problem:
                break
            await self._log(
                product_id, "keyframe", "retry", f"Attempt {attempts}: Gemini says {problem}", index
            )
        assert image is not None
        relative = f"keyframes/{product_id}/shot_{index}.jpg"
        await self.media(media_root).write(relative, image)
        await self._repository.save_keyframe(
            {
                **record,
                "attempts": attempts,
                "status": "ready",
                "image_path": relative,
                "error": None,
                "qa_problem": problem,
            }
        )
        await self._log(
            product_id,
            "keyframe",
            "flagged" if problem else "ok",
            f"Image ready after {attempts} attempt(s)"
            + (f", still flagged: {problem}" if problem else ""),
            index,
        )

    async def _keyframe_before(self, product_id: str, index: int, media_root: Path) -> bytes | None:
        """The image of the shot just before this one, so the cut between them can be checked."""
        if index < 2:
            return None  # shot 1 follows the master, which is already its reference
        for keyframe in await self._repository.list_keyframes(product_id):
            if keyframe["shot_index"] == index - 1 and keyframe.get("image_path"):
                found = await self.media(media_root).fetch(keyframe["image_path"])
                return found.read_bytes() if found else None
        return None

    async def _check_keyframe(
        self,
        shot: dict[str, Any],
        photos: list[bytes],
        image: bytes,
        master: bytes | None,
        persona: bytes | None = None,
        before: bytes | None = None,
    ) -> str | None:
        if self._checker is None:
            return None
        description = str(shot.get("description") or shot["keyframe_prompt"])
        if shot.get("product_size"):
            description = f"{description} Real size of the product: {shot['product_size']}"
        return await self._checker.check(description, photos, image, master, persona, before)

    async def clips(self, product_id: str, media_root: Path) -> list[dict[str, Any]]:
        """List clips, first collecting the ones whose video job has finished."""
        clips = await self._repository.list_clips(product_id)
        if self._videographer is None:
            return clips
        for clip in clips:
            if clip["status"] == "processing":
                await self._collect_clip(clip, media_root)
        return await self._repository.list_clips(product_id)

    async def _collect_clip(self, clip: dict[str, Any], media_root: Path) -> None:
        assert self._videographer is not None
        try:
            state = await self._videographer.status(clip["job_id"], clip["job_model"])
            if state.status == "completed" and state.video_url:
                content = await self._videographer.download(state.video_url)
                relative = f"clips/{clip['product_id']}/shot_{clip['shot_index']}.mp4"
                await self.media(media_root).write(relative, content)
                update = {"status": "ready", "video_path": relative, "error": None}
                await self._log(
                    clip["product_id"], "clip", "ok", "Clip downloaded", clip["shot_index"]
                )
            elif state.status == "failed":
                update = {"status": "failed", "error": state.error or "The video job failed"}
                await self._log(
                    clip["product_id"], "clip", "error", update["error"], clip["shot_index"]
                )
            else:
                return
        except ClipGenerationError:
            return
        await self._repository.save_clip({**clip, **update})

    async def generate_clips(
        self, product_id: str, media_root: Path, shot_index: int | None = None
    ) -> list[dict[str, Any]] | None:
        """Start a video job for each approved keyframe that has no clip yet.

        An explicit shot_index starts that shot again, which costs one more clip.
        """
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        if self._videographer is None:
            raise KeyframeUnavailable("Video model is not configured (AIC_VIDEO_MODEL)")
        shots = record["brief"].get("shots") or []
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        clips = {c["shot_index"]: c for c in await self._repository.list_clips(product_id)}
        approved = [
            i for i in range(len(shots)) if keyframes.get(i, {}).get("status") == "approved"
        ]
        if shot_index is not None:
            if shot_index not in approved:
                raise KeyframeUnavailable("Approve this shot's keyframe first")
            wanted = [shot_index]
        else:
            wanted = [
                i for i in approved if clips.get(i, {}).get("status") not in ("processing", "ready")
            ]
        if not wanted:
            raise KeyframeUnavailable("No approved keyframe is waiting for a clip")
        for index in wanted:
            await self._start_clip(
                product_id, index, shots[index], keyframes[index], clips.get(index), media_root
            )
        return await self._repository.list_clips(product_id)

    async def _start_clip(
        self,
        product_id: str,
        index: int,
        shot: dict[str, Any],
        keyframe: dict[str, Any],
        previous: dict[str, Any] | None,
        media_root: Path,
    ) -> None:
        assert self._videographer is not None
        seconds = CLIP_SECONDS
        clip = {
            "product_id": product_id,
            "shot_index": index,
            "job_id": None,
            "job_model": None,
            "video_path": (previous or {}).get("video_path"),
            "seconds": seconds,
            "attempts": (previous or {}).get("attempts", 0) + 1,
        }
        delivery = str(shot.get("delivery") or "narrated")
        if delivery == "talking":
            sound = (
                f"{_DELIVERY_RULE[True]} The person says in Vietnamese, in one go: "
                f'"{shot.get("voiceover") or ""}" No music, no text on screen.'
            )
        else:
            sound = (
                f"{_DELIVERY_RULE[False]} The clip has no sound: no dialogue, no music, "
                "no text on screen."
            )
        frame = await self.media(media_root).read(keyframe["image_path"])
        prompt = (
            f"{shot.get('motion_prompt') or 'Slow gentle camera push-in.'} "
            "Keep the product's exact shape, color and details; do not add or change objects. "
            "Energetic TikTok pace: brisk natural movement and quick camera moves, "
            "never slow motion, no long pauses. "
            f"{sound}"
        )
        try:
            job_id, job_model = await self._videographer.submit(prompt, frame, seconds)
        except ClipGenerationError as error:
            await self._repository.save_clip({**clip, "status": "failed", "error": str(error)})
            await self._log(product_id, "clip", "error", str(error), index)
            return
        await self._repository.save_clip(
            {
                **clip,
                "status": "processing",
                "job_id": job_id,
                "job_model": job_model,
                "error": None,
            }
        )
        await self._log(product_id, "clip", "started", f"Video job started ({delivery})", index)

    async def create_post_package(self, product_id: str) -> dict[str, Any] | None:
        """Write caption options and hashtags for the video and keep them on the brief."""
        record = await self._repository.get_brief(product_id)
        detail = await self._repository.get_detail(product_id)
        if record is None or detail is None:
            return None
        if self._poster is None:
            raise KeyframeUnavailable("LLM is not configured (AIC_SCREENING_API_KEY)")
        package = await self._poster.write(detail, record["brief"])
        package["warnings"] = package_warnings(package)
        package["ai_label_reminder"] = AI_LABEL_REMINDER
        brief = {**record["brief"], "post_package": package}
        await self._repository.save_brief(product_id, record["user_idea"], brief, record["status"])
        await self._log(
            product_id, "post", "ok", f"Wrote {len(package.get('captions') or [])} caption(s)"
        )
        return package

    async def create_voiceover(
        self, product_id: str, media_root: Path, voice: str | None = None
    ) -> dict[str, Any] | None:
        """Read each approved shot's voice-over so its words start with the shot."""
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        if self._speaker is None:
            raise KeyframeUnavailable("Text-to-speech is not configured (AIC_TTS_MODEL)")
        if voice and voice not in VOICES:
            raise KeyframeUnavailable(f"Unknown voice {voice}")
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        shots = record["brief"].get("shots") or []
        approved = [
            i for i in range(len(shots)) if keyframes.get(i, {}).get("status") == "approved"
        ]
        if not approved:
            raise KeyframeUnavailable("Approve at least one keyframe first")
        talking = any(shots[i].get("delivery") == "talking" for i in approved)
        clips = (
            {c["shot_index"]: c for c in await self.clips(product_id, media_root)}
            if talking
            else {}
        )
        segments: list[Reading] = []
        for index in approved:
            shot = shots[index]
            guide = None
            if shot.get("delivery") == "talking":
                clip = clips.get(index)
                if clip is not None and clip["status"] == "ready":
                    guide = await self.media(media_root).fetch(clip["video_path"])
                if guide is None:
                    raise KeyframeUnavailable(
                        f"Make the clip for shot {index + 1} first: its voice follows the "
                        "speech Grok made with the clip"
                    )
            seconds = min(float(shot.get("duration_seconds") or CLIP_SECONDS), CLIP_SECONDS)
            segments.append(Reading(str(shot.get("voiceover") or ""), shot_seconds(seconds), guide))
        store = self.media(media_root)
        folder = store.path(f"videos/{product_id}")
        folder.mkdir(parents=True, exist_ok=True)
        for extension in VOICEOVER_TYPES.values():
            await store.remove(f"videos/{product_id}/voiceover.{extension}")
        try:
            lengths = await make_voiceover(self._speaker, segments, folder / "voiceover.mp3", voice)
            await store.push(f"videos/{product_id}/voiceover.mp3")
            await self.note_voice(
                product_id, media_root, VOICES.get(voice or "", voice or "default")
            )
        except (SpeechError, StitchUnavailable) as error:
            raise KeyframeUnavailable(f"The voice-over could not be made: {error}") from error
        too_long = [
            i + 1
            for i, (n, reading) in enumerate(zip(lengths, segments, strict=True))
            if n > reading.seconds * MAX_SPEEDUP
        ]
        await self._log(
            product_id,
            "voiceover",
            "warning" if too_long else "ok",
            f"Read in voice {voice or 'default'}; shots {[round(n, 1) for n in lengths]} s"
            + (f"; too long: {too_long}" if too_long else ""),
        )
        return {
            "voiceover": "mp3",
            "seconds": [round(n, 1) for n in lengths],
            "too_long_shots": too_long,
        }

    async def voice_sample(self, voice: str, media_root: Path) -> Path:
        """A short reading in one voice, made once and kept so listening again costs nothing."""
        if self._speaker is None:
            raise KeyframeUnavailable("Text-to-speech is not configured (AIC_TTS_MODEL)")
        if voice not in VOICES:
            raise KeyframeUnavailable(f"Unknown voice {voice}")
        relative = f"voice_samples/{voice.removesuffix('.mp3')}.mp3"
        store = self.media(media_root)
        found = await store.fetch(relative)
        if found is None:
            try:
                audio = await self._speaker.speak(SAMPLE_TEXT, voice)
            except SpeechError as error:
                raise KeyframeUnavailable(f"The sample could not be made: {error}") from error
            found = await store.write(relative, audio)
        return found

    async def build_video(
        self, product_id: str, media_root: Path, captions: bool = False
    ) -> str | None:
        """Stitch the ready clips of approved shots, in story order, into one mp4.

        Captions are only burned into the picture when asked for, since the text can cover the
        product.
        """
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        shots = record["brief"].get("shots") or []
        clips = {c["shot_index"]: c for c in await self.clips(product_id, media_root)}
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        parts: list[StitchClip] = []
        used: dict[int, int] = {}
        for index, shot in enumerate(shots):
            if keyframes.get(index, {}).get("status") != "approved":
                continue
            clip = clips.get(index)
            if clip is None or clip["status"] != "ready":
                raise StitchUnavailable(f"The clip for shot {index + 1} is not ready yet")
            duration = min(float(shot.get("duration_seconds") or clip["seconds"]), clip["seconds"])
            caption = str(shot.get("on_screen_text") or "") if captions else ""
            local = await self.media(media_root).fetch(clip["video_path"])
            if local is None:
                raise StitchUnavailable(f"The clip file for shot {index + 1} is missing")
            parts.append(StitchClip(local, duration, caption))
            used[index] = clip["attempts"]
        relative = f"videos/{product_id}/video.mp4"
        store = self.media(media_root)
        await store.fetch_first(
            [f"videos/{product_id}/voiceover.{ext}" for ext in VOICEOVER_TYPES.values()]
        )
        voice = find_voiceover(media_root, product_id)
        await stitch(parts, store.path(relative), voice)
        await store.push(relative)
        cover = f"videos/{product_id}/cover.jpg"
        await cover_frame(store.path(relative), store.path(cover))
        await store.push(cover)
        await self._write_json(
            media_root,
            f"videos/{product_id}/video.json",
            {
                "built_at": datetime.now(UTC).isoformat(),
                "captions": captions,
                "seconds": round(sum(shot_seconds(p.duration) for p in parts), 1),
                "clip_attempts": used,
                "voice": await self._read_json(media_root, f"videos/{product_id}/voiceover.json"),
            },
        )
        await self._log(
            product_id,
            "video",
            "ok",
            f"Stitched {len(parts)} clip(s), voice-over {'yes' if voice else 'no'}, "
            f"captions {'yes' if captions else 'no'}",
        )
        return relative

    async def _write_json(self, media_root: Path, relative: str, data: dict[str, Any]) -> None:
        await self.media(media_root).write(relative, json.dumps(data, ensure_ascii=False).encode())

    async def _read_json(self, media_root: Path, relative: str) -> dict[str, Any] | None:
        try:
            return json.loads(await self.media(media_root).read(relative))
        except FileNotFoundError:
            return None

    async def note_voice(self, product_id: str, media_root: Path, voice: str) -> None:
        """Remember which voice read the voice-over, for the page that shows what a video is made of."""
        await self._write_json(
            media_root,
            f"videos/{product_id}/voiceover.json",
            {"voice": voice, "made_at": datetime.now(UTC).isoformat()},
        )

    async def list_outputs(self, media_root: Path) -> list[dict[str, Any]]:
        """The finished videos, newest first."""
        store = self.media(media_root)
        outputs = []
        for record in await self._repository.list_briefs():
            product_id = record["product_id"]
            if not await store.exists(f"videos/{product_id}/video.mp4"):
                continue
            detail = await self._repository.get_detail(product_id) or {}
            built = await self._read_json(media_root, f"videos/{product_id}/video.json") or {}
            outputs.append(
                {
                    "product_id": product_id,
                    "title": record["brief"].get("title"),
                    "product_title": detail.get("title"),
                    "image": next(iter(detail.get("images") or []), None),
                    "built_at": built.get("built_at"),
                    "seconds": built.get("seconds"),
                    "shots": len(built.get("clip_attempts") or record["brief"].get("shots") or []),
                    "voice": (built.get("voice") or {}).get("voice"),
                    "has_cover": await store.exists(f"videos/{product_id}/cover.jpg"),
                }
            )
        return sorted(outputs, key=lambda item: item["built_at"] or "", reverse=True)

    async def get_output(self, product_id: str, media_root: Path) -> dict[str, Any] | None:
        """What a finished video is made from: product, photos, references, person and shots."""
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        brief = record["brief"]
        detail = await self._repository.get_detail(product_id) or {}
        built = await self._read_json(media_root, f"videos/{product_id}/video.json") or {}
        voice = built.get("voice") or await self._read_json(
            media_root, f"videos/{product_id}/voiceover.json"
        )
        chosen = set(brief.get("selected_reference_ids") or [])
        references = [
            {key: image.get(key) for key in ("image_id", "image_url", "pin_url", "title")}
            for image in await self._repository.list_reference_images(None, None)
            if image["image_id"] in chosen
        ]
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        clips = {c["shot_index"]: c for c in await self._repository.list_clips(product_id)}
        in_video = {int(index) for index in built.get("clip_attempts") or {}}
        shots = [
            {
                "index": index,
                "role": shot.get("role"),
                "delivery": shot.get("delivery") or "narrated",
                "description": shot.get("description"),
                "voiceover": shot.get("voiceover"),
                "on_screen_text": shot.get("on_screen_text"),
                "has_keyframe": bool(keyframes.get(index, {}).get("image_path")),
                "keyframe_attempts": keyframes.get(index, {}).get("attempts"),
                "has_clip": clips.get(index, {}).get("status") == "ready",
                "clip_attempts": clips.get(index, {}).get("attempts"),
                "in_video": index in in_video,
            }
            for index, shot in enumerate(brief.get("shots") or [])
        ]
        persona = brief.get("persona") or {}
        return {
            "product": {
                "product_id": product_id,
                "title": detail.get("title"),
                "url": detail.get("url"),
                "image": next(iter(detail.get("images") or []), None),
            },
            "brief": {
                "title": brief.get("title"),
                "status": record["status"],
                "format": brief.get("format"),
                "user_idea": record["user_idea"],
                "selling_angle": brief.get("selling_angle"),
                "target_audience": brief.get("target_audience"),
                "product_size": brief.get("product_size"),
            },
            "product_photos": brief.get("product_photo_urls") or [],
            "references": references,
            "persona": {
                "description": persona.get("description"),
                "has_image": bool(persona.get("image_path")),
            }
            if persona.get("description")
            else None,
            "shots": shots,
            "video": {
                "built_at": built.get("built_at"),
                "seconds": built.get("seconds"),
                "captions": built.get("captions"),
                "voice": (voice or {}).get("voice"),
                "has_cover": await self.media(media_root).exists(f"videos/{product_id}/cover.jpg"),
                "exists": await self.media(media_root).exists(f"videos/{product_id}/video.mp4"),
            },
        }

    async def delete_product(self, product_id: str, media_root: Path) -> bool:
        """Delete a product with its brief, images, clips and video; it is not collected again."""
        deleted = await self._repository.delete_product(product_id)
        if deleted:
            store = self.media(media_root)
            for folder in ("persona", "keyframes", "clips", "videos"):
                await store.remove_tree(f"{folder}/{product_id}")
        return deleted

    async def set_image_status(self, image_id: str, status: str) -> bool:
        return await self._repository.set_image_status(image_id, status)

    async def queue(self, limit: int) -> list[str]:
        return await self._repository.queue(limit)

    async def details(self, include_junk: bool = False) -> list[dict[str, Any]]:
        products = await self._repository.list_details()
        return products if include_junk else [p for p in products if junk_reason(p) is None]

    async def download_media(self, media_root: Path) -> MediaDownloadReport:
        return await download_product_media(await self.details(), media_root)

    async def listing(self) -> list[dict[str, Any]]:
        return await self._repository.list_listing()

    async def detail(self, product_id: str) -> dict[str, Any] | None:
        return await self._repository.get_detail(product_id)

    async def select(self, product_id: str, regenerate: bool = False) -> dict[str, Any] | None:
        """Mark a product for content; draft its reference search profile when an LLM is set.

        With regenerate, the keywords of an existing product type are replaced by a new draft.
        """
        detail = await self._repository.get_detail(product_id)
        if detail is None:
            return None
        await self._repository.select_product(product_id, None)
        result: dict[str, Any] = {"product_id": product_id, "profile": None, "error": None}
        if self._generator is None:
            result["error"] = "LLM is not configured (AIC_SCREENING_API_KEY)"
            return result
        try:
            profile = await self._generator.generate(detail)
        except ProfileGenerationError as error:
            result["error"] = str(error)
            return result
        await self._repository.add_profile_if_missing(profile)
        if regenerate:
            await self._repository.update_profile(profile)
        await self._repository.select_product(product_id, profile.product_type)
        result["profile"] = profile.as_dict()
        return result

    async def mark_selected(self, product_id: str) -> bool:
        """Put a product in the selected list straight away, before its keyword exists."""
        if await self._repository.get_detail(product_id) is None:
            return False
        selections = await self._repository.selections()
        if product_id not in selections:
            await self._repository.select_product(product_id, None)
        return True

    async def selections(self) -> dict[str, str | None]:
        return await self._repository.selections()

    async def profiles(self) -> list[ReferenceProfile]:
        return await self._repository.list_profiles()

    async def update_profile(self, profile: ReferenceProfile) -> bool:
        return await self._repository.update_profile(profile)

    async def export_workbook(self) -> bytes:
        return build_workbook(await self.details())


def _video(product: dict[str, Any]) -> dict[str, Any] | None:
    raw = product.get("raw_product_info") or {}
    return raw.get("header_video") or raw.get("desc_video")


def _sheet(book: Workbook, title: str, header: list[str], rows: list[list[Any]]) -> None:
    sheet = book.create_sheet(title)
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(
            [json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v for v in row]
        )
    sheet.freeze_panes = "A2"


def build_workbook(products: list[dict[str, Any]]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    rows = []
    for product in products:
        stars = product.get("rating_distribution") or {}
        shop = product.get("shop") or {}
        ship = product.get("shipping") or {}
        seller = product.get("seller") or {}
        price = product.get("price") or {}
        video = _video(product)
        rows.append(
            [
                product["product_id"],
                product.get("title"),
                str(product.get("url", "")).split("?")[0],
                " > ".join(product.get("categories") or []),
                seller.get("name"),
                seller.get("id"),
                price.get("sale"),
                price.get("original"),
                price.get("discount"),
                price.get("currency"),
                product.get("sold_count"),
                product.get("rating"),
                product.get("review_count"),
                *(stars.get(str(star)) for star in (5, 4, 3, 2, 1)),
                ship.get("free_shipping"),
                ship.get("delivery_name"),
                seller.get("rating"),
                shop.get("followers_count"),
                shop.get("on_sell_product_count"),
                len(product.get("images") or []),
                len(product.get("variants") or []),
                bool(video),
                (video or {}).get("duration"),
                (product.get("images") or [None])[0],
                product.get("description"),
                product.get("specifications"),
            ]
        )
    _sheet(
        book,
        "products",
        [
            "product_id", "title", "url", "category_path", "shop_name", "seller_id",
            "price_sale", "price_original", "discount", "currency", "sold_count", "rating",
            "review_count", "star_5", "star_4", "star_3", "star_2", "star_1", "free_shipping",
            "delivery", "shop_rating", "shop_followers", "shop_products", "images_count",
            "variants_count", "has_video", "video_seconds", "main_image", "description",
            "specifications",
        ],
        rows,
    )  # fmt: skip
    _sheet(
        book,
        "variants",
        ["product_id", "sku_id", "variant", "price", "original_price", "stock", "status"],
        [
            [
                p["product_id"],
                v.get("sku_id"),
                v.get("variant"),
                v.get("price"),
                v.get("original_price"),
                v.get("stock"),
                v.get("status"),
            ]
            for p in products
            for v in p.get("variants") or []
        ],
    )
    _sheet(
        book,
        "images",
        ["product_id", "position", "url"],
        [
            [p["product_id"], i + 1, url]
            for p in products
            for i, url in enumerate(p.get("images") or [])
        ],
    )
    video_rows = []
    for product in products:
        video = _video(product)
        for info in (video or {}).get("video_infos") or []:
            video_rows.append(
                [
                    product["product_id"],
                    video.get("id"),
                    video.get("duration"),
                    info.get("width"),
                    info.get("height"),
                    info.get("size"),
                    info.get("format"),
                    info.get("main_url"),
                    info.get("url_expire"),
                    video.get("post_url"),
                ]
            )
    _sheet(
        book,
        "videos",
        [
            "product_id", "video_id", "duration_s", "width", "height", "size_bytes",
            "format", "url", "url_expires_unix", "cover_url",
        ],
        video_rows,
    )  # fmt: skip
    _sheet(
        book,
        "specifications",
        ["product_id", "name", "value"],
        [
            [p["product_id"], k, v]
            for p in products
            for k, v in (p.get("specifications") or {}).items()
        ],
    )
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
