"""Gemini check that a generated keyframe still shows the real product and the shared scene."""

from __future__ import annotations

import base64
from typing import Protocol

from baml_py import Image as BamlImage

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
        characters: list[BamlImage],
        previous_keyframe: BamlImage | None,
    ) -> baml_types.KeyframeCheck: ...



class QAProblem(str):
    """What a check found wrong, with the kind of problem it is (face, product, skin...)."""

    category: str

    def __new__(cls, text: str, category: str = "other") -> QAProblem:
        problem = super().__new__(cls, text)
        problem.category = category
        return problem


def _image(content: bytes) -> BamlImage:
    """The type comes from the bytes: a CDN often labels a webp picture as jpeg."""
    if content[:4] == b"\x89PNG":
        media_type = "image/png"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        media_type = "image/webp"
    else:
        media_type = "image/jpeg"
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
        )
        return cls(b.with_options(client_registry=registry))

    async def check(
        self,
        shot_description: str,
        product_photos: list[bytes],
        keyframe: bytes,
        master: bytes | None = None,
        persona: list[bytes] | None = None,
        previous: bytes | None = None,
    ) -> str | None:
        """Return "" when the keyframe passes or the problem text when it fails; a model error raises."""
        result = await self._client.CheckKeyframe(
            shot_description,
            [_image(photo) for photo in product_photos],
            _image(master) if master else None,
            _image(keyframe),
            [_image(photo) for photo in persona or []],
            _image(previous) if previous else None,
        )
        if result.passed:
            return ""
        return QAProblem(result.problem.strip() or "The keyframe does not match.", result.category)
