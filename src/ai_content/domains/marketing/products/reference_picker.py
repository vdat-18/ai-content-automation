"""A model looks at the closest reference photos of one shot and keeps the one that fits."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import httpx
from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry
from ai_content.domains.marketing.products.briefing import product_facts
from ai_content.domains.marketing.products.keyframe_check import _image

_SHOT_KEYS = ("role", "description", "keyframe_prompt", "delivery")


class ReferencePickerError(RuntimeError):
    """The model could not be reached or did not name one of the candidates."""


class _BamlPickerClient(Protocol):
    async def ChooseShotReference(
        self,
        product_json: str,
        shot_json: str,
        candidates: list[baml_types.ReferenceCandidate],
    ) -> baml_types.ShotReferenceChoice: ...


class ShotReferencePicker:
    def __init__(self, client: _BamlPickerClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> ShotReferencePicker:
        registry = build_client_registry(
            name="ShotReference",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
        )
        return cls(b.with_options(client_registry=registry))

    async def choose(
        self,
        product: dict[str, Any],
        shot: dict[str, Any],
        candidates: list[dict[str, str]],
        http: httpx.AsyncClient | None = None,
    ) -> str | None:
        """candidates: image_id, note, url. Returns the chosen image_id; None only when no candidate could be downloaded."""
        owned = http is None
        http = http or httpx.AsyncClient(timeout=30, follow_redirects=True)

        async def fetch(url: str) -> BamlImage | None:
            try:
                response = await http.get(url)
                response.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("Reference download failed: {}", str(error)[:200])
                return None
            return _image(response.content)

        try:
            images = await asyncio.gather(*(fetch(item["url"]) for item in candidates))
        finally:
            if owned:
                await http.aclose()
        labeled = {
            f"ref_{index + 1}": (item, image)
            for index, (item, image) in enumerate(zip(candidates, images, strict=True))
            if image is not None
        }
        if not labeled:
            return None
        try:
            result = await self._client.ChooseShotReference(
                json.dumps(product_facts(product), ensure_ascii=False),
                json.dumps({key: shot.get(key) for key in _SHOT_KEYS}, ensure_ascii=False),
                [
                    baml_types.ReferenceCandidate(label=label, note=item["note"], photo=image)
                    for label, (item, image) in labeled.items()
                ],
            )
        except BamlError as error:
            raise ReferencePickerError(str(error)[:300]) from error
        logger.info("Shot reference: model chose {!r} among {}", result.choice, list(labeled))
        found = labeled.get(result.choice.strip())
        if found is None:
            raise ReferencePickerError(f"The model chose {result.choice!r}, which is not a candidate")
        return found[0]["image_id"]
