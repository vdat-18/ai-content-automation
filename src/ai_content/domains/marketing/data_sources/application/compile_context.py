"""Compile latest synchronized records into existing Creative contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from ai_content.domains.marketing.creative.ports.contracts import (
    ContextPackage,
    CreativeConstraints,
    CustomerContext,
    EvidenceRef,
    HistoricalCreativeContext,
    OutputSpec,
    ProductFact,
    ProductFamilyContext,
    ProductFamilyRef,
    ProductMediaContext,
    ProductMetadata,
    ProductOptionContext,
    ProductSelectionScope,
    ProductVariantContext,
    SkuInput,
)

from ..domain.models import NormalizedRecord, SourceSnapshot


class CreativeContextUnavailableError(ValueError):
    """Expected absence or ambiguity of synchronized product context."""


class CreativeSourceContextCompiler:
    def product_family(
        self,
        snapshots: list[SourceSnapshot],
        *,
        brand: str,
        product_family_ref: ProductFamilyRef,
    ) -> ProductFamilyContext:
        snapshot, product = self._resolve_product(
            snapshots,
            sku_id=product_family_ref.family_key,
            product_family_ref=product_family_ref,
        )
        product_brand = _record_brand(product)
        if product_brand is None or _brand_key(product_brand) != _brand_key(brand):
            raise CreativeContextUnavailableError(
                "The selected Shopify product does not belong to the requested brand"
            )
        return _product_family(snapshot, product, product_family_ref.family_key)

    def compile(
        self,
        snapshots: list[SourceSnapshot],
        *,
        brand: str,
        sku_id: str,
        market: str,
        width: int,
        height: int,
        product_family_ref: ProductFamilyRef | None = None,
        selection_scope: ProductSelectionScope = ProductSelectionScope.PRODUCT_FAMILY,
        selected_variant_id: str | None = None,
        selected_product_media_ids: tuple[str, ...] = (),
    ) -> tuple[SkuInput, ContextPackage]:
        product_snapshot, product = self._resolve_product(
            snapshots,
            sku_id=sku_id,
            product_family_ref=product_family_ref,
        )
        product_brand = _record_brand(product)
        if product_brand is None or _brand_key(product_brand) != _brand_key(brand):
            raise CreativeContextUnavailableError(
                "The selected Shopify product does not belong to the requested brand"
            )
        matching = [
            item
            for item in snapshots
            if item.snapshot_id == product_snapshot.snapshot_id
            or self._supporting_context(item, brand)
        ]
        guideline = next(
            (
                f"{snapshot.source_id}:{snapshot.snapshot_id}:{record.provider_id}"
                for snapshot in matching
                for record in snapshot.records
                if record.kind == "brand_guideline"
                and (
                    snapshot.snapshot_id == product_snapshot.snapshot_id
                    or record_matches_brand(record, brand)
                )
            ),
            None,
        )
        strategy = [
            record.data
            for snapshot in matching
            for record in snapshot.records
            if record.kind == "creative_strategy"
            and (
                snapshot.snapshot_id == product_snapshot.snapshot_id
                or record_matches_brand(record, brand)
            )
        ]
        evidence = tuple(
            EvidenceRef(snapshot.source_id, snapshot.checksum_sha256, snapshot.captured_at)
            for snapshot in matching
        )
        family = _product_family(product_snapshot, product, sku_id)
        selected_variant = None
        if selection_scope == ProductSelectionScope.VARIANT:
            selected_variant = next(
                (item for item in family.variants if item.variant_id == selected_variant_id),
                None,
            )
            if selected_variant is None:
                raise CreativeContextUnavailableError(
                    "The selected Shopify variant does not belong to this product family"
                )
        media = tuple(
            item
            for item in family.media
            if selected_variant is None
            or not item.variant_ids
            or selected_variant.variant_id in item.variant_ids
        )
        if selected_product_media_ids:
            requested_media = set(selected_product_media_ids)
            known_media = {item.media_id for item in family.media}
            if not requested_media.issubset(known_media):
                raise CreativeContextUnavailableError(
                    "Selected product media does not belong to this Product Family"
                )
            media = tuple(item for item in media if item.media_id in requested_media)
        if not media:
            raise CreativeContextUnavailableError(
                "No selected product media is mapped to this Product Variant"
            )
        if selected_variant is not None:
            media = tuple(
                replace(
                    item,
                    variant_ids=(selected_variant.variant_id,) if item.variant_ids else (),
                )
                for item in media
            )
            family = replace(family, variants=(selected_variant,), media=media)
        price = selected_variant.price if selected_variant is not None else _first_price(family)
        family_key = family.ref.family_key
        sku = SkuInput(
            sku_id=family_key,
            sku_name=family.title,
            product_metadata=ProductMetadata(
                image_refs=tuple(item.url for item in media),
                price=price,
                currency=str(product.data.get("currency") or "USD"),
                differentiators=tuple(
                    str(item.get("Differentiator"))
                    for item in strategy
                    if item.get("Differentiator")
                ),
            ),
            creative_constraints=CreativeConstraints(
                OutputSpec(width, height, "png", f"{width}:{height}"),
                brand_guideline_ref=guideline,
                banned_claims=_claim_values(family, "banned"),
            ),
            customer_context=CustomerContext(
                pain_points=tuple(
                    str(item.get("Pain Point")) for item in strategy if item.get("Pain Point")
                ),
                promises=tuple(
                    str(item.get("Promise")) for item in strategy if item.get("Promise")
                ),
            ),
            historical_creative_context=HistoricalCreativeContext(
                tested_angles=tuple(
                    str(item.get("Angle")) for item in strategy if item.get("Angle")
                )
            ),
            product_family=family,
        )
        context_key = ":".join(sorted(snapshot.checksum_sha256[:12] for snapshot in matching))
        context = ContextPackage(
            context_id=f"external:{brand}:{market}:{family.ref.product_id}:{context_key}",
            source_run_id=f"external:{brand}:{family.ref.source_id}:{family.ref.product_id}",
            sku_id=family_key,
            brand=brand,
            evidence=evidence,
            historical=sku.historical_creative_context,
            brand_guideline_ref=guideline,
            collected_at=datetime.now(UTC),
        )
        return sku, context

    @staticmethod
    def _resolve_product(
        snapshots: list[SourceSnapshot],
        *,
        sku_id: str,
        product_family_ref: ProductFamilyRef | None,
    ) -> tuple[SourceSnapshot, NormalizedRecord]:
        candidates = [
            (snapshot, record)
            for snapshot in snapshots
            for record in snapshot.records
            if record.kind == "product"
            and (
                (
                    product_family_ref is not None
                    and snapshot.source_id == product_family_ref.source_id
                    and str(record.data.get("product_id") or record.provider_id)
                    == product_family_ref.product_id
                )
                or (product_family_ref is None and sku_id in record.data.get("variant_skus", ()))
            )
        ]
        if not candidates:
            raise CreativeContextUnavailableError(
                "No synchronized Shopify product matches this Product Family"
            )
        if len(candidates) > 1:
            raise CreativeContextUnavailableError(
                "Multiple Shopify products match this Product Family; select an exact product ID"
            )
        return candidates[0]

    @staticmethod
    def _supporting_context(snapshot: SourceSnapshot, brand: str) -> bool:
        return any(record_matches_brand(record, brand) for record in snapshot.records)


def record_matches_brand(record: NormalizedRecord, brand: str) -> bool:
    record_brand = _record_brand(record)
    return record_brand is not None and _brand_key(record_brand) == _brand_key(brand)


def _brand_key(value: str) -> str:
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    return normalized or value.strip().casefold()


def _record_brand(record: NormalizedRecord) -> str | None:
    for key, value in record.data.items():
        if str(key).casefold() in {"brand", "brand_id"} and isinstance(value, str):
            brand = value.strip()
            if brand:
                return brand
    return None


def _product_family(
    snapshot: SourceSnapshot,
    product: NormalizedRecord,
    fallback_family_key: str,
) -> ProductFamilyContext:
    data = product.data
    variants = tuple(_variant(item) for item in data.get("variants", ()) if isinstance(item, dict))
    if not variants and data.get("variant_skus"):
        variants = tuple(
            ProductVariantContext(
                variant_id=f"legacy-variant:{product.provider_id}:{index}",
                sku=str(sku),
                title=str(sku),
                position=index,
                selected_options=(),
                price=_decimal(data.get("price")),
                compare_at_price=None,
                media_ids=(),
            )
            for index, sku in enumerate(data.get("variant_skus", ()), 1)
            if sku
        )
    if not variants:
        raise CreativeContextUnavailableError("Shopify product has no usable variants")
    variant_ids = {item.variant_id for item in variants}
    media = tuple(
        item
        for item in (
            _media(raw, index, variant_ids)
            for index, raw in enumerate(data.get("media", ()), 1)
            if isinstance(raw, dict)
        )
        if item is not None
    )
    if not media:
        media = tuple(
            ProductMediaContext(
                media_id=f"legacy-media:{index}",
                url=str(url),
                position=index,
                variant_ids=(),
            )
            for index, url in enumerate(data.get("image_urls", ()), 1)
            if url
        )
    family_key = str(data.get("family_key") or data.get("sku") or fallback_family_key)
    return ProductFamilyContext(
        ref=ProductFamilyRef(
            source_id=snapshot.source_id,
            store_id=str(data.get("store_id")) if data.get("store_id") else None,
            product_id=str(data.get("product_id") or product.provider_id),
            family_key=family_key,
        ),
        handle=str(data.get("handle") or data.get("product_id") or product.provider_id),
        title=str(data.get("title") or family_key),
        description_html=(str(data["description_html"]) if data.get("description_html") else None),
        vendor=str(data["vendor"]) if data.get("vendor") else None,
        product_type=str(data["product_type"]) if data.get("product_type") else None,
        status=str(data["status"]) if data.get("status") else None,
        tags=_tags(data.get("tags")),
        options=tuple(
            ProductOptionContext(
                option_id=str(item.get("id") or f"option:{item.get('position', index)}"),
                name=str(item.get("name") or "Option"),
                position=int(item.get("position") or index),
                values=tuple(str(value) for value in item.get("values", ()) if value is not None),
            )
            for index, item in enumerate(data.get("options", ()), 1)
            if isinstance(item, dict)
        ),
        variants=variants,
        media=media,
        facts=tuple(
            ProductFact(
                namespace=str(item.get("namespace") or ""),
                key=str(item.get("key") or ""),
                value_type=str(item.get("type") or "string"),
                raw_value=str(item.get("value") or ""),
                canonical_value=(
                    str(item["canonical_value"])
                    if item.get("canonical_value") is not None
                    else None
                ),
                updated_at=str(item["updated_at"]) if item.get("updated_at") else None,
            )
            for item in data.get("metafields", ())
            if isinstance(item, dict) and item.get("namespace") and item.get("key")
        ),
        published_at=str(data["published_at"]) if data.get("published_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )


def _variant(item: dict[str, object]) -> ProductVariantContext:
    return ProductVariantContext(
        variant_id=str(item.get("id") or ""),
        sku=str(item["sku"]) if item.get("sku") else None,
        title=str(item.get("title") or item.get("sku") or "Variant"),
        position=int(item.get("position") or 1),
        selected_options=tuple(
            (str(option.get("name") or "Option"), str(option.get("value") or ""))
            for option in item.get("selected_options", ())
            if isinstance(option, dict)
        ),
        price=_decimal(item.get("price")),
        compare_at_price=_decimal(item.get("compare_at_price")),
        media_ids=tuple(str(value) for value in item.get("media_ids", ()) if value),
        created_at=str(item["created_at"]) if item.get("created_at") else None,
        updated_at=str(item["updated_at"]) if item.get("updated_at") else None,
    )


def _media(
    item: dict[str, object], position: int, known_variant_ids: set[str]
) -> ProductMediaContext | None:
    url = item.get("url") or item.get("src")
    media_id = item.get("id")
    if not url or not media_id:
        return None
    variant_ids = tuple(
        value
        for value in (str(raw) for raw in item.get("variant_ids", ()) if raw)
        if value in known_variant_ids
    )
    return ProductMediaContext(
        media_id=str(media_id),
        url=str(url),
        position=int(item.get("position") or position),
        variant_ids=variant_ids,
        alt=str(item["alt"]) if item.get("alt") else None,
        width=int(item["width"]) if item.get("width") is not None else None,
        height=int(item["height"]) if item.get("height") is not None else None,
    )



def product_claim_values(family: ProductFamilyContext, kind: str) -> tuple[str, ...]:
    return _claim_values(family, kind)


def _claim_values(family: ProductFamilyContext, kind: str) -> tuple[str, ...]:
    accepted_keys = {
        "approved": {"approved_claim", "approved_claims", "allowed_claim", "allowed_claims"},
        "banned": {
            "banned_claim",
            "banned_claims",
            "prohibited_claim",
            "prohibited_claims",
        },
    }[kind]
    values: list[str] = []
    for fact in family.facts:
        if fact.key.casefold().replace("-", "_") not in accepted_keys:
            continue
        raw = fact.canonical_value or fact.raw_value
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            candidates = [str(item) for item in parsed]
        elif isinstance(parsed, str):
            candidates = [parsed]
        else:
            candidates = raw.replace("|", "\n").replace(";", "\n").splitlines()
        for candidate in candidates:
            value = candidate.strip()
            if value and value not in values:
                values.append(value)
    return tuple(values)

def _first_price(family: ProductFamilyContext) -> Decimal | None:
    return next((item.price for item in family.variants if item.price is not None), None)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


__all__ = [
    "CreativeContextUnavailableError",
    "CreativeSourceContextCompiler",
    "product_claim_values",
    "record_matches_brand",
]
