"""Ingest browser captures and export collected products."""

from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from openpyxl import Workbook
from openpyxl.styles import Font

from ai_content.domains.marketing.research_crawler.identity import media_source_fingerprint

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

_PIN_SIZE = re.compile(r"^/(?:\d+x\d*|originals)/")
_PINTEREST_SEARCH = "https://www.pinterest.com/search/pins/?q="


def _clean_pins(pins: list[dict[str, Any]], exclude: list[str]) -> list[dict[str, str]]:
    """Keep distinct Pinterest CDN images whose title has none of the exclude words."""
    cleaned: dict[str, dict[str, str]] = {}
    for pin in pins:
        url = str(pin.get("image_url") or "")
        parsed = urlsplit(url)
        title = str(pin.get("title") or "")
        if (parsed.hostname or "").endswith("pinimg.com") is False:
            continue
        if any(word.lower() in title.lower() for word in exclude):
            continue
        image_id = media_source_fingerprint(url)
        cleaned.setdefault(
            image_id,
            {
                "image_id": image_id,
                "image_url": parsed._replace(path=_PIN_SIZE.sub("/736x/", parsed.path, 1)).geturl(),
                "pin_url": str(pin.get("pin_url") or ""),
                "title": title,
            },
        )
    return list(cleaned.values())


class ProductCatalogService:
    def __init__(
        self, repository: ProductRepository, generator: ReferenceProfileGenerator | None = None
    ) -> None:
        self._repository = repository
        self._generator = generator

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
        profiles = {p.product_type: p for p in await self._repository.list_profiles()}
        exclude = profiles[product_type].exclude_keywords if product_type in profiles else []
        pins = _clean_pins(list(payload.get("pins") or []), exclude)
        added = await self._repository.add_reference_images(
            product_type, str(payload["query"]), pins
        )
        return {
            "stored": "reference_images",
            "received": len(payload.get("pins") or []),
            "added": added,
        }

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
        return await self._repository.list_reference_images(status, product_type)

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

    async def select(self, product_id: str) -> dict[str, Any] | None:
        """Mark a product for content; draft its reference search profile when an LLM is set."""
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
