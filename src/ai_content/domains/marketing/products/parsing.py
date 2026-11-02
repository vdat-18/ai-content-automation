"""Pure parsers for TikTok Shop pages and feed responses."""

from __future__ import annotations

import json
import re
from typing import Any

SOURCE = "tiktok_shop_vn"
_FEED_MARKER = "homepage_desktop/products_by_component"


def is_product_url(url: str) -> bool:
    return "/pdp/" in url


def product_id_from_url(url: str) -> str | None:
    match = re.search(r"/pdp/[^/?]+/(\d+)", url)
    return match.group(1) if match else None


def is_feed_url(url: str) -> bool:
    return _FEED_MARKER in url


def money(value: object, currency: str | None) -> int | None:
    """Return whole VND amounts; other currencies are not stored as integers."""
    if currency != "VND" or value in (None, ""):
        return None
    text = re.sub(r"[.,\s]", "", str(value))
    return int(text) if text.isdigit() else None


_NON_PHYSICAL = re.compile(r"voucher|mã giảm|thẻ quà|e-?gift|nạp (thẻ|tiền)|thẻ cào", re.IGNORECASE)
MIN_REAL_PRICE_VND = 1000


def is_non_physical(title: str | None) -> bool:
    return bool(_NON_PHYSICAL.search(title or ""))


def junk_reason(product: dict[str, Any]) -> str | None:
    """Why a captured product is not worth turning into content, or None."""
    price = product.get("price") or {}
    sale = money(price.get("sale"), price.get("currency"))
    if price.get("currency") != "VND" or sale is None:
        return "not a VND price"
    if sale < MIN_REAL_PRICE_VND:
        return "promo price under 1,000 VND"
    if is_non_physical(product.get("title")):
        return "voucher or non-physical item"
    if not product.get("images"):
        return "no images"
    return None


def _int(value: object) -> int | None:
    if value in (None, ""):
        return None
    text = re.sub(r"[.,\s]", "", str(value))
    return int(text) if text.isdigit() else None


def _extract_object(text: str, marker: str) -> dict[str, Any] | None:
    start = text.find(marker)
    if start < 0:
        return None
    begin = text.index("{", start)
    depth = 0
    in_string = False
    escaped = False
    for index in range(begin, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[begin : index + 1])
                except ValueError:
                    return None
    return None


def _rich_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind in ("ul", "ol"):
            for item in block.get("content", []):
                if isinstance(item, dict):
                    text = item.get("text") or "".join(
                        value.get("text_attribute", {}).get("text", "")
                        for value in item.get("rich_text", {}).get("arguments", {}).values()
                    )
                else:
                    text = str(item)
                parts.append(f"- {text}")
    return "\n".join(part for part in parts if part)


def parse_product_page(html: str, url: str) -> dict[str, Any] | None:
    """Return the normalized product detail embedded in a product page, or None."""
    info = _extract_object(html, '"product_info":{"status":1')
    if not info or not info.get("product_id"):
        return None
    ratings = _extract_object(html, '"review_ratings":{') or {}
    shop = _extract_object(html, '"shop_info":{') or {}
    price = info.get("price") or {}
    seller = info.get("seller") or {}
    review = info.get("review") or {}
    logistic = info.get("logistic") or {}
    return {
        "source": SOURCE,
        "url": url,
        "product_id": str(info["product_id"]),
        "title": info.get("title"),
        "seller": {
            "id": info.get("seller_id"),
            "name": seller.get("name"),
            "rating": seller.get("rating_value"),
            "product_count": seller.get("product_count"),
        },
        "price": {
            "sale": price.get("min_sku_price"),
            "original": price.get("min_sku_original_price"),
            "discount": price.get("discount"),
            "currency": price.get("currency"),
        },
        "sold_count": info.get("sold_count"),
        "rating": review.get("product_rating"),
        "review_count": review.get("review_count"),
        "rating_distribution": ratings.get("rating_result"),
        "images": [(image.get("url_list") or [None])[0] for image in info.get("images", [])],
        "variants": [
            {
                "sku_id": sku.get("sku_id"),
                "variant": ", ".join(
                    prop.get("prop_value", "") for prop in sku.get("sku_sale_props", [])
                ),
                "stock": sku.get("stock"),
                "price": (sku.get("price") or {}).get("sale_price_decimal"),
                "original_price": (sku.get("price") or {}).get("origin_price_decimal"),
                "status": sku.get("status"),
            }
            for sku in info.get("skus", [])
        ],
        "specifications": {spec["name"]: spec["value"] for spec in info.get("specifications", [])},
        "description": _rich_text(info.get("desc_blocks", [])),
        "shipping": {
            key: logistic.get(key)
            for key in ("free_shipping", "delivery_name", "delivery_min_days", "delivery_max_days")
        },
        "categories": list(dict.fromkeys(re.findall(r'"category_name":"([^"]+)"', html))),
        "shop": shop,
        "raw_product_info": info,
    }


def parse_feed_payload(body: str) -> list[dict[str, Any]]:
    """Return Vietnamese market products listed in a feed response."""
    try:
        data = (json.loads(body) or {}).get("data") or {}
    except ValueError:
        return []
    found = list(data.get("productList") or [])
    for component in data.get("components_map") or []:
        found += (component.get("component_data") or {}).get("products", [])
    items: list[dict[str, Any]] = []
    for product in found:
        price = product.get("product_price_info") or {}
        if price.get("currency_name") != "VND" or not product.get("product_id"):
            continue
        video = product.get("bind_video") or {}
        items.append(
            {
                "product_id": str(product["product_id"]),
                "title": product.get("title"),
                "image": ((product.get("image") or {}).get("url_list") or [None])[0],
                "sale_price": price.get("sale_price_decimal"),
                "original_price": price.get("origin_price_decimal"),
                "discount": price.get("discount_format"),
                "currency": price.get("currency_name"),
                "rating": (product.get("rate_info") or {}).get("score"),
                "review_count": (product.get("rate_info") or {}).get("review_count"),
                "sold_count": (product.get("sold_info") or {}).get("sold_count"),
                "seller_id": (product.get("seller_info") or {}).get("seller_id"),
                "shop_name": (product.get("seller_info") or {}).get("shop_name"),
                "url": (product.get("seo_url") or {}).get("canonical_url"),
                "has_video": bool(video),
            }
        )
    return items


__all__ = [
    "SOURCE",
    "is_feed_url",
    "is_non_physical",
    "is_product_url",
    "junk_reason",
    "money",
    "parse_feed_payload",
    "parse_product_page",
    "product_id_from_url",
]
