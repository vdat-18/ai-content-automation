"""Ingest browser captures and export collected products."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from openpyxl import Workbook
from openpyxl.styles import Font

from .briefing import MAX_REFERENCES, BriefUnavailable, ContentBriefWriter
from .embedding import ImageEmbedder, cosine, dhash, download_images, hamming
from .identity import PIN_SIZE_DIR, media_source_fingerprint
from .image_review import ReferenceImageReviewer
from .media import MediaDownloadReport, download_product_media
from .parsing import (
    is_feed_url,
    is_product_url,
    junk_reason,
    parse_feed_payload,
    parse_product_page,
)
from .references import ProfileGenerationError, ReferenceProfile, ReferenceProfileGenerator
from .repositories import ProductRepository

_PINTEREST_SEARCH = "https://www.pinterest.com/search/pins/?q="
_SCREEN_BATCH = 200
DUPLICATE_COSINE = 0.90
DUPLICATE_HAMMING = 4
BRIEF_FIELDS = (
    "title",
    "scene",
    "product_placement",
    "selling_angle",
    "target_audience",
    "style",
    "colors",
    "shots",
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


class ProductCatalogService:
    def __init__(
        self,
        repository: ProductRepository,
        generator: ReferenceProfileGenerator | None = None,
        reviewer: ReferenceImageReviewer | None = None,
        briefer: ContentBriefWriter | None = None,
        embedder: ImageEmbedder | None = None,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._reviewer = reviewer
        self._briefer = briefer
        self._embedder = embedder

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
        pins, duplicates = await self._drop_duplicates(product_type, pins)
        added = await self._repository.add_reference_images(
            product_type, str(payload["query"]), pins
        )
        screened = await self.screen_images(_SCREEN_BATCH) if self._reviewer else None
        return {
            "stored": "reference_images",
            "received": len(payload.get("pins") or []),
            "added": added - duplicates,
            "duplicates": duplicates,
            "screened": screened,
        }

    async def _drop_duplicates(
        self, product_type: str, pins: list[dict[str, str]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Fingerprint new images and mark those that repeat a known image as duplicates.

        Duplicates are still stored (status "duplicate") so a later crawl skips them by id,
        but they never reach the vision model.
        """
        if self._embedder is None or not pins:
            return list(pins), 0
        known_ids = await self._repository.existing_image_ids([pin["image_id"] for pin in pins])
        fresh = [pin for pin in pins if pin["image_id"] not in known_ids]
        downloaded = await download_images([pin["image_url"] for pin in fresh])
        known = await self._repository.fingerprints(product_type)
        for item in known:
            item["phash_int"] = int(item["phash"], 16)
        usable = [pin for pin in fresh if pin["image_url"] in downloaded]
        vectors = await self._embedder.embed_many([downloaded[p["image_url"]] for p in usable])
        result: list[dict[str, Any]] = [pin for pin in pins if pin["image_id"] in known_ids]
        duplicates = 0
        fingerprints = {
            pin["image_id"]: (dhash(downloaded[pin["image_url"]]), vector)
            for pin, vector in zip(usable, vectors, strict=True)
        }
        for pin in fresh:
            if pin["image_id"] not in fingerprints:
                result.append(dict(pin))
                continue
            phash, vector = fingerprints[pin["image_id"]]
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
        return result, duplicates

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

    async def create_brief(self, product_id: str, user_idea: str = "") -> dict[str, Any] | None:
        """Draft one brief for a selected product from varied live reference scenes."""
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
        brief = await self._briefer.write(detail, user_idea, references)
        await self._repository.save_brief(product_id, user_idea.strip(), brief, "draft")
        return await self._repository.get_brief(product_id)

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
        await self._repository.save_brief(product_id, current["user_idea"], brief, status)
        return await self._repository.get_brief(product_id)

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
