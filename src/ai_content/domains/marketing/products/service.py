"""Ingest browser captures and export collected products."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from io import BytesIO
from itertools import accumulate
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
from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)

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
    caption_measure,
    clip_frames,
    clip_seconds_for,
    cover_frame,
    shot_seconds,
    still_tail_seconds,
    stitch,
    video_seconds,
)
from .compliance import AI_LABEL_REMINDER, brief_warnings, package_warnings, product_facts
from .embedding import ImageEmbedder, cosine, dhash, download_images, hamming
from .hooks import HookWriter
from .identity import PIN_SIZE_DIR, media_source_fingerprint
from .image_review import ReferenceImageReviewer
from .jumpcuts import zoom_windows
from .keyframe_check import KeyframeChecker
from .keyframes import (
    KEEP_SKIN_NOTE,
    KeyframeGenerationError,
    KeyframeGenerator,
    fetch_images,
    story_note,
)
from .knowledge import approved_rules, propose_feedback
from .media import MediaDownloadReport, download_product_media
from .media_store import MediaStore, RemoteMedia
from .parsing import (
    category_from_page_url,
    is_feed_url,
    is_product_url,
    junk_reason,
    parse_feed_payload,
    parse_product_page,
)
from .posting import PostingPackageWriter
from .reference_ad import AdAnalyzer, ReferenceAdUnavailable
from .reference_picker import ReferencePickerError, ShotReferencePicker
from .references import GENERAL_TYPE, ProfileGenerationError, ReferenceProfile
from .repositories import ProductRepository
from .shortening import VoiceShortener, words_that_fit
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
from .stickers import render_stickers, sticker_lines, sticker_start, stickers_by_shot
from .storyboard_review import StoryboardReviewer
from .text_embedding import TextEmbedder, TextEmbeddingError
from .video_check import LESSONS, VideoCheckUnavailable, judge, measure
from .voice_picker import VoicePicker
from .word_timing import MISREAD_BELOW, word_starts

# filter_genai asks Pinterest to show fewer AI pictures, whatever the account setting is
_PINTEREST_SEARCH = "https://www.pinterest.com/search/pins/?filter_genai=true&q="


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
STILL_TAIL_NOTE_SECONDS = 1.0  # a clip that ends this long without motion is noted in the run log
# Few inputs keep the face accurate: with many pictures the model loses the person among them
PERSONA_PHOTOS_PER_SHOT = 3
PRODUCT_PHOTOS_PER_SHOT = 3
# The check sees more of the product than the image model, so it can catch what the
# photos sent to the model do not show
KEYFRAME_CHECK_PHOTOS = 4
# Rules that ask for clearer skin than the person has; a product for the skin must not follow them
SKIN_RETOUCH_RULES = frozenset({"product-ad-clear-skin"})
# The voice-over is added later, so the picture only has to look right: a talking shot shows
# natural subtle speaking without exaggerated mouth movements, a narrated shot keeps lips closed.
_DELIVERY_RULE = {
    True: (
        "The person speaks naturally to the camera, subtle and gentle lip movement, "
        "relaxed facial expression, mouth does not open wide, no exaggerated mouth shapes. "
        "The lips move in exact sync with the spoken Vietnamese: every syllable gets its own "
        "matching mouth shape at the moment it is said, the lips close on b, m and p sounds and "
        "round on o and u vowels, and the mouth rests the moment a pause begins."
    ),
    False: "Nobody speaks: lips stay closed or relaxed, no lip movement.",
}
_NO_PERSON_VIDEO = (
    "No person appears in the picture: no face and no body, only the product, the place and, "
    "when needed, hands. "
)
VIDEO_LENGTHS = (15, 30, 45, 60, 75, 90)
_WORK_FOLDERS = ("keyframes", "clips", "videos")  # the media made from a script
PERSONA_FOLDER = "persona"  # the photos of the people a video can follow, one folder each
PEOPLE_FILE = f"{PERSONA_FOLDER}/people.json"  # their names, photos and which one is the default
_STALE_IMAGE = "The script of this scene changed after its image was made"
_STALE_CLIP = "The script of this scene changed after it was filmed"
# Kept as the problem of an image or clip whose AI check could not run, so a person looks at it
NOT_CHECKED = "Not checked: the AI check could not run"
_TALKING_OPENING = (
    "The opening scene shows the person speaking, so its words come from the filmed clip: "
    "a hook needs a clip of its own"
)
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
    "shot_references",
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


def _changed(old: dict[str, Any], new: dict[str, Any], *fields: str) -> bool:
    """Whether any of the fields of a scene differ, ignoring line breaks and extra spaces."""
    return any(
        " ".join(str(old.get(f) or "").split()) != " ".join(str(new.get(f) or "").split())
        for f in fields
    )


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


class HookClipPending(RuntimeError):
    """The clip of a hook is still being filmed; ask again in a little while."""


_KEEP_PERSON = (
    "Keep the same person (face, hair, clothes, body proportions) and the product's exact shape, "
    "color and details in every frame; do not add, remove or change objects. "
)
_KEEP_PRODUCT = (
    "Keep the product's exact shape, color and details in every frame; do not add, remove or "
    "change objects. "
)
_NO_ARTIFACTS = (
    "One continuous take with no cuts or dissolves. No morphing, warping, flicker or ghosting, no extra, missing or fused fingers or limbs, "
    "no watermark, and no icon, symbol, logo or graphic drawn on the picture, even when the "
    "words mention a cart or a link. "
)


def _clip_prompt(shot: dict[str, Any], with_person: bool, fix: str = "") -> str:
    """What the video model is told to film for one shot.

    `fix` is what the quality check found wrong in the last version of this clip; it is asked
    to be fixed and nothing else changed.
    """
    if str(shot.get("delivery") or "narrated") == "talking":
        sound = (
            f"{_DELIVERY_RULE[True]} The person says in Vietnamese, in one go: "
            f'"{shot.get("voiceover") or ""}". '
            "Audio: clear spoken Vietnamese dialogue at a steady pace, no background music, no text on screen."
        )
    else:
        sound = (
            f"{_DELIVERY_RULE[False]} Audio: no sound, no dialogue, no music, no text on screen."
        )
    return (
        f"{shot.get('motion_prompt') or 'Slow gentle camera push-in.'} "
        f"{_KEEP_PERSON if with_person else _KEEP_PRODUCT}{_NO_ARTIFACTS}"
        "Energetic TikTok pace: brisk natural movement and quick camera moves, "
        "never slow motion, no long pauses. "
        f"{'' if with_person else _NO_PERSON_VIDEO}"
        f"{sound}"
        f"{f' Keep everything else as before and fix only this problem of the last version: {fix}' if fix else ''}"
    )



def _with_category(product: dict[str, Any]) -> dict[str, Any]:
    """The category of the page the product was collected from, else the first one of its page."""
    if product.get("category"):
        return product
    names = product.get("categories") or []
    plain = unicodedata.normalize("NFKD", str(names[0]).lower().replace("đ", "d")) if names else ""
    slug = re.sub(r"[^a-z0-9]+", "-", plain.encode("ascii", "ignore").decode()).strip("-")
    return {**product, "category": slug} if slug else product

class ProductCatalogService:
    # Every request makes its own service, so the clips being collected are kept for the process
    _collecting: set[tuple[str, int]] = set()

    def __init__(
        self,
        repository: ProductRepository,
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
        voice_picker: VoicePicker | None = None,
        voice_shortener: VoiceShortener | None = None,
        usage: AIUsageTracker | None = None,
    ) -> None:
        self._usage = usage
        self._voice_shortener = voice_shortener
        self._voice_picker = voice_picker
        self._ad_analyzer = ad_analyzer
        self._hook_writer = hook_writer
        self._repository = repository
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
        hooks = []
        for hook in saved.get("hooks") or []:
            clip = await self._read_json(media_root, f"videos/{product_id}/{hook['id']}/clip.json")
            hooks.append(
                {
                    **hook,
                    "built": await store.exists(f"videos/{product_id}/{hook['id']}/video.mp4"),
                    "filming": bool(clip and clip["status"] == "processing"),
                }
            )
        return hooks

    async def build_hook_video(
        self,
        product_id: str,
        media_root: Path,
        hook_id: str,
        voice: str | None = None,
        captions: bool = False,
        stickers: bool = False,
    ) -> str | None:
        """Make the video for one saved hook from the clips already generated.

        When the opening scene is a person speaking, the hook needs one new clip of its own: the
        first call starts filming it and raises HookClipPending until it is ready.
        """
        hook = next(
            (h for h in await self.hooks(product_id, media_root) if h["id"] == hook_id), None
        )
        if hook is None:
            return None
        opening = await self._opening_clip(product_id, media_root, hook_id, hook["text"])
        await self.create_voiceover(
            product_id,
            media_root,
            voice,
            variant=hook_id,
            hook=hook["text"],
            opening_clip=opening,
        )
        return await self.build_video(
            product_id,
            media_root,
            captions,
            stickers,
            variant=hook_id,
            hook=hook["text"],
            opening_clip=opening,
        )

    async def _opening_clip(
        self, product_id: str, media_root: Path, hook_id: str, text: str
    ) -> Path | None:
        """The clip in which the person says a hook; None when the opening is not a person speaking.

        Raises HookClipPending while that clip is being filmed.
        """
        record = await self._repository.get_brief(product_id)
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        approved = [i for i, k in sorted(keyframes.items()) if k["status"] == "approved"]
        shots = (record or {}).get("brief", {}).get("shots") or []
        if not approved or approved[0] >= len(shots) or shots[approved[0]].get("delivery") != "talking":
            return None
        if self._videographer is None:
            raise KeyframeUnavailable("Video model is not configured (AIC_VIDEO_MODEL)")
        where = video_folder(product_id, hook_id)
        store = self.media(media_root)
        state = await self._read_json(media_root, f"{where}/clip.json")
        if state is None or state["text"] != text or state["status"] == "failed":
            frame = await store.read(keyframes[approved[0]]["image_path"])
            prompt = _clip_prompt(
                {**shots[approved[0]], "voiceover": text}, bool(record["brief"].get("with_person"))
            )
            try:
                job_id, job_model = await self._videographer.submit(prompt, frame, CLIP_SECONDS)
            except ClipGenerationError as error:
                raise KeyframeUnavailable(f"The opening clip could not be started: {error}") from error
            await self._count_call(product_id, "clip", "video", self._videographer)
            state = {"status": "processing", "job_id": job_id, "job_model": job_model, "text": text}
            await self._write_json(media_root, f"{where}/clip.json", state)
            await self._log(product_id, "clip", "started", f"Opening clip of {hook_id} started")
        if state["status"] == "processing":
            try:
                job = await self._videographer.status(state["job_id"], state["job_model"])
            except ClipGenerationError as error:
                logger.warning("Opening clip of {} could not be checked yet: {}", hook_id, error)
                raise HookClipPending(hook_id) from error
            if job.status == "failed":
                await self._write_json(media_root, f"{where}/clip.json", {**state, "status": "failed"})
                raise KeyframeUnavailable(
                    f"The opening clip failed: {job.error or 'the video job failed'}"
                )
            if job.status != "completed" or not job.video_url:
                raise HookClipPending(hook_id)
            await store.write(f"{where}/shot_0.mp4", await self._videographer.download(job.video_url))
            await self._write_json(media_root, f"{where}/clip.json", {**state, "status": "ready"})
        found = await store.fetch(f"{where}/shot_0.mp4")
        if found is None:
            raise KeyframeUnavailable("The opening clip file is missing; make the hook video again")
        return found

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
            if not items:
                logger.warning("A product feed answered with no product we can read: {}", url[:120])
            category = category_from_page_url(str(payload.get("page_url") or ""))
            for item in items if category else []:
                item["category"] = category
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
        return {
            "stored": "reference_images",
            "received": len(payload.get("pins") or []),
            "added": added - duplicates,
            "duplicates": duplicates,
            "check_failed": check_failed,
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

    async def _scene_pool(self) -> list[dict[str, Any]]:
        """Every live reference, whatever it was crawled for: all products draw from one pool."""
        return await self.reference_images("live", None)

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
        persona_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Draft one brief for a selected product from varied live reference scenes.

        Every shot becomes one 15 second clip, so the video length sets the number of shots.
        Every video follows one person of the library (persona_id), so there must be photos.
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
        live = await self._scene_pool()
        if not live:
            raise BriefUnavailable("No usable reference image yet; crawl Pinterest first")
        if not person_photos:
            raise BriefUnavailable("Upload the photo of the person first: every video shows them")
        shot_count = max(1, round(video_seconds / shot_seconds(CLIP_SECONDS)))
        rules = await approved_rules(self._knowledge, KnowledgeStage.PREPARATION, "brief")
        facts = product_facts(detail, user_idea)
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
            warnings = brief_warnings(brief, facts) if count_ok else []
            if count_ok and not problems and not warnings:
                break
            wanted = [] if count_ok else [f"Write exactly {shot_count} shots."]
            fixes = "\n\nRewrite the storyboard and fix these problems:\n- " + "\n- ".join(
                wanted + problems + warnings
            )
        if not count_ok:
            raise BriefGenerationError(
                f"The model wrote {len(brief['shots'])} shots instead of {shot_count}; try again"
            )
        brief["quality_problems"] = problems
        brief["warnings"] = warnings
        brief["shot_references"] = await self._pick_shot_references(
            product_id, detail, brief, live
        )
        brief["selected_reference_ids"] = list(
            dict.fromkeys(item for item in brief["shot_references"] if item)
        )
        brief["with_person"] = True
        brief["persona_id"] = persona_id  # later steps keep using this person, whatever the default
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

    async def _reference_vectors(self, live: list[dict[str, Any]]) -> dict[str, list[float]]:
        """The embedding of every live reference description; new ones are embedded and kept."""
        assert self._text_embedder is not None
        model = self._text_embedder.model
        stored = await self._repository.text_embeddings()
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
        stored = await self._repository.fingerprints()
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
            vectors = await self._reference_vectors(live)
            queries = await self._text_embedder.embed(
                [f"{shot.get('role', '')}. {shot.get('keyframe_prompt', '')}" for shot in shots]
            )
        except TextEmbeddingError as error:
            await self._log(product_id, "references", "error", str(error))
            return none
        pool = [image for image in live if image["image_id"] in vectors]
        if not pool:
            # A picture only counts once the review has described it, so say why nothing matched
            await self._log(
                product_id,
                "references",
                "warning",
                f"None of the {len(live)} live reference(s) has a description yet: "
                "shots have no reference",
            )
            return none
        looks = await self._product_look(product, brief, {i["image_id"] for i in pool})
        picker = self._reference_picker
        failures: list[str] = []

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
            try:
                return await picker.choose(
                    product,
                    shot,
                    [
                        {
                            "image_id": i["image_id"],
                            "note": reference_note(i),
                            "url": i["image_url"],
                        }
                        for i in closest
                    ],
                )
            except ReferencePickerError as error:
                failures.append(str(error))
                return None

        picked = await asyncio.gather(*(pick(s, q) for s, q in zip(shots, queries, strict=True)))
        seen: set[str] = set()
        result: list[str | None] = []
        for image_id in picked:  # the same picture is not used twice
            result.append(image_id if image_id and image_id not in seen else None)
            if image_id:
                seen.add(image_id)
        matched = f"Matched references to {sum(1 for item in result if item)} of {len(shots)} shot(s)"
        if failures:
            await self._log(
                product_id,
                "references",
                "error",
                f"{matched}; the model could not choose for {len(failures)} shot(s): {failures[0]}",
            )
        else:
            await self._log(
                product_id,
                "references",
                "ok",
                f"{matched} from {len(pool)} described reference(s)",
            )
        return result

    async def match_references(self, product_id: str) -> dict[str, Any] | None:
        """Choose the reference of each shot again for the stored storyboard."""
        record = await self._repository.get_brief(product_id)
        detail = await self._repository.get_detail(product_id)
        product_type = (await self._repository.selections()).get(product_id)
        if record is None or detail is None or not product_type:
            return None
        brief = dict(record["brief"])
        brief["shot_references"] = await self._pick_shot_references(
            product_id, detail, brief, await self._scene_pool()
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

    async def _count_call(
        self,
        product_id: str,
        operation: str,
        backend: str,
        client: object,
        *,
        count: int = 1,
        output_bytes: int | None = None,
        failure: str = "",
    ) -> None:
        """Write paid calls to the usage ledger; it must never break the step it counts."""
        if self._usage is None:
            return
        try:
            event = await self._usage.start(
                AIUsageStart(
                    workstream="product_ad",
                    operation=operation,
                    backend=backend,
                    model=str(getattr(client, "model", "unknown")),
                    run_id=product_id,
                )
            )
            if failure:
                await self._usage.fail(
                    event, AIUsageFailure(error_code=failure[:80], request_count=count)
                )
            else:
                await self._usage.succeed(
                    event,
                    AIUsageCompletion(
                        request_count=count, output_count=count, output_bytes=output_bytes
                    ),
                )
        except Exception as error:  # noqa: BLE001
            logger.warning("Could not write the usage of {}: {}", operation, error)

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

    async def save_run(self, product_id: str, status: str, message: str = "") -> None:
        await self._repository.save_run(product_id, status, message)

    async def get_run(self, product_id: str) -> dict[str, str] | None:
        return await self._repository.get_run(product_id)

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
        if "shot_references" in changes:
            brief["selected_reference_ids"] = list(
                dict.fromkeys(item for item in brief["shot_references"] if item)
            )
        detail = await self._repository.get_detail(product_id)
        facts = product_facts(detail, current["user_idea"]) if detail else ""
        brief["warnings"] = brief_warnings(brief, facts)
        brief.setdefault("quality_problems", [])
        if brief.get("shots") != current["brief"].get("shots"):
            # only a changed storyboard is worth a new review, which takes a minute
            await self._flag_changed_scenes(
                product_id, current["brief"].get("shots") or [], brief.get("shots") or []
            )
            brief["quality_problems"] = (
                await self._review_storyboard(detail, brief) if detail else []
            )
        await self._repository.save_brief(product_id, current["user_idea"], brief, status)
        return await self._repository.get_brief(product_id)

    async def _flag_changed_scenes(
        self, product_id: str, before: list[dict[str, Any]], after: list[dict[str, Any]]
    ) -> None:
        """Mark the image or clip of a scene whose script changed after it was made.

        The image needs a new approval and the clip a look, so nothing made from the old script
        goes into the video unnoticed.
        """
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        clips = {c["shot_index"]: c for c in await self._repository.list_clips(product_id)}

        for index, (old, new) in enumerate(zip(before, after, strict=False)):
            keyframe = keyframes.get(index)
            if (
                keyframe
                and keyframe.get("image_path")
                and _changed(old, new, "keyframe_prompt", "description")
            ):
                status = "ready" if keyframe["status"] == "approved" else keyframe["status"]
                await self._repository.save_keyframe(
                    {**keyframe, "status": status, "qa_problem": _STALE_IMAGE}
                )
            clip = clips.get(index)
            says_words = new.get("delivery") == "talking" and _changed(old, new, "voiceover")
            if clip and clip["status"] == "ready" and (_changed(old, new, "motion_prompt") or says_words):
                await self._repository.save_clip({**clip, "qa_problem": _STALE_CLIP})

    async def list_keyframes(self, product_id: str) -> list[dict[str, Any]]:
        return await self._repository.list_keyframes(product_id)

    async def set_keyframe_status(self, product_id: str, shot_index: int, status: str) -> bool:
        if status not in KEYFRAME_REVIEW_STATUSES:
            raise ValueError(f"Keyframe status must be one of {sorted(KEYFRAME_REVIEW_STATUSES)}")
        changed = await self._repository.set_keyframe_status(product_id, shot_index, status)
        if changed:
            await self._log(product_id, "keyframe", status, f"Marked {status}", shot_index)
        return changed

    async def _people(self, media_root: Path) -> dict[str, Any]:
        return await self._read_json(media_root, PEOPLE_FILE) or {"default": None, "people": []}

    async def list_personas(self, media_root: Path) -> list[dict[str, Any]]:
        """The people a video can follow, with the default one marked."""
        data = await self._people(media_root)
        return [
            {
                "id": person["id"],
                "name": person["name"],
                "photos": len(person["image_paths"]),
                "attempts": person["attempts"],
                "default": person["id"] == data["default"],
            }
            for person in data["people"]
        ]

    async def get_persona(
        self, media_root: Path, persona_id: str | None = None
    ) -> dict[str, Any] | None:
        """One person of the library: the one asked for, else the default."""
        data = await self._people(media_root)
        wanted = persona_id or data["default"]
        return next((person for person in data["people"] if person["id"] == wanted), None)

    async def persona_photos(self, media_root: Path, persona_id: str | None = None) -> list[bytes]:
        persona = await self.get_persona(media_root, persona_id)
        store = self.media(media_root)
        return [await store.read(path) for path in persona["image_paths"]] if persona else []

    async def brief_persona(
        self, media_root: Path, persona_id: str | None = None
    ) -> tuple[str | None, list[bytes]]:
        """The id and photos of the person a new video follows (the default when none is named)."""
        persona = await self.get_persona(media_root, persona_id)
        if persona is None:
            return None, []
        return persona["id"], await self.persona_photos(media_root, persona["id"])

    async def create_persona(self, media_root: Path, name: str) -> dict[str, Any]:
        """Add a person to the library; the first one becomes the default."""
        data = await self._people(media_root)
        person = {"id": uuid.uuid4().hex[:8], "name": name.strip(), "image_paths": [], "attempts": 0}
        data["people"].append(person)
        data["default"] = data["default"] or person["id"]
        await self._write_json(media_root, PEOPLE_FILE, data)
        return person

    async def upload_persona(
        self, media_root: Path, persona_id: str, content: bytes, add: bool = False
    ) -> dict[str, Any] | None:
        """Keep a photo of a person; with `add` it joins the photos already uploaded."""
        data = await self._people(media_root)
        person = next((p for p in data["people"] if p["id"] == persona_id), None)
        if person is None:
            return None
        store = self.media(media_root)
        if not add:
            for old in person["image_paths"]:
                await store.remove(old)
            person["image_paths"] = []
        relative = f"{PERSONA_FOLDER}/{persona_id}/photo_{person['attempts']}.jpg"
        await store.write(relative, content)
        person["image_paths"].append(relative)
        person["attempts"] += 1
        await self._write_json(media_root, PEOPLE_FILE, data)
        return person

    async def set_default_persona(self, media_root: Path, persona_id: str) -> bool:
        data = await self._people(media_root)
        if all(person["id"] != persona_id for person in data["people"]):
            return False
        data["default"] = persona_id
        await self._write_json(media_root, PEOPLE_FILE, data)
        return True

    async def delete_persona(self, media_root: Path, persona_id: str) -> bool:
        """Remove a person; the default moves to the next one. Videos that followed them lose them."""
        data = await self._people(media_root)
        remaining = [person for person in data["people"] if person["id"] != persona_id]
        if len(remaining) == len(data["people"]):
            return False
        await self.media(media_root).remove_tree(f"{PERSONA_FOLDER}/{persona_id}")
        data["people"] = remaining
        if data["default"] == persona_id:
            data["default"] = remaining[0]["id"] if remaining else None
        await self._write_json(media_root, PEOPLE_FILE, data)
        return True

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
            persona_images = (await self.persona_photos(media_root, record["brief"].get("persona_id")))[
                :PERSONA_PHOTOS_PER_SHOT
            ]
            if not persona_images:
                raise KeyframeUnavailable(
                    "Upload the photos of the person again, or write a new brief without a person"
                )
        detail = await self._repository.get_detail(product_id)
        check_photos = await fetch_images(
            _product_photo_urls(record["brief"], detail or {})[:KEYFRAME_CHECK_PHOTOS]
        )
        if not check_photos:
            raise KeyframeUnavailable("No product photo could be downloaded")
        photos = check_photos[:PRODUCT_PHOTOS_PER_SHOT]
        references = await self._shot_references(record["brief"], wanted)
        master = (
            await self.media(media_root).read(existing[0]["image_path"]) if master_ready else None
        )
        size = str(record["brief"].get("product_size") or "")
        variant = str(record["brief"].get("product_variant") or "")
        sensitive = bool(record["brief"].get("skin_sensitive"))
        skip = SKIN_RETOUCH_RULES if sensitive else frozenset()
        rules = await approved_rules(
            self._knowledge, KnowledgeStage.ORCHESTRATION, "keyframe", skip
        )
        qa_rules = await approved_rules(self._knowledge, KnowledgeStage.REVIEW, "keyframe", skip)
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
                            "retouch": not sensitive,
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
                        check_photos,
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
        check_photos: list[bytes] | None = None,
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
        last_category = ""
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
                await self._count_call(
                    product_id, "keyframe", "image", self._keyframer, failure=str(error)
                )
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
            await self._count_call(
                product_id, "keyframe", "image", self._keyframer, output_bytes=len(candidate)
            )
            if not before_loaded:
                if previous_done is not None:
                    await previous_done.wait()  # the cut check needs the shot before this one
                before = await self._keyframe_before(product_id, index, media_root)
                before_loaded = True
            problem = (
                await self._check_keyframe(
                    shot, check_photos or photos, image, master, persona, before
                )
                or ""
            )
            if not problem or problem == NOT_CHECKED:
                break
            await self._log(
                product_id, "keyframe", "retry", f"Attempt {attempts}: Gemini says {problem}", index
            )
            category = getattr(problem, "category", "other")
            # What is wrong with one person's face says nothing about other videos
            if self._knowledge is not None and not lesson_sent and category != "face":
                lesson_sent = True
                await propose_feedback(
                    self._knowledge,
                    product_id=product_id,
                    text=problem,
                    contributor="gemini-qa",
                    authority=KnowledgeAuthority.EXTERNAL,
                )
            if category == last_category != "other":
                break  # the same kind of problem twice: a third image would not fix it
            last_category = category
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
                "qa_problem": str(problem),
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
        if shot.get("retouch") is False:
            description = f"{description}\n\n{KEEP_SKIN_NOTE}"
        problem = await self._checker.check(description, photos, image, master, persona, before)
        return NOT_CHECKED if problem is None else problem

    async def recheck_keyframe(
        self, product_id: str, shot_index: int, media_root: Path
    ) -> dict[str, Any] | None:
        """Run the AI check again on an image that is made; no new image is paid for."""
        record = await self._repository.get_brief(product_id)
        keyframes = {k["shot_index"]: k for k in await self._repository.list_keyframes(product_id)}
        keyframe = keyframes.get(shot_index)
        if record is None or keyframe is None or not keyframe.get("image_path"):
            return None
        brief = record["brief"]
        store = self.media(media_root)
        persona = (
            (await self.persona_photos(media_root, brief.get("persona_id")))[:PERSONA_PHOTOS_PER_SHOT]
            if brief.get("with_person")
            else []
        )
        master_path = keyframes.get(0, {}).get("image_path")
        sensitive = bool(brief.get("skin_sensitive"))
        qa_rules = await approved_rules(
            self._knowledge,
            KnowledgeStage.REVIEW,
            "keyframe",
            SKIN_RETOUCH_RULES if sensitive else frozenset(),
        )
        shot = {
            **brief["shots"][shot_index],
            "product_size": brief.get("product_size"),
            "product_variant": brief.get("product_variant"),
            "retouch": not sensitive,
            "qa_rules": qa_rules.text,
            "story": story_note(brief, shot_index),
        }
        photos = await fetch_images(
            _product_photo_urls(brief, await self._repository.get_detail(product_id) or {})[
                :KEYFRAME_CHECK_PHOTOS
            ]
        )
        problem = (
            await self._check_keyframe(
                shot,
                photos,
                await store.read(keyframe["image_path"]),
                await store.read(master_path) if shot_index and master_path else None,
                persona or None,
                await self._keyframe_before(product_id, shot_index, media_root),
            )
            or ""
        )
        checked = {**keyframe, "qa_problem": str(problem)}
        await self._repository.save_keyframe(checked)
        await self._log(
            product_id,
            "keyframe",
            "flagged" if problem else "ok",
            "Checked again" + (f", flagged: {problem}" if problem else ""),
            shot_index,
        )
        return checked

    async def recheck_clip(
        self, product_id: str, shot_index: int, media_root: Path
    ) -> dict[str, Any] | None:
        """Run the AI check again on a clip that is made; no new clip is paid for."""
        clip = next(
            (
                c
                for c in await self._repository.list_clips(product_id)
                if c["shot_index"] == shot_index and c["status"] == "ready"
            ),
            None,
        )
        if clip is None:
            return None
        problem = await self._check_clip(clip, clip["video_path"], media_root) or ""
        checked = {**clip, "qa_problem": str(problem)}
        await self._repository.save_clip(checked)
        await self._log(
            product_id,
            "clip",
            "flagged" if problem else "ok",
            "Checked again" + (f", flagged: {problem}" if problem else ""),
            shot_index,
        )
        return checked

    async def clips(self, product_id: str, media_root: Path) -> list[dict[str, Any]]:
        """List clips, first collecting the ones whose video job has finished."""
        clips = await self._repository.list_clips(product_id)
        if self._videographer is None:
            return clips
        for clip in clips:
            if clip["status"] == "processing":
                await self._collect_clip(clip, media_root)
        return await self._repository.list_clips(product_id)

    async def accept_clip(self, product_id: str, shot_index: int) -> bool:
        """Keep a flagged clip as it is: a person looked at it and accepts it."""
        clip = next(
            (
                c
                for c in await self._repository.list_clips(product_id)
                if c["shot_index"] == shot_index and c["status"] == "ready"
            ),
            None,
        )
        if clip is None:
            return False
        await self._repository.save_clip({**clip, "qa_problem": ""})
        await self._log(
            product_id,
            "clip",
            "accepted",
            f"Accepted as it is: {clip['qa_problem'] or 'no problem was flagged'}",
            shot_index,
        )
        return True

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
                face = getattr(problem, "category", "") == "face"
                if problem and problem != NOT_CHECKED and not face and self._knowledge is not None:
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
                    "qa_problem": str(problem or ""),
                }
                real = await video_seconds(self.media(media_root).path(relative))
                if 0 < real < clip["seconds"] - 0.3:  # the model gave less than asked for
                    update["seconds"] = int(real)
                    await self._log(
                        clip["product_id"],
                        "clip",
                        "ok",
                        f"The clip is {real:.1f} s long, not the {clip['seconds']} s asked for",
                        clip["shot_index"],
                    )
                await self._log(
                    clip["product_id"],
                    "clip",
                    "flagged" if problem else "ok",
                    "Clip downloaded" + (f", flagged: {problem}" if problem else ""),
                    clip["shot_index"],
                )
                still = await still_tail_seconds(self.media(media_root).path(relative))
                if still >= STILL_TAIL_NOTE_SECONDS:
                    await self._log(
                        clip["product_id"],
                        "clip",
                        "ok",
                        f"The last {still:.1f} s of this clip hardly move; "
                        "the fixed trim only removes a fraction of a second",
                        clip["shot_index"],
                    )
            elif state.status == "failed":
                update = {"status": "failed", "error": state.error or "The video job failed"}
                await self._log(
                    clip["product_id"], "clip", "error", update["error"], clip["shot_index"]
                )
            else:
                return
        except ClipGenerationError as error:
            logger.warning("Clip of shot {} could not be collected yet: {}", clip["shot_index"], error)
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
            await self.persona_photos(media_root, brief.get("persona_id"))
            if brief.get("with_person")
            else []
        )
        description = str(shot.get("description") or shot.get("motion_prompt") or "")
        if brief.get("skin_sensitive"):
            description = f"{description}\n\n{KEEP_SKIN_NOTE}"
        problem = await self._clip_checker.check(
            description,
            photos,
            await store.read(keyframe["image_path"]),
            frames,
            persona_images or None,
        )
        return NOT_CHECKED if problem is None else problem

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
        frame = await self.media(media_root).read(keyframe["image_path"])
        last_problem = str((previous or {}).get("qa_problem") or "")
        found = last_problem not in (NOT_CHECKED, _STALE_CLIP)
        prompt = _clip_prompt(shot, with_person, last_problem if found else "")
        try:
            job_id, job_model = await self._videographer.submit(prompt, frame, seconds)
        except ClipGenerationError as error:
            await self._repository.save_clip({**clip, "status": "failed", "error": str(error)})
            await self._log(product_id, "clip", "error", str(error), index)
            await self._count_call(
                product_id, "clip", "video", self._videographer, failure=str(error)
            )
            return
        await self._count_call(product_id, "clip", "video", self._videographer)
        await self.media(media_root).write(
            f"clips/{product_id}/shot_{index}.prompt.txt", prompt.encode()
        )  # what the model was told, to see why a clip came out as it did
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
        opening_clip: Path | None = None,
    ) -> dict[str, Any] | None:
        """Read each approved shot's voice-over so its words start with the shot."""
        record = await self._repository.get_brief(product_id)
        if record is None:
            return None
        if self._speaker is None:
            raise KeyframeUnavailable("Text-to-speech is not configured (AIC_TTS_MODEL)")
        if voice and voice not in VOICES:
            raise KeyframeUnavailable(f"Unknown voice {voice}")
        voice_reason = ""
        if not voice and self._voice_picker is not None:
            brief = record["brief"]
            photos = (await self.persona_photos(media_root, brief.get("persona_id")))[:2]
            choice = await self._voice_picker.pick(brief, photos if brief.get("with_person") else [])
            if choice is not None:
                voice, voice_reason = choice.voice, choice.reason
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
            if segments[0].guide is not None and opening_clip is None:
                raise KeyframeUnavailable(_TALKING_OPENING)
            segments[0] = replace(
                segments[0], text=hook.strip(), guide=opening_clip or segments[0].guide
            )
        store = self.media(media_root)
        where = video_folder(product_id, variant)
        folder = store.path(where)
        folder.mkdir(parents=True, exist_ok=True)
        for extension in VOICEOVER_TYPES.values():
            await store.remove(f"{where}/voiceover.{extension}")
        planned = [reading.seconds for reading in segments]
        original = list(segments)

        async def read_all() -> list[float]:
            read = await make_voiceover(
                self._speaker,
                segments,
                folder / "voiceover.mp3",
                voice,
                partial(word_starts, model_dir=media_root.parent / "whisper"),
            )
            await self._count_call(
                product_id,
                "voiceover",
                "tts",
                self._speaker,
                count=sum(1 for reading in segments if reading.text.strip()),
            )
            return read

        try:
            lengths = await read_all()
            shortened = await self._shorten_long_lines(
                record, segments, lengths, planned, hook.strip() != ""
            )
            if shortened:
                segments[:] = [
                    replace(r, text=shortened.get(i, r.text)) for i, r in enumerate(original)
                ]
                await self._save_voiceover_lines(
                    product_id, record, {approved[i]: text for i, text in shortened.items()}
                )
                lengths = await read_all()
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
            words = {
                str(index): [round(start, 2) for start in reading.starts]
                for index, reading in zip(approved, segments, strict=True)
                if reading.starts
            }
            shares = {
                str(index): round(reading.heard, 2)
                for index, reading in zip(approved, segments, strict=True)
                if reading.heard is not None
            }
            await self.note_voice(
                product_id,
                media_root,
                VOICES.get(voice or "", voice or "default"),
                heard,
                variant,
                held,
                voice or "",
                words,
                shares,
            )
        except (SpeechError, StitchUnavailable) as error:
            raise KeyframeUnavailable(f"The voice-over could not be made: {error}") from error
        too_long = [
            i + 1
            for i, (n, planned_seconds) in enumerate(zip(lengths, planned, strict=True))
            if n > planned_seconds * MAX_SPEEDUP
        ]
        misread = [
            i + 1
            for i, reading in enumerate(segments)
            if reading.heard is not None and reading.heard < MISREAD_BELOW
        ]
        await self._log(
            product_id,
            "voiceover",
            "warning" if too_long or misread else "ok",
            f"Read in voice {voice or 'default'}; shots {[round(n, 1) for n in lengths]} s"
            + (f"; chosen because: {voice_reason}" if voice_reason else "")
            + (f"; shortened and read again: {[n + 1 for n in shortened]}" if shortened else "")
            + (f"; too long: {too_long}" if too_long else "")
            + (f"; the voice does not say the script in shots {misread}" if misread else ""),
        )
        return {
            "voiceover": "mp3",
            "voice": voice or "",
            "voice_reason": voice_reason,
            "seconds": [round(n, 1) for n in lengths],
            "too_long_shots": too_long,
            "misread_shots": misread,
        }

    async def _shorten_long_lines(
        self,
        record: dict[str, Any],
        segments: list[Reading],
        lengths: list[float],
        planned: list[float],
        hook_opens: bool,
    ) -> dict[int, str]:
        """New text for each shot whose reading cannot be sped up enough to end inside its shot.

        A talking shot that follows the speech of its clip and an opening line replaced by a hook
        keep their text. Keyed by the position of the shot in `segments`.
        """
        if self._voice_shortener is None:
            return {}
        detail = await self._repository.get_detail(record["product_id"]) or {}
        rules = await approved_rules(self._knowledge, KnowledgeStage.PREPARATION, "brief")
        found: dict[int, str] = {}
        for i, (reading, length, seconds) in enumerate(zip(segments, lengths, planned, strict=True)):
            if (
                length <= seconds * MAX_SPEEDUP
                or reading.guide is not None
                or not reading.text.strip()
                or (i == 0 and hook_opens)
            ):
                continue
            shorter = await self._voice_shortener.shorten(
                detail, reading.text, words_that_fit(reading.text, length, seconds), rules.text
            )
            if shorter is not None:
                found[i] = shorter
        return found

    async def _save_voiceover_lines(
        self, product_id: str, record: dict[str, Any], lines: dict[int, str]
    ) -> None:
        """Keep the shortened lines in the brief, so the captions and the checks use them too."""
        brief = record["brief"]
        for index, text in lines.items():
            brief["shots"][index]["voiceover"] = text
        await self._repository.save_brief(product_id, record["user_idea"], brief, record["status"])

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
        opening_clip: Path | None = None,
        music: bool = True,
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
        scripts: list[tuple[int, str]] = []  # per part: its shot number and what the voice says
        where = video_folder(product_id, variant)
        made = (await self._read_json(media_root, f"{where}/voiceover.json")) or {}
        heard = made.get("speech_seconds") or {}
        held = made.get("shot_seconds") or {}
        word_times = made.get("word_starts") or {}
        caption_width = caption_measure(caption_font())
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
            local = (
                opening_clip
                if opening_clip is not None and not parts
                else await self.media(media_root).fetch(clip["video_path"])
            )
            if local is None:
                raise StitchUnavailable(f"The clip file for shot {index + 1} is missing")
            cues = tuple(
                spoken_cues(
                    str(shot.get("voiceover") or ""),
                    heard.get(str(index), 0),
                    word_times.get(str(index)) or (),
                    caption_width,
                )
            )
            closer = (
                zoom_windows(
                    str(shot.get("voiceover") or "").split(),
                    word_times.get(str(index)) or (),
                    shot_seconds(duration),
                )
                if shot.get("delivery") == "talking"
                else ()
            )
            parts.append(
                StitchClip(local, duration, caption, cues if captions else (), zoom=closer)
            )
            spoken_texts.append(f"{shot.get('voiceover') or ''} {shot.get('on_screen_text') or ''}")
            scripts.append((index, str(shot.get("voiceover") or "")))
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
                    if kinds:
                        image = Path(scratch) / f"stickers_{number}.png"
                        render_stickers([(kind, lines[kind]) for kind in kinds], font, image)
                        images.append(image)
                    shot_number, script = scripts[number]
                    at = sticker_start(kinds, lines, script, word_times.get(str(shot_number), ()))
                    parts[number] = replace(
                        part, stickers=tuple(images), sticker_at=0.5 if at is None else at
                    )
            await stitch(parts, store.path(relative), voice, music=music)
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
                shot_starts=list(
                    accumulate(shot_seconds(p.duration) for p in parts[:-1])
                ),
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
                "music": music,
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
        voice_id: str = "",
        words: dict[str, list[float]] | None = None,
        heard_share: dict[str, float] | None = None,
    ) -> None:
        """Remember which voice read the voice-over, how long each shot's words are heard and,
        when measured, when each word starts."""
        await self._write_json(
            media_root,
            f"{video_folder(product_id, variant)}/voiceover.json",
            {
                "voice": voice,
                "voice_id": voice_id,
                "made_at": datetime.now(UTC).isoformat(),
                "speech_seconds": heard or {},
                "shot_seconds": held or {},
                "word_starts": words or {},
                "heard_share": heard_share or {},
            },
        )

    async def last_voice(self, product_id: str, media_root: Path) -> str:
        """The id of the voice that read the current voice-over, or "" when there is none."""
        made = await self._read_json(media_root, f"{video_folder(product_id)}/voiceover.json")
        return str((made or {}).get("voice_id") or "")

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
        persona = await self.get_persona(media_root, brief.get("persona_id"))
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
            "persona": {"photos": len(persona["image_paths"]) if persona else 0}
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
            for folder in _WORK_FOLDERS:
                await store.remove_tree(f"{folder}/{product_id}")
        return deleted

    async def start_over(self, product_id: str, media_root: Path) -> bool:
        """Throw away the script, images, clips and video of a product; it and its person stay."""
        if await self._repository.get_brief(product_id) is None:
            return False
        await self._repository.clear_work(product_id)
        store = self.media(media_root)
        for folder in _WORK_FOLDERS:
            await store.remove_tree(f"{folder}/{product_id}")
        await self._log(product_id, "brief", "reset", "Started over: the script and all made files were removed")
        return True

    async def set_image_status(self, image_id: str, status: str) -> bool:
        return await self._repository.set_image_status(image_id, status)

    async def queue(self, limit: int) -> list[str]:
        return await self._repository.queue(limit)

    async def details(self, include_junk: bool = False) -> list[dict[str, Any]]:
        products = [_with_category(p) for p in await self._repository.list_details()]
        return products if include_junk else [p for p in products if junk_reason(p) is None]

    async def download_media(self, media_root: Path) -> MediaDownloadReport:
        return await download_product_media(await self.details(), media_root)

    async def listing(self) -> list[dict[str, Any]]:
        return await self._repository.list_listing()

    async def detail(self, product_id: str) -> dict[str, Any] | None:
        return await self._repository.get_detail(product_id)

    async def select(self, product_id: str) -> bool:
        """Mark a product for content. Every product draws on the one shared reference pool."""
        if await self._repository.get_detail(product_id) is None:
            return False
        await self._repository.select_product(product_id, GENERAL_TYPE)
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
