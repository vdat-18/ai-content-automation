"""Deterministic mock connectors that return realistic synthetic source records.

A source opts in with ``"mock": true`` in its metadata. The generated world is a pure
function of ``(seed, brand)``: running it twice yields identical products and ad series.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..domain.models import DataSourceDefinition, DataSourceProvider, NormalizedRecord
from ..ports.interfaces import IDataSourceConnector, SourceReadError
from .http_connectors import _shopify_product

DEFAULT_SEED = 20260930
DEFAULT_END_DATE = date(2026, 9, 30)
DEFAULT_DAYS = 90
_STORY_BY_INDEX = ("fatigued", "winner", "new", "weak")


@dataclass(frozen=True)
class _Item:
    title: str
    product_type: str
    price: int
    options: tuple[tuple[str, tuple[str, ...]], ...]
    blurb: str


@dataclass(frozen=True)
class _Brand:
    key: str
    store: str
    vendor: str
    items: tuple[_Item, ...]


_BRANDS: dict[str, _Brand] = {
    "AuraSleep": _Brand(
        "AuraSleep",
        "aurasleep-demo",
        "AuraSleep",
        (
            _Item(
                "CloudSupport Orthopedic Pillow",
                "Pillow",
                79,
                (("Firmness", ("Soft", "Medium", "Firm")),),
                "Memory foam pillow that keeps the neck aligned through the night.",
            ),
            _Item(
                "LumbarRelief Seat Cushion",
                "Cushion",
                59,
                (("Color", ("Charcoal", "Sand")),),
                "Ergonomic seat cushion that relieves lower-back pressure at the desk.",
            ),
            _Item(
                "DeepRest Mattress Topper",
                "Topper",
                189,
                (("Size", ("Twin", "Queen", "King")),),
                "Cooling gel topper that adds pressure relief to any mattress.",
            ),
            _Item(
                "PosturePro Back Brace",
                "Brace",
                69,
                (("Size", ("S/M", "L/XL")),),
                "Breathable back brace for daily posture support.",
            ),
            _Item(
                "KneeEase Leg Pillow",
                "Pillow",
                45,
                (("Color", ("White", "Grey")),),
                "Contoured leg pillow for side sleepers.",
            ),
            _Item(
                "TravelNeck Memory Pillow",
                "Pillow",
                39,
                (("Color", ("Navy", "Grey")),),
                "Compact neck pillow that packs into its own pouch.",
            ),
            _Item(
                "WarmRelief Heating Wrap",
                "Wrap",
                55,
                (("Size", ("Standard", "Large")),),
                "Microwavable heating wrap for sore shoulders and back.",
            ),
            _Item(
                "SleepWell Weighted Blanket",
                "Blanket",
                129,
                (("Weight", ("12 lb", "15 lb", "20 lb")),),
                "Evenly weighted blanket designed to calm restless sleep.",
            ),
        ),
    ),
    "OaklineHome": _Brand(
        "OaklineHome",
        "oakline-demo",
        "Oakline Home",
        (
            _Item(
                "Haven Standing Desk",
                "Desk",
                899,
                (("Finish", ("Walnut", "Oak")), ("Width", ("48in", "60in"))),
                "Solid wood standing desk with a quiet dual-motor frame.",
            ),
            _Item(
                "Arc Floor Lamp",
                "Lamp",
                249,
                (("Color", ("Brass", "Black")),),
                "Arched floor lamp with a dimmable warm glow.",
            ),
            _Item(
                "Terra Oak Bookshelf",
                "Shelf",
                459,
                (("Height", ("5ft", "6ft")),),
                "Open oak bookshelf with adjustable shelves.",
            ),
            _Item(
                "Nest Lounge Chair",
                "Chair",
                649,
                (("Fabric", ("Linen", "Boucle", "Velvet")),),
                "Low-profile lounge chair built around a hardwood frame.",
            ),
            _Item(
                "Loft Console Table",
                "Table",
                379,
                (("Finish", ("Natural", "Espresso")),),
                "Slim console table for entryways and hallways.",
            ),
            _Item(
                "Pebble Side Table",
                "Table",
                189,
                (("Color", ("Sand", "Slate")),),
                "Rounded side table that tucks beside any sofa.",
            ),
            _Item(
                "Halo Pendant Light",
                "Lamp",
                159,
                (("Finish", ("Brass", "Matte Black")),),
                "Ring pendant light for dining and kitchen spaces.",
            ),
            _Item(
                "Plank Dining Bench",
                "Bench",
                329,
                (("Length", ("48in", "60in")),),
                "Solid wood bench that seats three comfortably.",
            ),
        ),
    ),
    "LumiSkin": _Brand(
        "LumiSkin",
        "lumiskin-demo",
        "LumiSkin",
        (
            _Item(
                "Dew Drop Hyaluronic Serum",
                "Serum",
                34,
                (("Size", ("30ml", "50ml")),),
                "Lightweight hydrating serum with three weights of hyaluronic acid.",
            ),
            _Item(
                "Bright Day Vitamin C Cream",
                "Moisturizer",
                42,
                (("Size", ("50ml",)),),
                "Daily moisturizer that brightens uneven tone.",
            ),
            _Item(
                "Gentle Cloud Cleanser",
                "Cleanser",
                24,
                (("Size", ("100ml", "200ml")),),
                "Soft foaming cleanser for sensitive skin.",
            ),
            _Item(
                "Night Repair Retinol Oil",
                "Oil",
                48,
                (("Strength", ("0.3%", "0.5%")),),
                "Overnight oil that smooths fine lines.",
            ),
            _Item(
                "SunVeil SPF 50 Fluid",
                "Sunscreen",
                29,
                (("Size", ("50ml",)),),
                "Invisible daily sunscreen with no white cast.",
            ),
            _Item(
                "Calm Barrier Cream",
                "Moisturizer",
                38,
                (("Size", ("50ml", "100ml")),),
                "Ceramide cream that restores the skin barrier.",
            ),
            _Item(
                "Clear Start Clay Mask",
                "Mask",
                27,
                (("Size", ("75ml",)),),
                "Weekly clay mask that clears pores without drying.",
            ),
            _Item(
                "Glow Mist Toner",
                "Toner",
                22,
                (("Size", ("100ml",)),),
                "Alcohol-free toner mist for instant freshness.",
            ),
        ),
    ),
}


def _rng(*parts: object) -> random.Random:
    return random.Random(":".join(str(part) for part in parts))


def _money(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def _brand(definition: DataSourceDefinition) -> _Brand:
    key = str(definition.metadata.get("brand") or "")
    brand = _BRANDS.get(key)
    if brand is None:
        raise SourceReadError("INVALID_CONFIGURATION", f"Unknown mock brand: {key!r}")
    return brand


def _seed(definition: DataSourceDefinition) -> int:
    return int(definition.metadata.get("mock_seed", DEFAULT_SEED))


def _sku(brand: _Brand, item_index: int, variant_index: int) -> str:
    return f"{brand.key[:2].upper()}-{item_index + 1:02d}{variant_index + 1:02d}"


def _packshot_url(definition: DataSourceDefinition, brand: _Brand, handle: str) -> str | None:
    """Return a fetchable packshot URL when the source lists one for this product."""
    base_url = str(definition.metadata.get("packshot_base_url") or "").rstrip("/")
    if not base_url or handle not in definition.metadata.get("packshots", ()):
        return None
    return f"{base_url}/{brand.key}/{handle}.png"


def _raw_product(
    brand: _Brand, item_index: int, seed: int, packshot_url: str | None = None
) -> dict[str, Any]:
    item = brand.items[item_index]
    rng = _rng(seed, brand.key, "product", item_index)
    product_id = str(9_000_000 + item_index)
    handle = _slug(item.title)
    combos: list[tuple[str, ...]] = [()]
    for _, values in item.options:
        combos = [(*combo, value) for combo in combos for value in values]
    variants, images = [], []
    for position, combo in enumerate(combos, 1):
        variant_id = f"{product_id}{position:02d}"
        image_id = f"{product_id}9{position:02d}"
        price = item.price + (position - 1) * max(1, round(item.price * 0.04))
        variants.append(
            {
                "id": variant_id,
                "sku": _sku(brand, item_index, position - 1),
                "title": " / ".join(combo),
                "price": f"{price}.00",
                "compare_at_price": f"{round(price * 1.2)}.00" if rng.random() < 0.4 else None,
                "position": position,
                "image_id": image_id,
                **{f"option{idx}": value for idx, value in enumerate(combo, 1)},
            }
        )
        images.append(
            {
                "id": image_id,
                "src": packshot_url or f"mock://{brand.key}/{handle}/{position}.png",
                "position": position,
                "alt": f"{item.title} {' '.join(combo)}".strip(),
                "width": 1600,
                "height": 1600,
                "variant_ids": [variant_id],
            }
        )
    return {
        "id": product_id,
        "handle": handle,
        "title": item.title,
        "body_html": f"<p>{item.blurb}</p>",
        "status": "active",
        "tags": f"{brand.key}, {item.product_type.lower()}",
        "product_type": item.product_type,
        "vendor": brand.vendor,
        "variants": variants,
        "images": images,
        "options": [
            {"name": name, "position": index, "values": list(values)}
            for index, (name, values) in enumerate(item.options, 1)
        ],
        "created_at": "2026-01-15T09:00:00Z",
        "updated_at": "2026-09-01T09:00:00Z",
        "published_at": "2026-01-20T09:00:00Z",
    }


def _product_record(
    definition: DataSourceDefinition, brand: _Brand, item_index: int, seed: int
) -> NormalizedRecord:
    packshot_url = _packshot_url(definition, brand, _slug(brand.items[item_index].title))
    return _shopify_product(
        _raw_product(brand, item_index, seed, packshot_url),
        "USD",
        brand=brand.key,
        store_id=brand.store,
        metafields=(),
    )


@dataclass(frozen=True)
class _AdSeries:
    ad_id: str
    ad_name: str
    sku: str
    campaign_id: str
    campaign_name: str
    spend: float
    impressions: int
    clicks: int
    purchases: int
    add_to_cart: int
    revenue: float
    ctr_first: float
    ctr_last: float


def _simulate_ad(
    brand: _Brand, item_index: int, ad_index: int, seed: int, end: date, days: int
) -> _AdSeries | None:
    story = _STORY_BY_INDEX[item_index % len(_STORY_BY_INDEX)]
    if story == "new":
        return None
    item = brand.items[item_index]
    rng = _rng(seed, brand.key, "ad", item_index, ad_index)
    scale = {"fatigued": 1.0, "winner": 0.8, "weak": 0.7}.get(story, 0.5)
    ctr0 = {"fatigued": 0.021, "winner": 0.017, "weak": 0.009}[story] * rng.uniform(0.9, 1.1)
    half_life = {"fatigued": 70.0, "winner": 400.0, "weak": 150.0}[story]
    cvr = {"fatigued": 0.032, "winner": 0.036, "weak": 0.012}[story] * rng.uniform(0.9, 1.1)
    base_impressions = (4000 + item.price * 6) * scale
    spend = clicks = impressions = purchases = atc = 0.0
    revenue = 0.0
    ctr_head: list[float] = []
    ctr_tail: list[float] = []
    for offset in range(days):
        day = end - timedelta(days=days - 1 - offset)
        weekday = 1.0 + (0.12 if day.weekday() >= 5 else 0.0)
        sale = 1.35 if date(2026, 9, 5) <= day <= date(2026, 9, 8) else 1.0
        impr = base_impressions * weekday * sale * rng.uniform(0.85, 1.15)
        ctr = ctr0 * (0.5 ** (offset / half_life)) * rng.uniform(0.92, 1.08)
        click = impr * ctr
        buy = (
            click
            * cvr
            * rng.uniform(0.8, 1.2)
            * (0.97 if story == "fatigued" and offset > 45 else 1.0)
        )
        cpc = (0.55 + item.price * 0.0007) * rng.uniform(0.9, 1.1)
        impressions += impr
        clicks += click
        purchases += buy
        atc += click * cvr * 3.1
        spend += click * cpc
        revenue += buy * item.price * rng.uniform(0.95, 1.1)
        if offset < 14:
            ctr_head.append(ctr)
        if offset >= days - 14:
            ctr_tail.append(ctr)
    return _AdSeries(
        ad_id=f"{brand.key[:3].lower()}-ad-{item_index + 1:02d}{ad_index + 1}",
        ad_name=f"{item.title} | {('Static', 'UGC', 'Offer')[ad_index % 3]} | {_sku(brand, item_index, 0)}",
        sku=_sku(brand, item_index, 0),
        campaign_id=f"{brand.key[:3].lower()}-cmp-{item_index + 1:02d}",
        campaign_name=f"{brand.vendor} | Prospecting | {item.product_type}",
        spend=spend,
        impressions=round(impressions),
        clicks=round(clicks),
        purchases=round(purchases),
        add_to_cart=round(atc),
        revenue=revenue,
        ctr_first=sum(ctr_head) / len(ctr_head),
        ctr_last=sum(ctr_tail) / len(ctr_tail),
    )


def _window(definition: DataSourceDefinition) -> tuple[date, int]:
    for resource in definition.resources:
        end_text, start_text = resource.get("end_date"), resource.get("start_date")
        if end_text and start_text:
            end, start = date.fromisoformat(end_text), date.fromisoformat(start_text)
            return end, (end - start).days + 1
    return DEFAULT_END_DATE, DEFAULT_DAYS


def _ads(definition: DataSourceDefinition) -> list[_AdSeries]:
    brand, seed = _brand(definition), _seed(definition)
    end, days = _window(definition)
    series = (
        _simulate_ad(brand, item_index, ad_index, seed, end, days)
        for item_index in range(len(brand.items))
        for ad_index in range(1 + (item_index + seed) % 3)
    )
    return [item for item in series if item is not None]


def _meta_records(definition: DataSourceDefinition) -> tuple[NormalizedRecord, ...]:
    account = str(definition.metadata.get("ad_account_id") or f"act_{_brand(definition).key}")
    records = []
    for ad in _ads(definition):
        records.append(
            NormalizedRecord(
                "ad_performance",
                ad.ad_id,
                {
                    "ad_account_id": account,
                    "campaign_id": ad.campaign_id,
                    "campaign_name": ad.campaign_name,
                    "adset_id": f"{ad.campaign_id}-set",
                    "adset_name": "Broad US 25-54",
                    "ad_id": ad.ad_id,
                    "ad_name": ad.ad_name,
                    "spend": _money(ad.spend),
                    "impressions": str(ad.impressions),
                    "clicks": str(ad.clicks),
                    "cpc": _money(ad.spend / max(ad.clicks, 1)),
                    "cpm": _money(ad.spend / max(ad.impressions, 1) * 1000),
                    "ctr": f"{ad.clicks / max(ad.impressions, 1) * 100:.4f}",
                    "purchases": str(ad.purchases),
                    "add_to_cart": str(ad.add_to_cart),
                    "purchase_conversion_value": _money(ad.revenue),
                    "purchase_roas": f"{ad.revenue / max(ad.spend, 0.01):.4f}",
                    "ctr_first_14d": f"{ad.ctr_first * 100:.4f}",
                    "ctr_last_14d": f"{ad.ctr_last * 100:.4f}",
                },
            )
        )
    return tuple(records)


def _google_ads_records(definition: DataSourceDefinition) -> tuple[NormalizedRecord, ...]:
    customer = str(definition.metadata.get("customer_id") or "0000000000")
    records = []
    for ad in _ads(definition):
        records.append(
            NormalizedRecord(
                "product_performance",
                f"{customer}:{ad.sku}:{ad.campaign_id}:{ad.campaign_id}-grp",
                {
                    "customer_id": customer,
                    "sku": ad.sku,
                    "campaign_id": ad.campaign_id,
                    "campaign_name": ad.campaign_name,
                    "ad_group_id": f"{ad.campaign_id}-grp",
                    "ad_group_name": "Shopping",
                    "impressions": str(round(ad.impressions * 0.6)),
                    "clicks": str(round(ad.clicks * 0.6)),
                    "cost_micros": str(round(ad.spend * 0.6 * 1_000_000)),
                    "cost": _money(ad.spend * 0.6),
                    "conversions": f"{ad.purchases * 0.6:.2f}",
                    "conversion_value": _money(ad.revenue * 0.6),
                },
            )
        )
    return tuple(records)


class MockDataConnector:
    """Serves synthetic Shopify, Meta Ads and Google Ads data for ``mock`` sources."""

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        provider = definition.provider
        if provider is DataSourceProvider.SHOPIFY:
            brand, seed = _brand(definition), _seed(definition)
            records = tuple(
                _product_record(definition, brand, index, seed) for index in range(len(brand.items))
            )
        elif provider is DataSourceProvider.META_ADS:
            records = _meta_records(definition)
        elif provider is DataSourceProvider.GOOGLE_ADS:
            records = _google_ads_records(definition)
        else:
            raise SourceReadError(
                "INVALID_CONFIGURATION", f"No mock data for provider {provider.value}"
            )
        return records, {"mock": True, "seed": _seed(definition), "record_count": len(records)}

    async def fetch_product(
        self, definition: DataSourceDefinition, product_id: str
    ) -> tuple[NormalizedRecord, dict[str, Any]]:
        brand, seed = _brand(definition), _seed(definition)
        for index in range(len(brand.items)):
            record = _product_record(definition, brand, index, seed)
            if record.provider_id == product_id:
                return record, {"mock": True, "seed": seed}
        raise SourceReadError("NOT_FOUND", f"Mock product {product_id} does not exist")


class MockAwareConnector:
    """Routes ``mock`` sources to the mock connector and everything else to the real one."""

    def __init__(self, real: IDataSourceConnector, mock: MockDataConnector) -> None:
        self._real = real
        self._mock = mock

    @staticmethod
    def _is_mock(definition: DataSourceDefinition) -> bool:
        return definition.metadata.get("mock") is True

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        target = self._mock if self._is_mock(definition) else self._real
        return await target.fetch(definition)

    def __getattr__(self, name: str) -> Any:
        if name == "fetch_product":
            real_fetch = getattr(self._real, "fetch_product", None)

            async def fetch_product(definition: DataSourceDefinition, product_id: str) -> Any:
                if self._is_mock(definition):
                    return await self._mock.fetch_product(definition, product_id)
                if real_fetch is None:
                    raise SourceReadError(
                        "INVALID_CONFIGURATION", "Connector cannot refresh one product"
                    )
                return await real_fetch(definition, product_id)

            return fetch_product
        return getattr(self._real, name)


__all__ = ["MockAwareConnector", "MockDataConnector"]
