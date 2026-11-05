"""Gemini check that a generated keyframe still shows the real product and the shared scene."""

from __future__ import annotations

import base64
from typing import Protocol

from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry


class _BamlCheckClient(Protocol):
    async def CheckKeyframe(
        self,
        shot_description: str,
        product_photos: list[BamlImage],
        master_keyframe: BamlImage | None,
        keyframe: BamlImage,
        character: BamlImage | None,
        previous_keyframe: BamlImage | None,
    ) -> baml_types.KeyframeCheck: ...


def _image(content: bytes) -> BamlImage:
    media_type = "image/png" if content[:4] == b"\x89PNG" else "image/jpeg"
    return BamlImage.from_base64(media_type, base64.b64encode(content).decode("ascii"))


class KeyframeChecker:
    """Ask the BAML screening model whether a keyframe matches the product photos."""

    def __init__(self, client: _BamlCheckClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> KeyframeChecker:
        registry = build_client_registry(
            name="KeyframeCheck",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
            max_output_tokens=4000,
        )
        return cls(b.with_options(client_registry=registry))

    async def check(
        self,
        shot_description: str,
        product_photos: list[bytes],
        keyframe: bytes,
        master: bytes | None = None,
        persona: bytes | None = None,
        previous: bytes | None = None,
    ) -> str | None:
        """Return "" when the keyframe passes, the problem text when it fails, None if unchecked."""
        try:
            result = await self._client.CheckKeyframe(
                shot_description,
                [_image(photo) for photo in product_photos],
                _image(master) if master else None,
                _image(keyframe),
                _image(persona) if persona else None,
                _image(previous) if previous else None,
            )
        except BamlError as error:
            logger.warning("Keyframe check failed: {}", str(error)[:300])
            return None
        return "" if result.passed else (result.problem.strip() or "The keyframe does not match.")
