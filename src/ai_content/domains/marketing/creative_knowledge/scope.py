"""Deterministic scope helpers for reusable Creative knowledge."""

import re

_BRAND_ALIASES = {
    "demofurn": "demofurn",
    "demofurniture": "demofurn",
    "demohome": "demohome",
}

_FURNITURE_ARCHETYPES = {
    "bed",
    "bedside_storage",
    "coffee_table",
    "console_table",
    "desk",
    "dining_table",
    "display_storage",
    "drawer_storage",
    "entryway_storage",
    "media_storage",
    "record_storage",
    "seating",
    "side_table",
    "wine_storage",
}

_ARCHETYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("media_storage", ("tv stand", "media console", "entertainment center")),
    ("record_storage", ("record player stand", "vinyl stand", "record stand")),
    ("wine_storage", ("wine rack", "wine cabinet", "wine holder")),
    ("bedside_storage", ("nightstand", "bedside table")),
    ("entryway_storage", ("shoe cabinet", "entryway cabinet", "hall tree")),
    ("display_storage", ("bookcase", "bookshelf", "display cabinet")),
    ("drawer_storage", ("dresser", "chest of drawers")),
    ("coffee_table", ("coffee table",)),
    ("console_table", ("console table", "sofa table")),
    ("side_table", ("side table", "end table", "accent table")),
    ("dining_table", ("dining table",)),
    ("desk", ("writing desk", "computer desk", "executive desk", "desk")),
    ("seating", ("chair", "stool", "bench", "sofa", "loveseat")),
    ("bed", ("bed frame", "platform bed", "headboard")),
    ("wall_art", ("wall art", "wall decor", "canvas art")),
    ("lighting", ("lamp", "lighting", "sconce", "chandelier")),
)


def canonical_brand_id(value: str | None) -> str | None:
    """Return the stable internal Brand identity for a known display alias."""

    if value is None or not value.strip():
        return None
    raw = value.strip()
    if raw.casefold().startswith("brand:"):
        raw = raw.split(":", 1)[1]
    alias_key = re.sub(r"[^a-z0-9]+", "", raw.casefold())
    canonical = _BRAND_ALIASES.get(alias_key, _slug(raw))
    return f"brand:{canonical}" if canonical else None


def canonical_niche_id(value: str | None) -> str | None:
    """Map broad and Shopify-specific product labels to a stable niche identity."""

    if value is None or not value.strip():
        return None
    raw = value.strip()
    if raw.casefold().startswith("niche:"):
        raw = raw.split(":", 1)[1]
    slug = _slug(raw)
    archetype = product_archetype(product_type=raw, title=raw)
    if slug in {"furniture", "home_furniture"} or archetype in _FURNITURE_ARCHETYPES:
        return "niche:furniture"
    return f"niche:{slug}" if slug else None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def product_niche(*, product_type: str | None, title: str) -> str | None:
    """Return a stable niche from the exact Shopify family metadata."""

    archetype = product_archetype(product_type=product_type, title=title)
    if archetype in _FURNITURE_ARCHETYPES:
        return "niche:furniture"
    return canonical_niche_id(product_type)


def product_archetype(*, product_type: str | None, title: str) -> str | None:
    """Return a stable cross-SKU category without inventing product facts."""

    searchable = " ".join(part.strip().casefold() for part in (title, product_type or ""))
    for archetype, phrases in _ARCHETYPE_PATTERNS:
        if any(phrase in searchable for phrase in phrases):
            return archetype
    if not product_type or not product_type.strip():
        return None
    normalized = _slug(product_type)
    return normalized or None
