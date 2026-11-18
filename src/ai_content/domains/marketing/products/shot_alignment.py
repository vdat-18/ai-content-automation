"""Keep the written description and motion of a shot in line with its remade picture."""

from __future__ import annotations

import json
from typing import Any, Protocol

from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

from .briefing import _small_image

_SHOT_KEYS = ("role", "delivery", "description", "motion_prompt", "voiceover")


class _BamlAlignClient(Protocol):
    async def AlignShot(
        self, shot_json: str, image: BamlImage, note: str
    ) -> baml_types.AlignedShot: ...


class ShotAligner:
    """Ask the model to rewrite a shot's description and motion prompt for its new picture."""

    def __init__(self, client: _BamlAlignClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> ShotAligner:
        registry = build_client_registry(
            name="AlignShot",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0.2,
        )
        return cls(b.with_options(client_registry=registry))

    async def align(self, shot: dict[str, Any], image: bytes, note: str) -> dict[str, str] | None:
        """The new description and motion prompt, or None when the model did not answer."""
        facts = {key: shot.get(key) for key in _SHOT_KEYS}
        try:
            result = await self._client.AlignShot(
                json.dumps(facts, ensure_ascii=False), _small_image(image), note
            )
        except BamlError as error:
            logger.warning("Aligning a shot with its new picture failed: {}", str(error)[:300])
            return None
        description = " ".join(result.description.split())
        motion = " ".join(result.motion_prompt.split())
        if not description or not motion:
            return None
        return {"description": description, "motion_prompt": motion}
