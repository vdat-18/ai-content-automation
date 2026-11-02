"""Reference search profiles: one product type maps to Pinterest search keywords."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

_PROMPT = """You prepare image-reference searches for affiliate content on TikTok Shop Vietnam.
From the product below, return ONLY a JSON object with:
- "product_type": a short generic product type in Vietnamese lowercase (e.g. "máy cạo râu"),
- "keywords": 3 to 5 Pinterest search queries, mixing Vietnamese and English, for visual
  inspiration of the product's marketing photos (style, composition, setting),
- "exclude_keywords": up to 5 words that signal unrelated or junk pins.
Do not use brand names.

Product title: {title}
Categories: {categories}
Specifications: {specifications}
"""


@dataclass
class ReferenceProfile:
    product_type: str
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    status: str = "draft"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProfileGenerationError(RuntimeError):
    pass


class ReferenceProfileGenerator:
    """Ask an OpenAI-compatible chat model for the product type and search keywords."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = client

    async def generate(self, product: dict[str, Any]) -> ReferenceProfile:
        prompt = _PROMPT.format(
            title=product.get("title") or "",
            categories=" > ".join(product.get("categories") or []),
            specifications=json.dumps(product.get("specifications") or {}, ensure_ascii=False)[
                :800
            ],
        )
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body = {"model": self._model, "messages": [{"role": "user", "content": prompt}]}
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions", json=body, headers=headers
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            raise ProfileGenerationError(f"LLM request failed: {error}") from error
        finally:
            if self._client is None:
                await client.aclose()
        return parse_profile(content)


def parse_profile(content: str) -> ReferenceProfile:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    product_type = str(data.get("product_type") or "").strip().lower()
    keywords = [str(k).strip() for k in data.get("keywords") or [] if str(k).strip()]
    if not product_type or not keywords:
        raise ProfileGenerationError("LLM answer had no product type or keywords")
    exclude = [str(k).strip() for k in data.get("exclude_keywords") or [] if str(k).strip()]
    return ReferenceProfile(product_type, keywords[:5], exclude[:5])
