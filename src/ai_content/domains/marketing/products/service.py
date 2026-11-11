"""Ingest browser captures and export collected products."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from loguru import logger
from openpyxl import Workbook
from openpyxl.styles import Font

from ai_content.domains.marketing.creative_knowledge.models import (
    KnowledgeAuthority,
    KnowledgeStage,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService

from .briefing import (
    BriefGenerationError,
    BriefUnavailable,
    ContentBriefWriter,
    reference_note,
)
from .captions import spoken_cues
from .clip_check import ClipChecker
from .clips import (
    CLIP_SECONDS,
    ClipGenerationError,
    StitchClip,
    StitchUnavailable,
    VideoClient,
    caption_font,
    clip_frames,
    clip_seconds_for,
    cover_frame,
    shot_seconds,
    stitch,
)
from .compliance import AI_LABEL_REMINDER, brief_warnings, package_warnings, product_facts
from .embedding import ImageEmbedder, cosine, dhash, download_images, hamming
from .hooks import HookWriter
from .identity import PIN_SIZE_DIR, media_source_fingerprint
from .image_review import ReferenceImageReviewer
from .keyframe_check import KeyframeChecker
from .keyframes import KeyframeGenerationError, KeyframeGenerator, fetch_images, story_note
from .knowledge import approved_rules, propose_feedback
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
from .reference_ad import AdAnalyzer, ReferenceAdUnavailable
from .reference_picker import ShotReferencePicker
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
    spoken_seconds,
)
from .stickers import render_sticker, sticker_lines, stickers_by_shot
from .storyboard_review import StoryboardReviewer
from .text_embedding import TextEmbedder, TextEmbeddingError
from .video_check import LESSONS, VideoCheckUnavailable, judge, measure

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
KEYFRAME_CONCURRENCY = 3
CLIP_CHECK_PHOTOS = 4
MODEL_IMAGE_LIMIT = 30  # pictures the image model takes in one request
MODEL_IMAGE_RESERVE = 2  # kept free for the scene or master picture and a pose reference
# The voice-over is added later, so the picture only has to look right: a talking shot shows
# natural subtle speaking without exaggerated mouth movements, a narrated shot keeps lips closed.
_DELIVERY_RULE = {
    True: (
        "The person speaks naturally to the camera, subtle and gentle lip movement, "
        "relaxed facial expression, mouth does not open wide, no exaggerated mouth shapes."
    ),
    False: "Nobody speaks: lips stay closed or relaxed, no lip movement.",
}
_NO_PERSON_VIDEO = (
    "No person appears in the picture: no face and no body, only the product, the place and, "
    "when needed, hands. "
)
VIDEO_LENGTHS = (15, 30, 45, 60, 75, 90)
BRIEF_ATTEMPTS = 3
KEYFRAME_REVIEW_STATUSES = frozenset({"approved", "ready", "rejected"})
BRIEF_FIELDS = (
    "title",
    "product_variant",
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


REFERENCE_CANDIDATES = 5  # pictures a model compares for one shot
REFERENCE_LOOK_WEIGHT = 0.5  # how much looking like the product photos counts, next to the text


def _scaled(scores: dict[str, float]) -> dict[str, float]:
    """Scores moved to 0..1, so two kinds of similarity can be added."""
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    return {
        key: (value - low) / (high - low) if high > low else 0.0 for key, value in scores.items()
    }


def _product_photo_urls(brief: dict[str, Any], detail: dict[str, Any]) -> list[str]:
    """The product photos the brief picked; the first photos of the product if it picked none."""
    urls = brief.get("product_photo_urls") or [u for u in detail.get("images") or [] if u]
    return urls


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


VOICEOVER_TYPES = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
}


def video_folder(product_id: str, variant: str = "") -> str:
    """Where a product's video files live; a hook variant keeps its own files in a sub-folder."""
    return f"videos/{product_id}" + (f"/{variant}" if variant else "")


