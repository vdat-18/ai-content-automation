"""Draft one content brief per product from approved reference scenes."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Protocol

import httpx
from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

_CONCURRENCY = 2
_DOWNLOAD_TIMEOUT = 30
MAX_REFERENCES = 8
PHOTOS_SEEN = 9  # the crawl keeps at most this many photos of a product
MAX_PRODUCT_PHOTOS = PHOTOS_SEEN  # photos the image model gets, picked by the brief


class BriefGenerationError(RuntimeError):
    """The model could not produce a brief."""


class BriefUnavailable(RuntimeError):
    """The product is not ready for a brief; the message says what to do first."""


class _BamlBriefClient(Protocol):
    async def DraftContentBrief(
        self,
        product_json: str,
        user_idea: str,
        shot_count: int,
        product_images: list[BamlImage],
        references: list[baml_types.LabeledReference],
    ) -> baml_types.ContentBrief: ...


def product_facts(product: dict[str, Any]) -> dict[str, Any]:
    """Compact, grounded product facts the model may rely on."""
    price = product.get("price") or {}
    return {
        "title": product.get("title"),
        "categories": product.get("categories"),
        "price_vnd": price.get("sale"),
        "sold_count": product.get("sold_count"),
        "rating": product.get("rating"),
        "review_count": product.get("review_count"),
        "specifications": dict(list((product.get("specifications") or {}).items())[:20]),
        "variants": [v.get("variant") for v in (product.get("variants") or [])[:10]],
        "description": (product.get("description") or "")[:3_000],
    }


_DETAIL_LABELS = (
    ("setting", "Setting"),
    ("surface_and_props", "Props"),
    ("lighting", "Light"),
    ("color_palette", "Colors"),
    ("style", "Style"),
    ("camera", "Camera"),
    ("people", "People"),
    ("placement", "Product spot"),
    ("suits", "Fits shots"),
    ("motion_ideas", "Motion ideas"),
)


def _note(image: dict[str, Any]) -> str:
    """Everything the review saw in the picture, as text the brief writer can compare."""
    screening = image.get("screening") or {}
    if screening.get("description"):
        details = []
        for key, label in _DETAIL_LABELS:
            value = screening.get(key)
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            if value:
                details.append(f"{label}: {value}")
        return " ".join([str(screening["description"]), *(f"{item}." for item in details)])
    parts = [screening.get("scene_description"), screening.get("placement_note")]
    return " ".join(part for part in parts if part)


class ContentBriefWriter:
    """Download reference images and ask the BAML model for a single brief."""

    def __init__(self, client: _BamlBriefClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> ContentBriefWriter:
        registry = build_client_registry(
            name="ContentBrief",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0.4,
            max_output_tokens=12000,
        )
        return cls(b.with_options(client_registry=registry))

    async def write(
        self,
        product: dict[str, Any],
        user_idea: str,
        references: list[dict[str, Any]],
        http: httpx.AsyncClient | None = None,
        shot_count: int = 1,
    ) -> dict[str, Any]:
        """Return the brief as a dict.

        The model sees the product photos and only the text of the reference scenes. It picks one
        scene (reported as an image id) and the photos the image model will use (reported as urls).
        """
        semaphore = asyncio.Semaphore(_CONCURRENCY)
        owned = http is None
        http = http or httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)

        async def fetch(url: str) -> BamlImage | None:
            async with semaphore:
                try:
                    response = await http.get(url)
                    response.raise_for_status()
                except httpx.HTTPError as error:
                    logger.warning("Brief image download failed: {}", str(error)[:200])
                    return None
            media_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
            return BamlImage.from_base64(media_type, base64.b64encode(response.content).decode())

        urls = [url for url in (product.get("images") or [])[:PHOTOS_SEEN] if url]
        try:
            downloaded = await asyncio.gather(*(fetch(url) for url in urls))
        finally:
            if owned:
                await http.aclose()
        photos = [
            (url, photo) for url, photo in zip(urls, downloaded, strict=True) if photo is not None
        ]
        if not photos:
            raise BriefGenerationError("None of the product photos could be downloaded")
        labeled = {f"ref_{index + 1}": image["image_id"] for index, image in enumerate(references)}
        try:
            draft = await self._client.DraftContentBrief(
                json.dumps(product_facts(product), ensure_ascii=False),
                user_idea.strip(),
                shot_count,
                [photo for _, photo in photos],
                [
                    baml_types.LabeledReference(label=label, note=_note(image))
                    for label, image in zip(labeled, references, strict=True)
                ],
            )
        except BamlError as error:
            raise BriefGenerationError(str(error)) from error
        brief = draft.model_dump()
        labels = brief.pop("selected_reference_labels")
        brief["selected_reference_ids"] = [labeled[label] for label in labels if label in labeled][
            :1
        ]
        numbers = dict.fromkeys(brief.pop("product_photo_numbers"))
        chosen = [photos[number - 1][0] for number in numbers if 1 <= number <= len(photos)]
        brief["product_photo_urls"] = (chosen or [url for url, _ in photos])[:MAX_PRODUCT_PHOTOS]
        return brief
