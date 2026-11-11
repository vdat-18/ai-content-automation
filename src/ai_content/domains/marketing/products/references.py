"""Reference search profiles: one product type maps to Pinterest search keywords."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from baml_py.baml_py import BamlError

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry


@dataclass
class ReferenceProfile:
    product_type: str
    keywords: list[str] = field(default_factory=list)
    status: str = "draft"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProfileGenerationError(RuntimeError):
    pass


class _BamlProfileClient(Protocol):
    async def DraftReferenceSearchProfile(
        self, product_json: str
    ) -> baml_types.ReferenceSearchProfileDraft: ...


class ReferenceProfileGenerator:
    """Draft the product type and Pinterest keywords of a product with the BAML screening model."""

    def __init__(self, client: _BamlProfileClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> ReferenceProfileGenerator:
        registry = build_client_registry(
            name="ReferenceSearchProfile",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
        )
        return cls(b.with_options(client_registry=registry))

    async def generate(self, product: dict[str, Any]) -> ReferenceProfile:
        facts = {
            "title": product.get("title"),
            "categories": product.get("categories"),
            "specifications": product.get("specifications"),
        }
        try:
            draft = await self._client.DraftReferenceSearchProfile(
                json.dumps(facts, ensure_ascii=False)[:2_000]
            )
        except BamlError as error:
            raise ProfileGenerationError(str(error)) from error
        return ReferenceProfile(
            product_type=draft.product_type.strip().lower(),
            keywords=draft.keywords[:5],
        )