def find_voiceover(media_root: Path, product_id: str, variant: str = "") -> Path | None:
    """The voice-over file kept beside the stitched video, if there is one."""
    folder = Path(media_root) / video_folder(product_id, variant)
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
        text_embedder: TextEmbedder | None = None,
        reference_picker: ShotReferencePicker | None = None,
        clip_checker: ClipChecker | None = None,
        knowledge: CreativeKnowledgeService | None = None,
        ad_analyzer: AdAnalyzer | None = None,
        hook_writer: HookWriter | None = None,
    ) -> None:
        self._ad_analyzer = ad_analyzer
        self._hook_writer = hook_writer
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
        self._text_embedder = text_embedder
        self._reference_picker = reference_picker
        self._clip_checker = clip_checker
        self._knowledge = knowledge
        self._collecting: set[tuple[str, int]] = set()

    async def write_hooks(self, product_id: str, media_root: Path) -> list[dict[str, str]] | None:
        """Write alternative opening lines for the brief and keep them; None without a brief."""
        record = await self._repository.get_brief(product_id)
        detail = await self._repository.get_detail(product_id)
        if record is None or detail is None:
            return None
        if self._hook_writer is None:
            raise KeyframeUnavailable("The AI model is not configured (AIC_SCREENING_API_KEY)")
        rules = await approved_rules(self._knowledge, KnowledgeStage.PREPARATION, "brief")
        hooks = await self._hook_writer.write(detail, record["brief"], rules.text)
        if not hooks:
            raise KeyframeUnavailable(
                "No hook passed the checks (7 words or fewer, no flagged words, no invented "
                "numbers); try again"
            )
        stored = [{"id": f"hook_{n}", **hook} for n, hook in enumerate(hooks, start=1)]
        await self._write_json(media_root, f"videos/{product_id}/hooks.json", {"hooks": stored})
        return stored

    async def hooks(self, product_id: str, media_root: Path) -> list[dict[str, Any]]:
        """The saved hooks, each with whether its video has been made."""
        saved = (await self._read_json(media_root, f"videos/{product_id}/hooks.json")) or {}
        store = self.media(media_root)
        return [
            {**hook, "built": await store.exists(f"videos/{product_id}/{hook['id']}/video.mp4")}
            for hook in saved.get("hooks") or []
        ]

    async def build_hook_video(
        self,
        product_id: str,
        media_root: Path,
        hook_id: str,
        voice: str | None = None,
        captions: bool = False,
        stickers: bool = False,
    ) -> str | None:
        """Make the video for one saved hook from the clips already generated: no new clip."""
        hook = next(
            (h for h in await self.hooks(product_id, media_root) if h["id"] == hook_id), None
        )
        if hook is None:
            return None
        await self.create_voiceover(
            product_id, media_root, voice, variant=hook_id, hook=hook["text"]
        )
        return await self.build_video(
            product_id, media_root, captions, stickers, variant=hook_id, hook=hook["text"]
        )

    async def learn_from_reference_ad(self, content: bytes) -> list[dict[str, str]]:
        """Describe how an example ad is built and propose that as rules for a human to approve.

        The video is analysed from a temporary file and never kept.
        """
        if self._ad_analyzer is None or self._knowledge is None:
            raise KeyframeUnavailable("The AI model is not configured (AIC_SCREENING_API_KEY)")
        with tempfile.TemporaryDirectory() as scratch:
            video = Path(scratch) / "example_ad"
            video.write_bytes(content)
            try:
                rules = await self._ad_analyzer.analyze(video)
            except ReferenceAdUnavailable as error:
                raise KeyframeUnavailable(str(error)) from error
        if not rules:
            raise KeyframeUnavailable("The AI model could not describe that ad; try again")
        items = [
            await propose_feedback(
                self._knowledge,
                product_id="reference-ad",
                text=rule,
                contributor="reference-ad",
                authority=KnowledgeAuthority.EXTERNAL,
                asset_type="brief",
                once=True,
            )
            for rule in rules
        ]
        return [
            {"knowledge_id": item.knowledge_id, "text": item.content, "status": item.status.value}
            for item in items
        ]

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
        self,
        product_id: str,
        user_idea: str = "",
        video_seconds: int = CLIP_SECONDS,
        person_photos: list[bytes] | None = None,
    ) -> dict[str, Any] | None:
        """Draft one brief for a selected product from varied live reference scenes.

        Every shot becomes one 15 second clip, so the video length sets the number of shots.
        With person photos the video follows that person; without them it shows no person.
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
        if not live:
            raise BriefUnavailable(
                f"No usable reference image of type '{product_type}' yet; crawl Pinterest first"
            )
        shot_count = max(1, round(video_seconds / shot_seconds(CLIP_SECONDS)))
        rules = await approved_rules(self._knowledge, KnowledgeStage.PREPARATION, "brief")
        fixes = ""
        attempts = 0
        for _ in range(BRIEF_ATTEMPTS):
            attempts += 1
            brief = await self._briefer.write(
                detail,
                f"{user_idea}{fixes}",
                shot_count=shot_count,
                person_photos=person_photos,
                rules=rules.text,
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
        brief["warnings"] = brief_warnings(brief, product_facts(detail, user_idea))
        brief["shot_references"] = await self._pick_shot_references(
            product_id, detail, brief, live, product_type
        )
        brief["selected_reference_ids"] = list(
            dict.fromkeys(item for item in brief["shot_references"] if item)
        )
        brief["with_person"] = bool(person_photos)
        brief["rule_ids"] = rules.ids
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

    async def _reference_vectors(
        self, product_type: str, live: list[dict[str, Any]]
    ) -> dict[str, list[float]]:
        """The embedding of every live reference description; new ones are embedded and kept."""
        assert self._text_embedder is not None
        model = self._text_embedder.model
        stored = await self._repository.text_embeddings(product_type)
        vectors = {
            image_id: item["vector"] for image_id, item in stored.items() if item["model"] == model
        }
        missing = [
            (image["image_id"], note)
            for image in live
            if image["image_id"] not in vectors and (note := reference_note(image))
        ]
        if missing:
            fresh = await self._text_embedder.embed([note for _, note in missing])
            for (image_id, _), vector in zip(missing, fresh, strict=True):
                await self._repository.set_text_embedding(image_id, model, vector)
                vectors[image_id] = vector
        return vectors

    async def _product_look(
        self,
        product: dict[str, Any],
        brief: dict[str, Any],
        product_type: str,
        wanted: set[str],
    ) -> dict[str, float]:
        """How much each reference picture looks like the product photos, by image embedding.

        Empty when there is no image embedder or the product photos cannot be embedded; the
        references are then ranked by their text alone.
        """
        if self._embedder is None:
            return {}
        photos = await fetch_images(_product_photo_urls(brief, product))
        if not photos:
            return {}
        try:
            vectors = await self._embedder.embed_many(photos)
        except Exception as error:
            logger.warning("Product photos could not be embedded: {}", str(error)[:200])
            return {}
        stored = await self._repository.fingerprints(product_type)
        return _scaled(
            {
                item["image_id"]: max(cosine(vector, item["embedding"]) for vector in vectors)
                for item in stored
                if item["embedding"] and item["image_id"] in wanted
            }
        )

    async def _pick_shot_references(
        self,
        product_id: str,
        product: dict[str, Any],
        brief: dict[str, Any],
        live: list[dict[str, Any]],
        product_type: str,
    ) -> list[str | None]:
        """For every shot, the image id of the reference that fits it best, or None.

        The text of the shot is matched to the written descriptions of the references by
        embedding, and references that look like the product photos rank higher; a model then
        looks at the closest few pictures and keeps one, or none.
        """
        shots = brief.get("shots") or []
        none: list[str | None] = [None] * len(shots)
        if self._text_embedder is None or self._reference_picker is None:
            await self._log(
                product_id,
                "references",
                "warning",
                "No text embedding model: shots have no reference",
            )
            return none
        try:
            vectors = await self._reference_vectors(product_type, live)
            queries = await self._text_embedder.embed(
                [f"{shot.get('role', '')}. {shot.get('keyframe_prompt', '')}" for shot in shots]
            )
        except TextEmbeddingError as error:
            await self._log(product_id, "references", "error", str(error))
            return none
        pool = [image for image in live if image["image_id"] in vectors]
        looks = await self._product_look(
            product, brief, product_type, {i["image_id"] for i in pool}
        )
        picker = self._reference_picker

        async def pick(shot: dict[str, Any], query: list[float]) -> str | None:
            text = _scaled({i["image_id"]: cosine(query, vectors[i["image_id"]]) for i in pool})
            closest = sorted(
                pool,
                key=lambda image: (
                    text[image["image_id"]]
                    + REFERENCE_LOOK_WEIGHT * looks.get(image["image_id"], 0.0)
                ),
                reverse=True,
            )[:REFERENCE_CANDIDATES]
            return await picker.choose(
                product,
                shot,
                [
                    {"image_id": i["image_id"], "note": reference_note(i), "url": i["image_url"]}
                    for i in closest
                ],
            )

        picked = await asyncio.gather(*(pick(s, q) for s, q in zip(shots, queries, strict=True)))
        seen: set[str] = set()
        result: list[str | None] = []
        for image_id in picked:  # the same picture is not used twice
            result.append(image_id if image_id and image_id not in seen else None)
            if image_id:
                seen.add(image_id)
        await self._log(
            product_id,
            "references",
            "ok",
            f"Matched references to {sum(1 for item in result if item)} of {len(shots)} shot(s)",
        )
        return result

    async def match_references(self, product_id: str) -> dict[str, Any] | None:
        """Choose the reference of each shot again for the stored storyboard."""
        record = await self._repository.get_brief(product_id)
        detail = await self._repository.get_detail(product_id)
        product_type = (await self._repository.selections()).get(product_id)
        if record is None or detail is None or not product_type:
            return None
        live = await self.reference_images("live", product_type)
        brief = dict(record["brief"])
        brief["shot_references"] = await self._pick_shot_references(
            product_id, detail, brief, live, product_type
        )
        brief["selected_reference_ids"] = list(
            dict.fromkeys(item for item in brief["shot_references"] if item)
        )
        await self._repository.save_brief(product_id, record["user_idea"], brief, record["status"])
        return await self._repository.get_brief(product_id)

    async def _review_storyboard(self, product: dict[str, Any], brief: dict[str, Any]) -> list[str]:
        """Problems the reviewer found; none when there is no reviewer or the review failed."""
        if self._storyboard_reviewer is None or not brief.get("shots"):
            return []
        rules = await approved_rules(self._knowledge, KnowledgeStage.REVIEW, "brief")
        return await self._storyboard_reviewer.review(product, brief, rules.text) or []

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
        detail = await self._repository.get_detail(product_id)
        facts = product_facts(detail, current["user_idea"]) if detail else ""
        brief["warnings"] = brief_warnings(brief, facts)
        brief.setdefault("quality_problems", [])
        if brief.get("shots") != current["brief"].get("shots"):
            # only a changed storyboard is worth a new review, which takes a minute
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

    async def get_persona(self, product_id: str, media_root: Path) -> dict[str, Any]:
        """The photos the user uploaded of the person who appears in the video."""
        stored = await self._read_json(media_root, f"persona/{product_id}/persona.json")
        return stored or {"image_paths": [], "attempts": 0}

    async def persona_photos(self, product_id: str, media_root: Path) -> list[bytes]:
        store = self.media(media_root)
        persona = await self.get_persona(product_id, media_root)
        return [await store.read(path) for path in persona["image_paths"]]

    async def upload_persona(
        self, product_id: str, media_root: Path, content: bytes, add: bool = False
    ) -> dict[str, Any] | None:
        """Keep a photo of the person; with `add` it joins the photos already uploaded."""
        if await self._repository.get_detail(product_id) is None:
            return None
        store = self.media(media_root)
        previous = await self.get_persona(product_id, media_root)
        kept = previous["image_paths"] if add else []
        if not add:
            for old in previous["image_paths"]:
                await store.remove(old)
        relative = f"persona/{product_id}/photo_{len(kept)}.jpg"
        await store.write(relative, content)
        persona = {"image_paths": [*kept, relative], "attempts": previous["attempts"] + 1}
        await self._write_json(media_root, f"persona/{product_id}/persona.json", persona)
        await self._log(
            product_id, "persona", "ok", f"Person photo uploaded ({len(persona['image_paths'])})"
        )
        return persona

    async def delete_persona(self, product_id: str, media_root: Path) -> None:
        await self.media(media_root).remove_tree(f"persona/{product_id}")

    async def generate_keyframes(
        self, product_id: str, media_root: Path, shot_index: int | None = None, note: str = ""
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
        persona_images: list[bytes] | None = None
        if record["brief"].get("with_person"):
            persona_images = (await self.persona_photos(product_id, media_root))[
                : MODEL_IMAGE_LIMIT - MODEL_IMAGE_RESERVE - 1
            ]
            if not persona_images:
                raise KeyframeUnavailable(
                    "Upload the photos of the person again, or write a new brief without a person"
                )
        detail = await self._repository.get_detail(product_id)
        room = MODEL_IMAGE_LIMIT - MODEL_IMAGE_RESERVE - len(persona_images or [])
        photos = await fetch_images(_product_photo_urls(record["brief"], detail or {})[:room])
        if not photos:
            raise KeyframeUnavailable("No product photo could be downloaded")
        references = await self._shot_references(record["brief"], wanted)
        master = (
            await self.media(media_root).read(existing[0]["image_path"]) if master_ready else None
        )
        size = str(record["brief"].get("product_size") or "")
        variant = str(record["brief"].get("product_variant") or "")
        rules = await approved_rules(self._knowledge, KnowledgeStage.ORCHESTRATION, "keyframe")
        qa_rules = await approved_rules(self._knowledge, KnowledgeStage.REVIEW, "keyframe")
        rule_ids = sorted({*rules.ids, *qa_rules.ids})
        limit = asyncio.Semaphore(KEYFRAME_CONCURRENCY)
        done = {index: asyncio.Event() for index in wanted}

        async def make(index: int) -> None:
            async with limit:
                try:
                    await self._make_keyframe(
                        product_id,
                        index,
                        {
                            **shots[index],
                            "product_size": size,
                            "product_variant": variant,
                            "rules": rules.text,
                            "qa_rules": qa_rules.text,
                            "rule_ids": rule_ids,
                            "story": story_note(record["brief"], index),
                        },
                        existing.get(index),
                        media_root,
                        photos,
                        references.get(index),
                        master,
                        persona_images,
                        done.get(index - 1),
                        note,
                    )
                finally:
                    done[index].set()

        async with asyncio.TaskGroup() as group:
            for index in wanted:
                group.create_task(make(index))
        return await self._repository.list_keyframes(product_id)

    async def _shot_references(self, brief: dict[str, Any], wanted: list[int]) -> dict[int, bytes]:
        """The picture of the reference chosen for each wanted shot, when it has one."""
        chosen = brief.get("shot_references") or []
        ids = {index: chosen[index] for index in wanted if index < len(chosen) and chosen[index]}
        if not ids:
            return {}
        urls = {
            image["image_id"]: image["image_url"]
            for image in await self._repository.list_reference_images(None, None)
            if image["image_id"] in set(ids.values())
        }
        wanted_ids = [
            (index, urls[image_id]) for index, image_id in ids.items() if image_id in urls
        ]
        pictures = await asyncio.gather(*(fetch_images([url]) for _, url in wanted_ids))
        found = {index: got[0] for (index, _), got in zip(wanted_ids, pictures, strict=True) if got}
        return found

    async def _make_keyframe(
        self,
        product_id: str,
        index: int,
        shot: dict[str, Any],
        previous: dict[str, Any] | None,
        media_root: Path,
        photos: list[bytes],
        reference: bytes | None,
        master: bytes | None,
        persona: list[bytes] | None = None,
        previous_done: asyncio.Event | None = None,
        note: str = "",
    ) -> None:
        assert self._keyframer is not None
        attempts = (previous or {}).get("attempts", 0)
        before: bytes | None = None
        before_loaded = False
        record = {
            "product_id": product_id,
            "shot_index": index,
            "prompt": str(shot["keyframe_prompt"]),
            "image_path": (previous or {}).get("image_path"),
        }
        image: bytes | None = None
        problem = note  # the user's note is the first thing to fix
        lesson_sent = False  # one proposal per keyframe keeps the review queue short
        for _ in range(1 + MAX_KEYFRAME_FIXES):
            try:
                if index == 0:
                    candidate = await self._keyframer.master(
                        shot, photos, reference, problem, persona
                    )
                else:
                    candidate = await self._keyframer.follow_up(
                        shot, master or b"", photos, problem, persona, reference
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
            if not before_loaded:
                if previous_done is not None:
                    await previous_done.wait()  # the cut check needs the shot before this one
                before = await self._keyframe_before(product_id, index, media_root)
                before_loaded = True
            problem = await self._check_keyframe(shot, photos, image, master, persona, before) or ""
            if not problem:
                break
            await self._log(
                product_id, "keyframe", "retry", f"Attempt {attempts}: Gemini says {problem}", index
            )
            if self._knowledge is not None and not lesson_sent:
                lesson_sent = True
                await propose_feedback(
                    self._knowledge,
                    product_id=product_id,
                    text=problem,
                    contributor="gemini-qa",
                    authority=KnowledgeAuthority.EXTERNAL,
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
            + (f", still flagged: {problem}" if problem else "")
            + (f". Rules used: {', '.join(shot['rule_ids'])}" if shot.get("rule_ids") else ""),
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
        persona: list[bytes] | None = None,
        before: bytes | None = None,
    ) -> str | None:
        if self._checker is None:
            return None
        description = str(shot.get("description") or shot["keyframe_prompt"])
        if shot.get("product_size"):
            description = f"{description} Real size of the product: {shot['product_size']}"
        if shot.get("product_variant"):
            description = (
                f"{description} The product must be this version: {shot['product_variant']}"
            )
        if shot.get("story"):
            description = f"{description}\n\nThe whole video, for context:\n{shot['story']}"
        if shot.get("qa_rules"):
            description = f"{description}\n\nApproved rules:\n{shot['qa_rules']}"
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
        key = (clip["product_id"], clip["shot_index"])
        if key in self._collecting:
            return  # another poll is already downloading and checking this clip
        self._collecting.add(key)
        try:
            await self._collect_finished_clip(clip, media_root)
        finally:
            self._collecting.discard(key)

    async def _collect_finished_clip(self, clip: dict[str, Any], media_root: Path) -> None:
        assert self._videographer is not None
        try:
            state = await self._videographer.status(clip["job_id"], clip["job_model"])
            if state.status == "completed" and state.video_url:
                content = await self._videographer.download(state.video_url)
                relative = f"clips/{clip['product_id']}/shot_{clip['shot_index']}.mp4"
                await self.media(media_root).write(relative, content)
                problem = await self._check_clip(clip, relative, media_root)
                if problem and self._knowledge is not None:
                    await propose_feedback(
                        self._knowledge,
                        product_id=clip["product_id"],
                        text=problem,
                        contributor="gemini-qa",
                        authority=KnowledgeAuthority.EXTERNAL,
                        asset_type="brief",
                        once=True,
                    )
                update = {
                    "status": "ready",
                    "video_path": relative,
                    "error": None,
                    "qa_problem": problem or "",
                }
                await self._log(
                    clip["product_id"],
                    "clip",
                    "flagged" if problem else "ok",
                    "Clip downloaded" + (f", flagged: {problem}" if problem else ""),
                    clip["shot_index"],
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

    async def _check_clip(
        self, clip: dict[str, Any], relative: str, media_root: Path
    ) -> str | None:
        """Ask Gemini whether the clip still shows the real product; None when not checked."""
        if self._clip_checker is None:
            return None
        product_id = clip["product_id"]
        record = await self._repository.get_brief(product_id)
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        keyframe = keyframes.get(clip["shot_index"], {})
        if record is None or not keyframe.get("image_path"):
            return None
        store = self.media(media_root)
        try:
            frames = await clip_frames(store.path(relative), clip["seconds"])
        except StitchUnavailable as error:
            logger.warning("Clip frames could not be read: {}", error)
            return None
        if not frames:
            return None
        brief = record["brief"]
        shot = brief["shots"][clip["shot_index"]]
        detail = await self._repository.get_detail(product_id)
        photos = await fetch_images(_product_photo_urls(brief, detail or {})[:CLIP_CHECK_PHOTOS])
        persona_images = (
            await self.persona_photos(product_id, media_root) if brief.get("with_person") else []
        )
        description = str(shot.get("description") or shot.get("motion_prompt") or "")
        return await self._clip_checker.check(
            description,
            photos,
            await store.read(keyframe["image_path"]),
            frames,
            persona_images or None,
        )

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
                product_id,
                index,
                shots[index],
                keyframes[index],
                clips.get(index),
                media_root,
                bool(record["brief"].get("with_person")),
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
        with_person: bool,
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
            "qa_problem": "",
        }
        delivery = str(shot.get("delivery") or "narrated")
        if delivery == "talking":
            sound = (
                f"{_DELIVERY_RULE[True]} The person says in Vietnamese, in one go: "
                f'"{shot.get("voiceover") or ""}". '
                "Audio: clear spoken Vietnamese dialogue at a steady pace, no background music, no text on screen."
            )
        else:
            sound = (
                f"{_DELIVERY_RULE[False]} Audio: no sound, no dialogue, no music, "
                "no text on screen."
            )
        frame = await self.media(media_root).read(keyframe["image_path"])
        prompt = (
            f"{shot.get('motion_prompt') or 'Slow gentle camera push-in.'} "
            "Keep the product's exact shape, color and details; do not add or change objects. "
            "Energetic TikTok pace: brisk natural movement and quick camera moves, "
            "never slow motion, no long pauses. "
            f"{'' if with_person else _NO_PERSON_VIDEO}"
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
        self,
        product_id: str,
        media_root: Path,
        voice: str | None = None,
        variant: str = "",
        hook: str = "",
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
        if hook.strip():
            if segments[0].guide is not None:
                raise KeyframeUnavailable(
                    "The first shot is a talking shot: its words are fixed by its clip"
                )
            segments[0] = replace(segments[0], text=hook.strip())
        store = self.media(media_root)
        where = video_folder(product_id, variant)
        folder = store.path(where)
        folder.mkdir(parents=True, exist_ok=True)
        for extension in VOICEOVER_TYPES.values():
            await store.remove(f"{where}/voiceover.{extension}")
        planned = [reading.seconds for reading in segments]
        try:
            lengths = await make_voiceover(self._speaker, segments, folder / "voiceover.mp3", voice)
            await store.push(f"{where}/voiceover.mp3")
            heard = {
                str(index): round(spoken_seconds(n, planned_seconds, reading.guide is not None), 2)
                for index, n, planned_seconds, reading in zip(
                    approved, lengths, planned, segments, strict=True
                )
                if reading.text.strip()
            }
            held = {
                str(index): round(reading.seconds, 2)
                for index, reading in zip(approved, segments, strict=True)
            }
            await self.note_voice(
                product_id,
                media_root,
                VOICES.get(voice or "", voice or "default"),
                heard,
                variant,
                held,
            )
        except (SpeechError, StitchUnavailable) as error:
            raise KeyframeUnavailable(f"The voice-over could not be made: {error}") from error
        too_long = [
            i + 1
            for i, (n, planned_seconds) in enumerate(zip(lengths, planned, strict=True))
            if n > planned_seconds * MAX_SPEEDUP
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
        self,
        product_id: str,
        media_root: Path,
        captions: bool = False,
        stickers: bool = False,
        variant: str = "",
        hook: str = "",
    ) -> str | None:
        """Stitch the ready clips of approved shots, in story order, into one mp4.

        Captions are only burned into the picture when asked for, since the text can cover the
        product. They show the voice-over words as they are spoken; a shot whose voice-over was
        not made shows its on-screen text instead. Stickers show the price, sales and rating from
        the product data in the shot that mentions them, only when asked for.
        """
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        shots = record["brief"].get("shots") or []
        clips = {c["shot_index"]: c for c in await self.clips(product_id, media_root)}
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        parts: list[StitchClip] = []
        first_words = ""
        used: dict[int, int] = {}
        spoken_texts: list[str] = []
        where = video_folder(product_id, variant)
        made = (await self._read_json(media_root, f"{where}/voiceover.json")) or {}
        heard = made.get("speech_seconds") or {}
        held = made.get("shot_seconds") or {}
        for index, shot in enumerate(shots):
            if keyframes.get(index, {}).get("status") != "approved":
                continue
            if hook.strip() and not parts:  # a hook variant only changes the opening line
                shot = {**shot, "voiceover": hook.strip(), "on_screen_text": hook.strip()}
            clip = clips.get(index)
            if clip is None or clip["status"] != "ready":
                raise StitchUnavailable(f"The clip for shot {index + 1} is not ready yet")
            duration = min(float(shot.get("duration_seconds") or clip["seconds"]), clip["seconds"])
            if str(index) in held:  # the voice-over was cut to its words; cut the picture to match
                duration = min(duration, clip_seconds_for(float(held[str(index)])))
            caption = str(shot.get("on_screen_text") or "") if captions else ""
            local = await self.media(media_root).fetch(clip["video_path"])
            if local is None:
                raise StitchUnavailable(f"The clip file for shot {index + 1} is missing")
            cues = tuple(spoken_cues(str(shot.get("voiceover") or ""), heard.get(str(index), 0)))
            parts.append(StitchClip(local, duration, caption, cues if captions else ()))
            spoken_texts.append(f"{shot.get('voiceover') or ''} {shot.get('on_screen_text') or ''}")
            if not parts[1:]:
                first_words = str(shot.get("on_screen_text") or shot.get("voiceover") or "")
            used[index] = clip["attempts"]
        relative = f"{where}/video.mp4"
        store = self.media(media_root)
        await store.fetch_first([f"{where}/voiceover.{ext}" for ext in VOICEOVER_TYPES.values()])
        voice = find_voiceover(media_root, product_id, variant)
        shown: list[list[str]] = [[] for _ in parts]
        with tempfile.TemporaryDirectory() as scratch:
            font = caption_font()
            detail = await self._repository.get_detail(product_id) if stickers else None
            if detail and font is not None:
                lines = sticker_lines(detail)
                shown = stickers_by_shot(lines, spoken_texts)
                for number, (part, kinds) in enumerate(zip(parts, shown, strict=True)):
                    images = []
                    for kind in kinds:
                        image = Path(scratch) / f"sticker_{number}_{kind}.png"
                        render_sticker(lines[kind][0], font, image)
                        images.append(image)
                    parts[number] = replace(part, stickers=tuple(images))
            await stitch(parts, store.path(relative), voice)
        await store.push(relative)
        cover = f"{where}/cover.jpg"
        await cover_frame(store.path(relative), store.path(cover))
        await store.push(cover)
        check = None
        try:
            check = judge(
                await measure(store.path(relative), voice),
                expected_seconds=sum(shot_seconds(p.duration) for p in parts),
                hook_text=first_words,
                burned_texts=[p.caption for p in parts if p.caption and not p.cues],
                wants_audio=voice is not None,
            )
        except VideoCheckUnavailable as error:
            logger.warning("Final video check skipped: {}", error)
        if check is not None and not variant:
            await self._learn_from_check(product_id, media_root, check)
        await self._write_json(
            media_root,
            f"{where}/video.json",
            {
                "hook": hook.strip(),
                "built_at": datetime.now(UTC).isoformat(),
                "captions": captions,
                "stickers": [kind for kinds in shown for kind in kinds],
                "seconds": round(sum(shot_seconds(p.duration) for p in parts), 1),
                "clip_attempts": used,
                "check": check,
                "voice": await self._read_json(media_root, f"{where}/voiceover.json"),
            },
        )
        await self._log(
            product_id,
            "video",
            "ok",
            f"Stitched {len(parts)} clip(s), voice-over {'yes' if voice else 'no'}, "
            f"captions {'yes' if captions else 'no'}"
            + (f", hook variant {variant}" if variant else ""),
        )
        return relative

    async def _learn_from_check(
        self, product_id: str, media_root: Path, check: dict[str, Any]
    ) -> None:
        """Propose a script rule for a problem that has now shown up in two or more videos."""
        if self._knowledge is None:
            return
        found = {i["code"] for i in check["issues"] if i["code"] in LESSONS}
        for record in await self._repository.list_briefs():
            if not found:
                break
            if record["product_id"] == product_id:
                continue
            earlier = await self._read_json(media_root, f"videos/{record['product_id']}/video.json")
            seen = {i.get("code") for i in ((earlier or {}).get("check") or {}).get("issues", [])}
            for code in found & seen:
                await propose_feedback(
                    self._knowledge,
                    product_id=product_id,
                    text=LESSONS[code],
                    contributor="video-check",
                    authority=KnowledgeAuthority.EXTERNAL,
                    asset_type="brief",
                    once=True,
                )
            found -= seen

    async def video_check(self, product_id: str, media_root: Path) -> dict[str, Any] | None:
        """The automatic check made when the video was stitched, or None when there is none."""
        built = await self._read_json(media_root, f"videos/{product_id}/video.json") or {}
        return built.get("check")

    async def _write_json(self, media_root: Path, relative: str, data: dict[str, Any]) -> None:
        await self.media(media_root).write(relative, json.dumps(data, ensure_ascii=False).encode())

    async def _read_json(self, media_root: Path, relative: str) -> dict[str, Any] | None:
        try:
            return json.loads(await self.media(media_root).read(relative))
        except FileNotFoundError:
            return None

    async def note_voice(
        self,
        product_id: str,
        media_root: Path,
        voice: str,
        heard: dict[str, float] | None = None,
        variant: str = "",
        held: dict[str, float] | None = None,
    ) -> None:
        """Remember which voice read the voice-over and how long each shot's words are heard."""
        await self._write_json(
            media_root,
            f"{video_folder(product_id, variant)}/voiceover.json",
            {
                "voice": voice,
                "made_at": datetime.now(UTC).isoformat(),
                "speech_seconds": heard or {},
                "shot_seconds": held or {},
            },
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
        persona = await self.get_persona(product_id, media_root)
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
            "persona": {"photos": len(persona["image_paths"])}
            if brief.get("with_person")
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
