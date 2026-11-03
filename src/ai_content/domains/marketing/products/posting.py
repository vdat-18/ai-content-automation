"""Caption and hashtags that go with a finished video."""

from __future__ import annotations

import json
from typing import Any, Protocol

from baml_py.baml_py import BamlError

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry
from ai_content.domains.marketing.products.briefing import product_facts

_BRIEF_KEYS = ("title", "scene", "selling_angle", "target_audience", "style", "colors", "shots")
_SHOT_KEYS = ("role", "description", "on_screen_text", "voiceover")


class PostingPackageError(RuntimeError):
    """The model could not produce the posting text."""


class _BamlPostingClient(Protocol):
    async def WritePostingPackage(
        self, product_json: str, brief_json: str
    ) -> baml_types.PostingPackage: ...


def _brief_for_text(brief: dict[str, Any]) -> dict[str, Any]:
    compact = {key: brief.get(key) for key in _BRIEF_KEYS if key != "shots"}
    compact["shots"] = [
        {key: shot.get(key) for key in _SHOT_KEYS} for shot in brief.get("shots") or []
    ]
    return compact


def _hashtag(tag: str) -> str:
    return "#" + "".join(tag.split()).lstrip("#").lower()


class PostingPackageWriter:
    """Ask the BAML model for caption options and hashtags grounded in the brief."""

    def __init__(self, client: _BamlPostingClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> PostingPackageWriter:
        registry = build_client_registry(
            name="PostingPackage",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0.7,
            max_output_tokens=4000,
        )
        return cls(b.with_options(client_registry=registry))

    async def write(self, product: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
        try:
            draft = await self._client.WritePostingPackage(
                json.dumps(product_facts(product), ensure_ascii=False),
                json.dumps(_brief_for_text(brief), ensure_ascii=False),
            )
        except BamlError as error:
            raise PostingPackageError(str(error)) from error
        hashtags = list(dict.fromkeys(_hashtag(tag) for tag in draft.hashtags if tag.strip()))
        return {
            "captions": [caption.strip() for caption in draft.captions if caption.strip()],
            "hashtags": hashtags,
            "product_url": product.get("url") or "",
        }
