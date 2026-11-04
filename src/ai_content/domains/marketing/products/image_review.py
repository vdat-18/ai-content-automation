"""Gemini review of crawled reference images."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Protocol

import httpx
from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

_CONCURRENCY = 2
# a complete review of a usable image has at least these
_REQUIRED_DETAIL = ("setting", "lighting", "camera", "placement")
_DOWNLOAD_TIMEOUT = 30


class _BamlReviewClient(Protocol):
    async def ReviewReferenceImage(
        self, product_type: str, image: BamlImage
    ) -> baml_types.ReferenceImageReview: ...


class ReferenceImageReviewer:
    """Download each image and ask the BAML screening model whether it is a usable reference."""

    def __init__(self, client: _BamlReviewClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> ReferenceImageReviewer:
        registry = build_client_registry(
            name="ReferenceImageReview",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
            max_output_tokens=4096,
        )
        return cls(b.with_options(client_registry=registry))

    async def review_all(
        self, images: list[dict[str, Any]], http: httpx.AsyncClient | None = None
    ) -> dict[str, dict[str, Any] | None]:
        """Return a review per image id; None when the image could not be reviewed."""
        semaphore = asyncio.Semaphore(_CONCURRENCY)
        owned = http is None
        http = http or httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)

        async def review(image: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
            async with semaphore:
                try:
                    response = await http.get(image["image_url"])
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
                    result = await self._client.ReviewReferenceImage(
                        image["product_type"],
                        BamlImage.from_base64(
                            media_type, base64.b64encode(response.content).decode("ascii")
                        ),
                    )
                except (httpx.HTTPError, BamlError) as error:
                    logger.warning("Reference image review failed: {}", str(error)[:300])
                    return image["image_id"], None
                review = result.model_dump()
                if review["usable"] and not any(review.get(key) for key in _REQUIRED_DETAIL):
                    # a reply cut off half way still parses; never let it through as a full review
                    logger.warning("Reference image review was cut short: {}", image["image_id"])
                    return image["image_id"], None
                return image["image_id"], review

        try:
            return dict(await asyncio.gather(*(review(image) for image in images)))
        finally:
            if owned:
                await http.aclose()
