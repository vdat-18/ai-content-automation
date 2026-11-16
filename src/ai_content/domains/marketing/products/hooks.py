"""Alternative opening lines for an ad, so several hooks can be tried on the same clips."""

from __future__ import annotations

import json
from typing import Any, Protocol

from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry
from ai_content.domains.marketing.products.briefing import product_facts as brief_facts

HOOK_COUNT = 3


class _BamlHookClient(Protocol):
    async def WriteHooks(
        self, product_json: str, story_json: str, rules: str, count: int
    ) -> baml_types.HookOptions: ...


class HookWriter:
    """Ask the BAML screening model for hooks that fit the storyboard's opening scene."""

    def __init__(self, client: _BamlHookClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> HookWriter:
        registry = build_client_registry(
            name="HookVariants",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0.8,
        )
        return cls(b.with_options(client_registry=registry))

    async def write(
        self,
        product: dict[str, Any],
        brief: dict[str, Any],
        rules: str = "",
        count: int = HOOK_COUNT,
    ) -> list[dict[str, str]] | None:
        """Return the hooks the model wrote, or None when it did not answer."""
        story = {"title": brief.get("title"), "opening_scene": (brief.get("shots") or [None])[0]}
        try:
            result = await self._client.WriteHooks(
                json.dumps(brief_facts(product), ensure_ascii=False),
                json.dumps(story, ensure_ascii=False),
                rules or "(none)",
                count,
            )
        except BamlError as error:
            logger.warning("Hook writing failed: {}", str(error)[:300])
            return None
        return [{"angle": h.angle.strip(), "text": h.text.strip()} for h in result.hooks]
