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
from .mock_store import build_store

DEFAULT_SEED = 20260930
DEFAULT_END_DATE = date(2026, 9, 30)
DEFAULT_DAYS = 90
DEFAULT_CUSTOMERS = 600
_STORY_BY_INDEX = ("fatigued", "winner", "new", "weak")


@dataclass(frozen=True)
class _Item:
    title: str
    product_type: str
    price: int
    options: tuple[tuple[str, tuple[str, ...]], ...]
    blurb: str
    details: tuple[str, ...]


@dataclass(frozen=True)
class _Brand:
    key: str
    store: str
    vendor: str
    guideline: dict[str, Any]
    items: tuple[_Item, ...]


_BRANDS: dict[str, _Brand] = {
    "AuraSleep": _Brand(
        "AuraSleep",
        "aurasleep-demo",
        "AuraSleep",
        {
            "content": (
                "AuraSleep helps desk workers and side sleepers wake up without neck or back "
                "pain. Voice: calm, warm, reassuring; never clinical or alarmist."
            ),
            "colors": ["cloud white", "light grey", "muted dusk blue"],
            "photography": (
                "Soft morning light in a tidy, minimal bedroom; natural linen textures; "
                "real people resting comfortably, never posed as patients."
            ),
            "production_rules": [
                "Show the product in use within the first seconds.",
                "Keep the product shape and knit texture exactly as in the packshot.",
            ],
            "banned_claims": ["cures pain", "medical device", "doctor recommended"],
        },
        (
            _Item(
                "CloudSupport Orthopedic Pillow",
                "Pillow",
                79,
                (("Firmness", ("Soft", "Medium", "Firm")),),
                "Contoured memory foam pillow that keeps the neck aligned through the night.",
                (
                    "Butterfly contour cradles the head for back and side sleeping",
                    "Slow-rebound memory foam with a breathable light-grey knit cover",
                    "Removable, machine-washable cover",
                    "100-night trial",
                ),
            ),
            _Item(
                "SleepWell Weighted Blanket",
                "Blanket",
                129,
                (("Weight", ("12 lb", "15 lb", "20 lb")),),
                "Evenly weighted blanket with a cooling cover for calmer, deeper sleep.",
                (
                    "Glass micro-beads stitched in small pockets so weight never shifts",
                    "Breathable dusk-blue cotton cover",
                    "Sizes for one sleeper or a queen bed",
                ),
            ),
            _Item(
                "Dusk Cooling Sheet Set",
                "Sheets",
                119,
                (("Size", ("Queen", "King")), ("Color", ("Cloud White", "Dusk Blue"))),
                "Breathable percale sheets that stay cool through warm nights.",
                (
                    "Long-staple cotton percale, 300 thread count",
                    "Deep pockets fit mattresses up to 16 inches",
                    "Gets softer with every wash",
                ),
            ),
            _Item(
                "Hush Silk Sleep Mask",
                "Accessory",
                28,
                (("Color", ("Dusk Blue", "Light Grey")),),
                "Lightweight mulberry silk mask that blocks light without pressure.",
                (
                    "Grade 6A mulberry silk, gentle on skin and lashes",
                    "Adjustable strap with no pressure on the eyes",
                    "Travel pouch included",
                ),
            ),
        ),
    ),
    "OaklineHome": _Brand(
        "OaklineHome",
        "oakline-demo",
        "Oakline Home",
        {
            "content": (
                "Oakline Home makes solid-wood furniture for small, bright homes. Voice: "
                "confident, understated, crafted; focus on materials and everyday use."
            ),
            "colors": ["walnut", "natural oak", "matte black", "warm white"],
            "photography": (
                "Daylight interiors with uncluttered Scandinavian styling, a single plant "
                "or book as props, eye-level or three-quarter angles."
            ),
            "production_rules": [
                "Show real wood grain clearly.",
                "Keep proportions and finish exactly as in the packshot.",
            ],
            "banned_claims": ["lifetime guarantee", "cheapest"],
        },
        (
            _Item(
                "Haven Standing Desk",
                "Desk",
                899,
                (("Finish", ("Walnut", "Oak")), ("Width", ("48in", "60in"))),
                "Solid wood standing desk with a whisper-quiet dual-motor frame.",
                (
                    "Solid walnut or oak top with hand-finished edges",
                    "Dual motors lift from 25in to 50in in about 20 seconds",
                    "Four height presets on a slim keypad",
                ),
            ),
            _Item(
                "Nest Lounge Chair",
                "Chair",
                649,
                (("Fabric", ("Linen", "Boucle")),),
                "Low-profile lounge chair built around a solid oak frame.",
                (
                    "Solid oak frame with rounded arms",
                    "Deep seat with high-resilience foam",
                    "Removable linen or boucle cover",
                ),
            ),
            _Item(
                "Grove Open Bookshelf",
                "Shelving",
                479,
                (("Finish", ("Walnut", "Oak")),),
                "Five-tier solid wood bookshelf with an open back for airy rooms.",
                (
                    "Solid wood shelves with visible grain",
                    "Matte black steel frame",
                    "Anti-tip wall anchor included",
                ),
            ),
            _Item(
                "Terra Side Table",
                "Table",
                189,
                (("Finish", ("Walnut", "Oak")),),
                "Compact round side table with a hand-sanded solid wood top.",
                (
                    "Solid wood top, hand-sanded and oiled",
                    "Tapered legs in matching wood",
                    "Fits beside a sofa or bed",
                ),
            ),
        ),
    ),
    "LumiSkin": _Brand(
        "LumiSkin",
        "lumiskin-demo",
        "LumiSkin",
        {
            "content": (
                "LumiSkin makes minimal skincare for sensitive skin. Voice: fresh, honest, "
                "gentle; describe how skin feels, never promise results."
            ),
            "colors": ["white", "blush pink", "pale aqua"],
            "photography": (
                "Bright diffused light, glass and water textures, dewy natural skin with "
                "visible texture; no heavy retouching."
            ),
            "production_rules": [
                "Keep the frosted bottle and white dropper exactly as in the packshot.",
            ],
            "banned_claims": ["anti-aging guaranteed", "clinically proven", "removes wrinkles"],
        },
        (
            _Item(
                "Dew Drop Hyaluronic Serum",
                "Serum",
                34,
                (("Size", ("30ml", "50ml")),),
                "Lightweight hydrating serum with three weights of hyaluronic acid.",
                (
                    "Three molecular weights of hyaluronic acid",
                    "Fragrance-free, suitable for sensitive skin",
                    "Frosted glass bottle with a white dropper",
                ),
            ),
            _Item(
                "SunVeil SPF 50 Fluid",
                "Sunscreen",
                29,
                (("Size", ("50ml",)),),
                "Invisible daily sunscreen fluid with no white cast.",
                (
                    "Broad-spectrum SPF 50",
                    "Sheer fluid texture that disappears on all skin tones",
                    "Works under makeup",
                ),
            ),
            _Item(
                "Cloud Gel Cleanser",
                "Cleanser",
                22,
                (("Size", ("150ml", "250ml")),),
                "Soft-foaming gel cleanser that rinses clean without tightness.",
                (
                    "Amino-acid cleansing base",
                    "Fragrance-free, pH balanced for sensitive skin",
                    "Pump bottle in frosted white",
                ),
            ),
            _Item(
                "Night Bloom Barrier Cream",
                "Moisturizer",
                38,
                (("Size", ("50ml",)),),
                "Rich overnight cream that cushions the skin barrier while you sleep.",
                (
                    "Ceramides and squalane in a velvety texture",
                    "Fragrance-free, non-greasy finish",
                    "Airless pump keeps the formula fresh",
                ),
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
    bullets = "".join(f"<li>{line}</li>" for line in item.details)
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
        "body_html": f"<p>{item.blurb}</p><ul>{bullets}</ul>",
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


def _store_records(definition: DataSourceDefinition) -> tuple[NormalizedRecord, ...]:
    brand, seed = _brand(definition), _seed(definition)
    products = [_raw_product(brand, index, seed) for index in range(len(brand.items))]
    campaigns = {
        int(product["id"]): f"{brand.key[:3].lower()}-cmp-{index + 1:02d}"
        for index, product in enumerate(products)
        if _STORY_BY_INDEX[index % len(_STORY_BY_INDEX)] != "new"
    }
    return build_store(
        brand_key=brand.key,
        products=products,
        campaigns=campaigns,
        seed=seed,
        end=_window(definition)[0],
        customer_count=int(definition.metadata.get("mock_customers", DEFAULT_CUSTOMERS)),
    )


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
            records = (
                *(
                    _product_record(definition, brand, index, seed)
                    for index in range(len(brand.items))
                ),
                NormalizedRecord(
                    "brand_guideline",
                    f"{brand.store}-guideline",
                    {"brand": brand.key, **brand.guideline},
                ),
                *_store_records(definition),
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
