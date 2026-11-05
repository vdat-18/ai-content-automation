"""LLM review of the stitched video, from frames sampled along it."""

from __future__ import annotations

import json
from typing import Any, Protocol

from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry
from ai_content.domains.marketing.products.briefing import product_facts
from ai_content.domains.marketing.products.keyframe_check import _image


class _BamlVideoClient(Protocol):
    async def ReviewFinalVideo(
        self,
        product_json: str,
        storyboard_json: str,
        product_photos: list[BamlImage],
        frames: list[BamlImage],
    ) -> baml_types.VideoReview: ...


class VideoReviewer:
    """Ask the BAML screening model whether the stitched video is ready to post."""

    def __init__(self, client: _BamlVideoClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> VideoReviewer:
        registry = build_client_registry(
            name="VideoReview",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
            max_output_tokens=800,
        )
        return cls(b.with_options(client_registry=registry))

    async def review(
        self,
        product: dict[str, Any],
        brief: dict[str, Any],
        photos: list[bytes],
        frames: list[bytes],
    ) -> list[str] | None:
        """Return the problems found ([] when it passes), or None when the review failed."""
        story = {key: brief.get(key) for key in ("title", "shots")}
        try:
            result = await self._client.ReviewFinalVideo(
                json.dumps(product_facts(product), ensure_ascii=False),
                json.dumps(story, ensure_ascii=False),
                [_image(photo) for photo in photos],
                [_image(frame) for frame in frames],
            )
        except BamlError as error:
            logger.warning("Video review failed: {}", str(error)[:300])
            return None
        if result.passed:
            return []
        problems = [problem.strip() for problem in result.problems if problem.strip()]
        return problems or ["The reviewer rejected the video without saying why."]
