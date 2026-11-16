"""Shorten a voice-over line that reads longer than its shot."""

from __future__ import annotations

from typing import Protocol

from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

from .speech import MAX_SPEEDUP

# aim a little under the longest reading the shot can absorb, so the read does not just scrape by
_AIM = 0.9


class _BamlShortenClient(Protocol):
    async def ShortenVoiceover(
        self, line: str, max_words: int, rules: str
    ) -> baml_types.ShortenedLine: ...


def words_that_fit(text: str, length: float, seconds: float) -> int:
    """How many words of `text` fit its shot, when the reading takes `length` s naturally.

    The reading can be sped up to MAX_SPEEDUP and must still end inside `seconds`.
    """
    count = len(text.split())
    return max(1, int(count * seconds * MAX_SPEEDUP * _AIM / length))


class VoiceShortener:
    """Ask the BAML screening model for a shorter line that says the same with the same figures."""

    def __init__(self, client: _BamlShortenClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> VoiceShortener:
        registry = build_client_registry(
            name="ShortenVoiceover",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0.3,
        )
        return cls(b.with_options(client_registry=registry))

    async def shorten(self, text: str, max_words: int, rules: str = "") -> str | None:
        """The shorter line, or None when the model did not answer or the line is not shorter."""
        try:
            result = await self._client.ShortenVoiceover(text, max_words, rules or "(none)")
        except BamlError as error:
            logger.warning("Shortening a voice-over line failed: {}", str(error)[:300])
            return None
        shorter = " ".join(result.text.split())
        if not _fits(shorter, text, max_words):
            logger.warning("A shortened voice-over line was refused: {}", shorter[:120])
            return None
        return shorter


def _fits(shorter: str, text: str, max_words: int) -> bool:
    """Shorter than the original and within the word limit the shot can say."""
    return 0 < len(shorter.split()) <= max_words and len(shorter.split()) < len(text.split())
