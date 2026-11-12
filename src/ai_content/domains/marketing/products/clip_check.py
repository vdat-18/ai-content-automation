"""Gemini check that a generated clip still shows the real product and the same person."""

from __future__ import annotations

import asyncio
import base64
from typing import Protocol

from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry
from ai_content.domains.marketing.products.keyframe_check import QAProblem


class _BamlClipClient(Protocol):
    async def CheckClip(
        self,
        shot_description: str,
        product_photos: list[BamlImage],
        keyframe: BamlImage,
        characters: list[BamlImage],
        clip_frames: list[BamlImage],
    ) -> baml_types.ClipCheck: ...

_TRIES = 3
_RETRY_DELAY = 3.0


def _image(content: bytes) -> BamlImage:
    media_type = "image/png" if content[:4] == b"\x89PNG" else "image/jpeg"
    return BamlImage.from_base64(media_type, base64.b64encode(content).decode("ascii"))


class ClipChecker:
    """Ask the BAML screening model whether frames of a clip match the product and keyframe."""

    def __init__(
        self, client: _BamlClipClient, retry_delay: float = _RETRY_DELAY
    ) -> None:
        self._client = client
        self._retry_delay = retry_delay

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> ClipChecker:
        registry = build_client_registry(
            name="ClipCheck",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
        )
        return cls(b.with_options(client_registry=registry))

    async def check(
        self,
        shot_description: str,
        product_photos: list[bytes],
        keyframe: bytes,
        frames: list[bytes],
        persona: list[bytes] | None = None,
    ) -> str | None:
        """Return "" when the clip passes, the problem text when it fails, None if unchecked."""
        for attempt in range(_TRIES):
            try:
                result = await self._client.CheckClip(
                    shot_description,
                    [_image(photo) for photo in product_photos],
                    _image(keyframe),
                    [_image(photo) for photo in persona or []],
                    [_image(frame) for frame in frames],
                )
            except BamlError as error:
                logger.warning("Clip check attempt {} failed: {}", attempt + 1, str(error)[:300])
                if attempt < _TRIES - 1:
                    await asyncio.sleep(self._retry_delay)
                continue
            if result.passed:
                return ""
            return QAProblem(result.problem.strip() or "The clip does not match.", result.category)
        return None
