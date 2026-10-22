"""Build bounded, versioned brand context for research acceptance decisions."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ai_content.domains.marketing.data_sources.domain.models import (
    NormalizedRecord,
)
from ai_content.domains.marketing.data_sources.ports.interfaces import (
    IDataSourceRepository,
)

from .models import ResearchBrandContext

_SUPPORTED_KINDS = {"brand_guideline", "creative_strategy", "product"}
_PRODUCT_LIMIT = 100
_SUPPORTING_FACT_LIMIT = 100
_BRAND_ALIAS_GROUPS = (frozenset({"demofurn", "demofurniture"}),)


class ResearchBrandContextResolver:
    def __init__(self, repository: IDataSourceRepository) -> None:
        self._repository = repository

    async def resolve(self, brand_id: str) -> ResearchBrandContext:
        snapshots = await self._repository.list_latest_snapshots()
        matched = [
            (snapshot, record)
            for snapshot in snapshots
            for record in snapshot.records
            if record.kind in _SUPPORTED_KINDS
            and (
                _matches_brand(record, brand_id)
                or (
                    record.kind == "product"
                    and not _record_brand_values(record)
                    and _source_matches_brand(snapshot.source_id, brand_id)
                )
            )
        ]
        products = [item for item in matched if item[1].kind == "product"]
        if not products:
            raise ValueError(f"No synchronized product context is available for brand {brand_id}")
        source_versions = tuple(
            sorted(
                {
                    f"{snapshot.source_id}:{snapshot.checksum_sha256}"
                    for snapshot, _record in matched
                }
            )
        )
        product_facts = tuple(
            fact
            for _snapshot, record in products[:_PRODUCT_LIMIT]
            if (fact := _product_fact(record))
        )
        supporting_facts = tuple(
            fact
            for _snapshot, record in matched
            if record.kind != "product"
            for fact in _supporting_facts(record)
        )[:_SUPPORTING_FACT_LIMIT]
        payload = {
            "brand_id": brand_id,
            "source_versions": source_versions,
            "product_facts": product_facts,
            "supporting_facts": supporting_facts,
        }
        version = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return ResearchBrandContext(version=version, **payload)


def _matches_brand(record: NormalizedRecord, brand_id: str) -> bool:
    expected = brand_alias_keys(brand_id)
    return any(
        candidate == requested or candidate.startswith(requested)
        for value in _record_brand_values(record)
        for requested in expected
        for candidate in brand_alias_keys(value)
    )


def _record_brand_values(record: NormalizedRecord) -> tuple[str, ...]:
    return tuple(
        value
        for key, value in record.data.items()
        if str(key).casefold() in {"brand", "brand_id"} and isinstance(value, str)
    )


def _brand_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def brand_alias_keys(value: str) -> set[str]:
    """Return normalized lookup keys for a Brand display name or known alias."""

    tokens = [token.casefold() for token in re.findall(r"[a-zA-Z0-9]+", value)]
    aliases = {_brand_key(value)}
    if len(tokens) > 1:
        aliases.add("".join(token if len(token) <= 3 else token[0] for token in tokens))
    for group in _BRAND_ALIAS_GROUPS:
        if aliases & group:
            aliases.update(group)
    return aliases


def _source_matches_brand(source_id: str, brand_id: str) -> bool:
    source_tokens = {_brand_key(token) for token in re.split(r"[^a-zA-Z0-9]+", source_id) if token}
    return _brand_key(brand_id) in source_tokens


def _product_fact(record: NormalizedRecord) -> str:
    data = record.data
    values = [
        data.get("title"),
        data.get("product_type"),
        data.get("vendor"),
        data.get("description_html"),
        data.get("tags"),
    ]
    parts = [_plain_text(value) for value in values]
    return " | ".join(part for part in parts if part)[:2_000]


def _supporting_facts(record: NormalizedRecord) -> tuple[str, ...]:
    accepted_keys = {
        "angle",
        "content",
        "differentiator",
        "pain point",
        "persona",
        "promise",
    }
    return tuple(
        value
        for key, raw in record.data.items()
        if str(key).casefold() in accepted_keys and (value := _plain_text(raw))
    )


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        text = ", ".join(str(item) for item in value if item is not None)
    elif isinstance(value, (str, int, float, bool)):
        text = str(value)
    else:
        return ""
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())[:5_000]


__all__ = ["ResearchBrandContextResolver", "brand_alias_keys"]
