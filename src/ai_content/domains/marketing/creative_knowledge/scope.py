"""Deterministic scope helpers for reusable Creative knowledge."""

import re


def canonical_brand_id(value: str | None) -> str | None:
    """Return the stable internal Brand identity for a display name."""

    return _scoped_id("brand", value)


def canonical_niche_id(value: str | None) -> str | None:
    """Return the stable niche identity for a product type or niche label."""

    return _scoped_id("niche", value)


def product_niche(*, product_type: str | None) -> str | None:
    """Return the niche of a product family from its catalog product type."""

    return canonical_niche_id(product_type)


def product_archetype(*, product_type: str | None) -> str | None:
    """Return a stable cross-SKU category from the catalog product type."""

    return _slug(product_type or "") or None


def _scoped_id(prefix: str, value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if raw.casefold().startswith(f"{prefix}:"):
        raw = raw.split(":", 1)[1]
    slug = _slug(raw)
    return f"{prefix}:{slug}" if slug else None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
