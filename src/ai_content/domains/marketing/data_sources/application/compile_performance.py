"""Project read-only Ads snapshots into reviewable Performance evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..domain.models import (
    DataSourceDefinition,
    DataSourceProvider,
    NormalizedRecord,
    SourceSnapshot,
)


@dataclass(frozen=True)
class ProductPerformanceCandidate:
    """One Google Ads product item aggregated over its configured reporting window."""

    source_id: str
    snapshot_id: str
    brand: str | None
    product_item_id: str
    sku_id: str | None
    sku_mapping_status: str
    window_start: str | None
    window_end: str | None
    currency: str | None
    record_count: int
    impressions: Decimal | None
    clicks: Decimal | None
    spend: Decimal | None
    conversions: Decimal | None
    conversion_value: Decimal | None
    roas: Decimal | None


@dataclass(frozen=True)
class CreativePerformanceCandidate:
    """One Meta Ads row without asserting an unavailable Creative-version link."""

    source_id: str
    snapshot_id: str
    brand: str | None
    ad_id: str
    ad_name: str | None
    creative_lineage_status: str
    window_label: str
    currency: str | None
    impressions: Decimal | None
    clicks: Decimal | None
    spend: Decimal | None
    purchases: Decimal | None
    add_to_cart: Decimal | None
    purchase_conversion_value: Decimal | None
    roas: Decimal | None
    cost_per_atc: Decimal | None


@dataclass(frozen=True)
class SourcePerformanceReport:
    """Candidate-level evidence from the latest configured read-only snapshots."""

    products: tuple[ProductPerformanceCandidate, ...]
    creatives: tuple[CreativePerformanceCandidate, ...]


@dataclass(frozen=True)
class _CatalogIdentity:
    variant_skus: dict[str, set[str]]
    variant_ids: _IdentifierIndex
    product_ids: _IdentifierIndex
    currency: str | None


@dataclass(frozen=True)
class _IdentifierIndex:
    """Resolve provider identifiers without scanning the full catalog per Ads row."""

    values: dict[str, set[str]]
    anchors: dict[str, set[str]]


class SourcePerformanceCompiler:
    """Aggregate provider-normalized records without inventing attribution or lineage."""

    def compile(
        self,
        snapshots: list[SourceSnapshot],
        definitions: tuple[DataSourceDefinition, ...],
    ) -> SourcePerformanceReport:
        latest = _latest_by_source(snapshots)
        definitions_by_source = {item.source_id: item for item in definitions}
        catalogs = self._catalogs(latest, definitions_by_source)
        products: list[ProductPerformanceCandidate] = []
        creatives: list[CreativePerformanceCandidate] = []

        for source_id, snapshot in latest.items():
            definition = definitions_by_source.get(source_id)
            if definition is None:
                continue
            if definition.provider == DataSourceProvider.GOOGLE_ADS:
                products.extend(self._products(snapshot, definition, catalogs))
            elif definition.provider == DataSourceProvider.META_ADS:
                creatives.extend(self._creatives(snapshot, definition, catalogs))

        return SourcePerformanceReport(
            products=tuple(
                sorted(
                    products,
                    key=lambda item: (
                        item.conversion_value is None,
                        -(item.conversion_value or Decimal()),
                        item.product_item_id,
                    ),
                )
            ),
            creatives=tuple(
                sorted(
                    creatives,
                    key=lambda item: (
                        item.purchase_conversion_value is None,
                        -(item.purchase_conversion_value or Decimal()),
                        item.ad_id,
                    ),
                )
            ),
        )

    def _catalogs(
        self,
        snapshots: dict[str, SourceSnapshot],
        definitions: dict[str, DataSourceDefinition],
    ) -> dict[str, _CatalogIdentity]:
        catalogs: dict[str, _CatalogIdentity] = {}
        for source_id, snapshot in snapshots.items():
            definition = definitions.get(source_id)
            if definition is None or definition.provider != DataSourceProvider.SHOPIFY:
                continue
            brand = _brand(definition)
            if brand is None:
                continue
            variant_skus: dict[str, set[str]] = {}
            variant_ids: dict[str, set[str]] = {}
            product_ids: dict[str, set[str]] = {}
            currencies: set[str] = set()
            for record in snapshot.records:
                if record.kind != "product":
                    continue
                product_ids.setdefault(record.provider_id, set()).add(record.provider_id)
                currency = _text(record.data.get("currency"))
                if currency:
                    currencies.add(currency)
                for sku in record.data.get("variant_skus", ()):  # Legacy snapshots.
                    value = _text(sku)
                    if value:
                        variant_skus.setdefault(value, set()).add(value)
                for variant in record.data.get("variants", ()):  # Current snapshots.
                    if not isinstance(variant, dict):
                        continue
                    sku = _text(variant.get("sku"))
                    variant_id = _text(variant.get("id"))
                    if sku:
                        variant_skus.setdefault(sku, set()).add(sku)
                    if sku and variant_id:
                        variant_ids.setdefault(variant_id, set()).add(sku)
            catalogs[_brand_key(brand)] = _CatalogIdentity(
                variant_skus=variant_skus,
                variant_ids=_identifier_index(variant_ids),
                product_ids=_identifier_index(product_ids),
                currency=next(iter(currencies)) if len(currencies) == 1 else None,
            )
        return catalogs

    def _products(
        self,
        snapshot: SourceSnapshot,
        definition: DataSourceDefinition,
        catalogs: dict[str, _CatalogIdentity],
    ) -> list[ProductPerformanceCandidate]:
        grouped: dict[str, list[NormalizedRecord]] = {}
        for record in snapshot.records:
            if record.kind != "product_performance":
                continue
            product_item_id = _text(record.data.get("sku"))
            if product_item_id:
                grouped.setdefault(product_item_id, []).append(record)
        brand = _brand(definition)
        catalog = catalogs.get(_brand_key(brand)) if brand else None
        window_start, window_end = _google_window(definition)
        candidates: list[ProductPerformanceCandidate] = []
        for product_item_id, records in grouped.items():
            sku_id, mapping_status = _resolve_sku(product_item_id, catalog)
            candidates.append(
                ProductPerformanceCandidate(
                    source_id=definition.source_id,
                    snapshot_id=snapshot.snapshot_id,
                    brand=brand,
                    product_item_id=product_item_id,
                    sku_id=sku_id,
                    sku_mapping_status=mapping_status,
                    window_start=window_start,
                    window_end=window_end,
                    currency=catalog.currency if catalog is not None else None,
                    record_count=len(records),
                    impressions=_sum(records, "impressions"),
                    clicks=_sum(records, "clicks"),
                    spend=_sum(records, "cost"),
                    conversions=_sum(records, "conversions"),
                    conversion_value=_sum(records, "conversion_value"),
                    roas=_ratio(_sum(records, "conversion_value"), _sum(records, "cost")),
                )
            )
        return candidates

    def _creatives(
        self,
        snapshot: SourceSnapshot,
        definition: DataSourceDefinition,
        catalogs: dict[str, _CatalogIdentity],
    ) -> list[CreativePerformanceCandidate]:
        brand = _brand(definition)
        catalog = catalogs.get(_brand_key(brand)) if brand else None
        window_label = _meta_window(definition)
        candidates: list[CreativePerformanceCandidate] = []
        for record in snapshot.records:
            if record.kind != "ad_performance":
                continue
            spend = _decimal(record.data.get("spend"))
            purchase_value = _decimal(record.data.get("purchase_conversion_value"))
            atc = _decimal(record.data.get("add_to_cart"))
            candidates.append(
                CreativePerformanceCandidate(
                    source_id=definition.source_id,
                    snapshot_id=snapshot.snapshot_id,
                    brand=brand,
                    ad_id=_text(record.data.get("ad_id")) or record.provider_id,
                    ad_name=_text(record.data.get("ad_name")),
                    creative_lineage_status="unlinked",
                    window_label=window_label,
                    currency=catalog.currency if catalog is not None else None,
                    impressions=_decimal(record.data.get("impressions")),
                    clicks=_decimal(record.data.get("clicks")),
                    spend=spend,
                    purchases=_decimal(record.data.get("purchases")),
                    add_to_cart=atc,
                    purchase_conversion_value=purchase_value,
                    roas=_ratio(purchase_value, spend),
                    cost_per_atc=_ratio(spend, atc),
                )
            )
        return candidates


def _latest_by_source(snapshots: list[SourceSnapshot]) -> dict[str, SourceSnapshot]:
    latest: dict[str, SourceSnapshot] = {}
    for snapshot in snapshots:
        current = latest.get(snapshot.source_id)
        if current is None or snapshot.captured_at > current.captured_at:
            latest[snapshot.source_id] = snapshot
    return latest


def _brand(definition: DataSourceDefinition) -> str | None:
    return _text(definition.metadata.get("brand"))


def _brand_key(value: str) -> str:
    return value.casefold()


def _google_window(definition: DataSourceDefinition) -> tuple[str | None, str | None]:
    for resource in definition.resources:
        if resource.get("kind") == "product_performance":
            return _text(resource.get("start_date")), _text(resource.get("end_date"))
    return None, None


def _meta_window(definition: DataSourceDefinition) -> str:
    for resource in definition.resources:
        if resource.get("kind") != "insights":
            continue
        if date_preset := _text(resource.get("date_preset")):
            return date_preset
        start_date = _text(resource.get("start_date"))
        end_date = _text(resource.get("end_date"))
        if start_date and end_date:
            return f"{start_date}:{end_date}"
    return "configured_window"


def _resolve_sku(value: str, catalog: _CatalogIdentity | None) -> tuple[str | None, str]:
    if catalog is None:
        return None, "catalog_unavailable"
    direct = catalog.variant_skus.get(value, set())
    if len(direct) == 1:
        return next(iter(direct)), "matched_sku"
    if len(direct) > 1:
        return None, "ambiguous_sku"
    variant_matches = _identifier_matches(value, catalog.variant_ids)
    if len(variant_matches) == 1:
        return next(iter(variant_matches)), "matched_variant"
    if len(variant_matches) > 1:
        return None, "ambiguous_variant"
    if _identifier_matches(value, catalog.product_ids):
        return None, "product_only"
    return None, "unmapped"


def _identifier_index(values: dict[str, set[str]]) -> _IdentifierIndex:
    anchors: dict[str, set[str]] = {}
    for identifier in values:
        anchor = _identifier_anchor(identifier)
        if anchor:
            anchors.setdefault(anchor, set()).add(identifier)
    return _IdentifierIndex(values=values, anchors=anchors)


def _identifier_matches(value: str, identifiers: _IdentifierIndex) -> set[str]:
    matches: set[str] = set()
    direct = identifiers.values.get(value)
    if direct:
        matches.update(direct)
    candidate_ids: set[str] = set()
    for anchor in _value_anchors(value):
        candidate_ids.update(identifiers.anchors.get(anchor, set()))
    for identifier in candidate_ids:
        mapped = identifiers.values[identifier]
        if _contains_identifier(value, identifier):
            matches.update(mapped)
    return matches


def _identifier_anchor(identifier: str) -> str | None:
    numeric = re.findall(r"\d+", identifier)
    if numeric:
        return max(numeric, key=lambda item: (len(item), item))
    parts = re.findall(r"[A-Za-z0-9]+", identifier)
    return max(parts, key=lambda item: (len(item), item)) if parts else None


def _value_anchors(value: str) -> set[str]:
    numeric = set(re.findall(r"\d+", value))
    if numeric:
        return numeric
    parts = re.findall(r"[A-Za-z0-9]+", value)
    return {max(parts, key=lambda item: (len(item), item))} if parts else set()


def _contains_identifier(value: str, identifier: str) -> bool:
    if not identifier:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])", value) is not None


def _sum(records: list[NormalizedRecord], field: str) -> Decimal | None:
    values = [_decimal(record.data.get(field)) for record in records]
    if not values or any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal())


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "CreativePerformanceCandidate",
    "ProductPerformanceCandidate",
    "SourcePerformanceCompiler",
    "SourcePerformanceReport",
]
