"""LLM review of a storyboard, run before any image or clip is paid for."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry
from ai_content.domains.marketing.products.briefing import product_facts

_BRIEF_KEYS = ("title", "shots")


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())


class _BamlReviewClient(Protocol):
    async def ReviewStoryboard(
        self, product_json: str, brief_json: str, rules: str
    ) -> baml_types.StoryboardReview: ...


class StoryboardReviewer:
    """Ask the BAML screening model whether a storyboard is ready to be filmed."""

    def __init__(self, client: _BamlReviewClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> StoryboardReviewer:
        registry = build_client_registry(
            name="StoryboardReview",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
        )
        return cls(b.with_options(client_registry=registry))

    async def review(
        self, product: dict[str, Any], brief: dict[str, Any], rules: str = ""
    ) -> list[str] | None:
        """Return the problems found ([] when it passes), or None when the review failed."""
        story = {key: brief.get(key) for key in _BRIEF_KEYS}
        facts = json.dumps(product_facts(product), ensure_ascii=False)
        try:
            result = await self._client.ReviewStoryboard(
                facts,
                json.dumps(story, ensure_ascii=False),
                rules or "(none)",
            )
        except BamlError as error:
            logger.warning("Storyboard review failed: {}", str(error)[:300])
            return None
        problems = [
            f"{item.where.strip()}: {item.problem.strip()} Fix: {item.fix.strip()}"
            for item in result.problems
        ]
        # A claim counts only when the quote that backs it really is in the product data
        known = _plain(facts)
        problems += [
            f'{claim.where.strip()}: "{claim.claim.strip()}" is not in the product data. '
            "Fix: remove it or say only what the product data says."
            for claim in result.claims
            if not (claim.evidence and _plain(claim.evidence) in known)
        ]
        if result.passed and not problems:
            return []
        return problems or ["The reviewer rejected the storyboard without saying why."]
