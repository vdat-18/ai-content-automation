"""Compact product truth exposed to Creative models."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from html.parser import HTMLParser

from pydantic import TypeAdapter

from ..ports.contracts import ProductFamilyContext
from ..ports.preparation import PreparationContext


class _ProductDescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def product_family_for_model(family: ProductFamilyContext) -> dict[str, object]:
    """Return product facts needed for Creative planning, without audit-only metadata."""
    return {
        "source_id": family.ref.source_id,
        "product_id": family.ref.product_id,
        "family_key": family.ref.family_key,
        "title": family.title,
        "description": _plain_text(family.description_html),
        "product_type": family.product_type,
        "variants": [
            {
                "variant_id": item.variant_id,
                "sku": item.sku,
                "title": item.title,
                "selected_options": dict(item.selected_options),
                "price": str(item.price) if item.price is not None else None,
                "compare_at_price": (
                    str(item.compare_at_price) if item.compare_at_price is not None else None
                ),
            }
            for item in family.variants
        ],
        "attributes": [
            {
                "name": item.key,
                "value": item.canonical_value or item.raw_value,
            }
            for item in family.facts
            if item.key.casefold().replace("-", "_")
            not in {
                "approved_claim",
                "approved_claims",
                "allowed_claim",
                "allowed_claims",
                "banned_claim",
                "banned_claims",
                "prohibited_claim",
                "prohibited_claims",
            }
        ],
        "media": [
            {
                "media_id": item.media_id,
                "variant_ids": list(item.variant_ids),
                "alt": item.alt,
                "width": item.width,
                "height": item.height,
            }
            for item in family.media
        ],
    }


def preparation_context_for_model(context: PreparationContext | object) -> dict[str, object]:
    """Serialize preparation context while replacing raw Shopify data with its AI view."""
    if isinstance(context, PreparationContext):
        payload = TypeAdapter(PreparationContext).dump_python(context, mode="json")
    elif is_dataclass(context):
        payload = asdict(context)
    else:
        raise TypeError("Preparation model context must be a dataclass")
    sku = getattr(context, "sku", None)
    family = getattr(sku, "product_family", None)
    sku_payload = payload.get("sku")
    if isinstance(family, ProductFamilyContext) and isinstance(sku_payload, dict):
        sku_payload["product_family"] = product_family_for_model(family)
    _remove_audit_identifiers(payload)
    return payload


def _remove_audit_identifiers(payload: dict[str, object]) -> None:
    """Keep immutable audit versions out of the model's citation vocabulary."""
    sources = payload.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict):
                source.pop("data_version", None)

    package = payload.get("package")
    if isinstance(package, dict):
        evidence = package.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if isinstance(item, dict):
                    item.pop("data_version", None)

    brand_profile = payload.get("brand_profile")
    if isinstance(brand_profile, dict):
        brand_profile.pop("profile_id", None)


def _plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    parser = _ProductDescriptionParser()
    parser.feed(value)
    parser.close()
    result = " ".join(parser.parts)
    return result or None
