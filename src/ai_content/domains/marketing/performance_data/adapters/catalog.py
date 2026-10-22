"""Sanitized Shopify catalog reference loaded from a local JSON fixture."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from ..domain.models import CatalogProduct


class JsonProductCatalog:
    """Resolve explicit GMC-to-Shopify mappings; never match by product title."""

    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Product catalog fixture must be a JSON list")
        products = []
        for item in data:
            products.append(
                CatalogProduct(
                    gmc_product_id=str(item["gmc_product_id"]),
                    canonical_product_id=str(item["canonical_product_id"]),
                    shopify_sku=str(item["shopify_sku"]),
                    price=Decimal(str(item["price"])) if item.get("price") is not None else None,
                    currency=str(item["currency"]) if item.get("currency") else None,
                    availability=(str(item["availability"]) if item.get("availability") else None),
                )
            )
        self._products = tuple(products)

    def find(self, gmc_product_id: str) -> tuple[CatalogProduct, ...]:
        return tuple(
            product for product in self._products if product.gmc_product_id == gmc_product_id
        )
