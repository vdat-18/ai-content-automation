"""Public commerce and inspiration platform detection and normalization."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from .identity import source_record_id
from .models import ResearchCrawlRecord

SUPPORTED_PUBLIC_PLATFORMS = frozenset(
    {"amazon", "etsy", "houzz", "pinterest", "tiktok", "wayfair"}
)
PRODUCT_PLATFORMS = frozenset({"amazon", "etsy", "houzz", "wayfair"})
DETAIL_PLATFORMS = frozenset({*PRODUCT_PLATFORMS, "tiktok"})

_HOST_PLATFORMS = {
    "amazon.com": "amazon",
    "etsy.com": "etsy",
    "houzz.com": "houzz",
    "pinterest.com": "pinterest",
    "tiktok.com": "tiktok",
    "wayfair.com": "wayfair",
}

_RECORD_TYPES = {
    "amazon": "product",
    "etsy": "product",
    "houzz": "product",
    "pinterest": "pin",
    "tiktok": "creative",
    "wayfair": "product",
}

# The browser script intentionally relies on stable URL shapes before broad card selectors.
# Site-specific adapters can tighten these selectors without changing persistence contracts.
PUBLIC_PLATFORM_RECORDS_SCRIPT = r"""() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const absolute = (value) => {
    try { return new URL(value, location.href).href; } catch (_) { return ''; }
  };
  const srcsetUrls = (image) => (image.getAttribute('srcset') || '')
    .split(',').map((part) => absolute(part.trim().split(/\s+/)[0])).filter(Boolean);
  const imageUrls = (image) => [
    ...srcsetUrls(image), image.currentSrc || image.src,
    image.getAttribute('data-src'), image.getAttribute('data-original'),
    image.getAttribute('data-src-zoom-image')
  ].map(absolute).filter(Boolean);
  const backgroundUrl = (element) => {
    const value = element ? getComputedStyle(element).backgroundImage : '';
    const match = value && value.match(/^url\(["']?(.*?)["']?\)$/);
    return match ? absolute(match[1]) : '';
  };
  const host = location.hostname.replace(/^www\./, '').toLowerCase();
  const directItem = (host.endsWith('pinterest.com') && /^\/pin\/[^/]+/.test(location.pathname)) ||
    (host.endsWith('etsy.com') && /^\/listing\/[^/]+/.test(location.pathname)) ||
    (host.endsWith('amazon.com') && /\/(dp|gp\/product)\/[^/]+/.test(location.pathname)) ||
    (host.endsWith('wayfair.com') && /\/pdp\//.test(location.pathname)) ||
    (host.endsWith('houzz.com') && /\/products\/[^/]+-prvw-vr~[0-9]+/.test(location.pathname)) ||
    (host.endsWith('tiktok.com') && /\/topads\/[0-9]+/.test(location.pathname));
  const rules = host.endsWith('pinterest.com')
    ? {links: ['a[href*="/pin/"]'], cards: ['[data-test-id="pin"]', '[data-grid-item]', 'article']}
    : host.endsWith('etsy.com')
    ? {links: ['a[href*="/listing/"]'], cards: ['[data-listing-id]', '.v2-listing-card', 'li']}
    : host.endsWith('amazon.com')
    ? {links: ['a[href*="/dp/"]', 'a[href*="/gp/product/"]'], cards: ['[data-asin]', '[data-component-type="s-search-result"]']}
    : host.endsWith('wayfair.com')
    ? {links: ['a[href*="/pdp/"]', 'a[href*="-pdp-"]'], cards: ['[data-enzyme-id="BrowseProductCard"]', '[data-testid*="product"]', 'article']}
    : host.endsWith('houzz.com')
    ? {links: ['a[href*="/products/"]'], cards: ['[data-compid*="Product"]', '.hz-product-card', 'article']}
    : {links: ['a[href*="/topads/"]'], cards: ['[class*="TopadsVideoCard_card__"]', '[class*="creative-card"]', '[class*="ad-card"]', 'article']};

  const anchors = directItem ? [] : [...document.querySelectorAll(rules.links.join(','))];
  const candidates = [];
  const seen = new Set();
  for (const anchor of anchors) {
    const url = absolute(anchor.href);
    if (!url || seen.has(url)) continue;
    const card = rules.cards.map((selector) => anchor.closest(selector)).find(Boolean) || anchor.parentElement || anchor;
    const text = clean(card.innerText || anchor.innerText);
    const visual = card.querySelector('[class*="cardVideo"]');
    const images = [
      ...[...card.querySelectorAll('img')].flatMap(imageUrls),
      backgroundUrl(visual)
    ].filter(Boolean);
    const videos = [...card.querySelectorAll('video, video source')]
      .map((video) => absolute(video.currentSrc || video.src)).filter(Boolean);
    if (!text && !images.length && !videos.length) continue;
    seen.add(url);
    candidates.push({
      external_id: card.getAttribute('data-listing-id') || card.getAttribute('data-asin') ||
        card.getAttribute('data-id') || card.getAttribute('data-pin-id') ||
        (url.match(/\/(?:pin|listing|topads)\/([0-9]+)/) || [])[1] || null,
      title: clean(card.querySelector('h1,h2,h3,[data-testid*="title"],[class*="title"]')?.innerText || card.innerText || anchor.getAttribute('aria-label') || anchor.innerText),
      text,
      source_url: url,
      links: [...card.querySelectorAll('a[href]')].map((item) => ({text: clean(item.innerText), url: absolute(item.href)})).filter((item) => item.url),
      images: [...new Set(images)],
      videos: [...new Set(videos)],
      price: clean(card.querySelector('[data-price],[class*="price"],.a-price')?.innerText),
      rating: clean(card.querySelector('[aria-label*="star"],[class*="rating"]')?.getAttribute('aria-label') || card.querySelector('[class*="rating"]')?.innerText),
      review_count: clean(card.querySelector('[class*="review"],[aria-label*="review"]')?.innerText)
    });
  }
  if (candidates.length) return candidates;

  const commercePlatform = host.endsWith('etsy.com') || host.endsWith('amazon.com') ||
    host.endsWith('wayfair.com') || host.endsWith('houzz.com');
  if (!directItem && !commercePlatform) {
    const imageRoot = document.querySelector('main,[role="main"]') || document.body;
    const imageCandidates = [...imageRoot.querySelectorAll('img')]
      .map((image) => {
        const sources = imageUrls(image);
        const url = sources.at(-1) || '';
        const container = image.closest('article,[data-grid-item],[role="listitem"]') || image.parentElement;
        return {
          external_id: null,
          title: clean(image.alt),
          text: clean(container?.innerText || image.alt).slice(0, 4000),
          source_url: location.href,
          links: [],
          images: url ? [url] : [],
          videos: [],
          price: '', rating: '', review_count: '',
          width: image.naturalWidth || image.width || Number(image.getAttribute('width')) || 0,
          height: image.naturalHeight || image.height || Number(image.getAttribute('height')) || 0
        };
      })
      .filter((item) => item.images.length && item.width >= 160 && item.height >= 160);
    if (imageCandidates.length) return imageCandidates;
  }

  const root = host.endsWith('amazon.com')
    ? (document.querySelector('#dp-container,#ppd') || document.querySelector('main') || document.body)
    : document.querySelector('main') || document.body;
  const canonical = document.querySelector('link[rel="canonical"]')?.href || location.href;
  const text = clean(root?.innerText);
  const title = clean(document.querySelector('h1')?.innerText || document.title);
  const allImageElements = [...root.querySelectorAll('img')];
  let productImageElements = allImageElements;
  if (directItem && host.endsWith('wayfair.com') && title) {
    const normalizedTitle = title.toLowerCase();
    const matching = allImageElements.filter((image) => clean(image.alt).toLowerCase().includes(normalizedTitle));
    if (matching.length) productImageElements = matching;
  } else if (directItem && host.endsWith('amazon.com')) {
    const matching = [...root.querySelectorAll('#landingImage,#imgTagWrapperId img,#altImages img,[data-a-image-name]')];
    if (matching.length) productImageElements = matching;
  } else if (directItem && host.endsWith('etsy.com')) {
    const matching = [...root.querySelectorAll('[data-carousel-image] img,img[data-src-zoom-image],[data-listing-page-image] img')];
    if (matching.length) productImageElements = matching;
  } else if (directItem && host.endsWith('houzz.com')) {
    const matching = [...root.querySelectorAll('#productGallery img,[class*="ProductGallery"] img,[class*="product-gallery"] img')];
    if (matching.length) productImageElements = matching;
  }
  const images = productImageElements.flatMap(imageUrls);
  const videos = [...root.querySelectorAll('video, video source')]
    .filter((video) => !String(video.className || '').includes('Popup'))
    .map((video) => absolute(video.currentSrc || video.src)).filter((url) =>
      url && !url.includes('creative-factory') && !url.includes('seedance2.0-model-demo')
    );
  if (!text && !images.length && !videos.length) return [];
  return [{
    external_id: host.endsWith('amazon.com')
      ? (document.querySelector('[data-asin]')?.getAttribute('data-asin') || null)
      : ((canonical.match(/\/(?:pin|listing|topads)\/([0-9]+)/) || [])[1] || null),
    title,
    text,
    source_url: canonical,
    links: [...root.querySelectorAll('a[href]')].map((item) => ({text: clean(item.innerText), url: absolute(item.href)})).filter((item) => item.url),
    images: [...new Set(images)],
    videos: [...new Set(videos)],
    price: clean(root.querySelector('.a-price .a-offscreen,[data-price],[class*="price"]')?.innerText),
    rating: clean(root.querySelector('#acrPopover,[aria-label*="star"],[class*="rating"]')?.getAttribute('aria-label') || root.querySelector('[class*="rating"]')?.innerText),
    review_count: clean(root.querySelector('#acrCustomerReviewText,[class*="review"],[aria-label*="review"]')?.innerText)
  }];
}"""


def is_product_detail_url(platform: str, url: str) -> bool:
    """Return whether a supported commerce URL points to one product."""
    if platform not in PRODUCT_PLATFORMS:
        return False
    path = urlsplit(url).path.lower()
    if platform == "amazon":
        return "/dp/" in path or "/gp/product/" in path
    if platform == "etsy":
        return path.startswith("/listing/")
    if platform == "wayfair":
        return "/pdp/" in path or "-pdp-" in path
    return path.startswith("/products/") and "-prvw-vr~" in path


def is_platform_detail_url(platform: str, url: str) -> bool:
    """Return whether a supported platform URL identifies one record."""
    if platform in PRODUCT_PLATFORMS:
        return is_product_detail_url(platform, url)
    if platform == "tiktok":
        return re.search(r"/topads/[0-9]+(?:/|$)", urlsplit(url).path.lower()) is not None
    return False


def public_platform(url: str) -> str | None:
    """Return the supported public platform for a URL."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for suffix, platform in _HOST_PLATFORMS.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return platform
    return None


def normalize_public_platform_records(
    raw_records: list[dict[str, Any]],
    *,
    platform: str,
    page_url: str,
    structured_data: list[Any] | None = None,
    page_metadata: list[dict[str, str]] | None = None,
) -> list[ResearchCrawlRecord]:
    """Normalize visible product, pin, and creative cards from a public page."""
    if platform not in SUPPORTED_PUBLIC_PLATFORMS:
        raise ValueError(f"Unsupported public research platform: {platform}")
    records: list[ResearchCrawlRecord] = []
    seen: set[str] = set()
    for raw in raw_records:
        raw_text = str(raw.get("text") or "")
        text = _clean(raw_text)
        title = _clean(raw.get("title")) or None
        raw_source_url = _url(raw.get("source_url"))
        source_url = raw_source_url or page_url
        if platform == "tiktok" and not is_platform_detail_url(platform, source_url):
            continue
        images = _urls(raw.get("images"))
        videos = _urls(raw.get("videos"))
        links = _links(raw.get("links"))
        if not text and not images and not videos:
            continue
        identifier = (
            _clean(raw.get("external_id"))
            or (
                source_record_id(source_url)
                if raw_source_url and is_platform_detail_url(platform, source_url)
                else ""
            )
            or (source_record_id(images[0]) if len(raw_records) > 1 and images else "")
            or (source_record_id(source_url) if raw_source_url else fallback_record_id(raw))
        )
        if identifier in seen:
            continue
        seen.add(identifier)
        structured = raw.get("structured_data")
        if not isinstance(structured, list):
            structured = (structured_data or []) if len(raw_records) == 1 else []
        meta_tags = raw.get("page_metadata")
        if not isinstance(meta_tags, list):
            meta_tags = (page_metadata or []) if len(raw_records) == 1 else []
        product = _find_product(structured)
        images = _filter_product_images(
            platform,
            images,
            detail=is_product_detail_url(platform, source_url),
        )
        product_images = _product_images(product)
        page_images = _metadata_images(meta_tags)
        images = list(dict.fromkeys([*product_images, *images, *page_images]))
        if platform == "tiktok":
            images = [url for url in images if _is_tiktok_creative_image(url)]
        title = _clean(product.get("name")) or title if product else title
        product_description = _clean(product.get("description")) if product else ""
        if product_description and product_description not in text:
            text = f"{product_description}\n{text}".strip()
        metadata = {
            key: value
            for key in ("price", "rating", "review_count")
            if (value := _clean(raw.get(key)))
        }
        metadata["platform"] = platform
        visible_facts = _visible_product_facts(text, title)
        metadata.update(visible_facts)
        if platform == "tiktok":
            tiktok_facts = _tiktok_facts(raw_text)
            metadata.update(tiktok_facts)
            title = tiktok_facts.get("caption") or title
        elif platform == "pinterest" and not is_platform_detail_url(platform, source_url):
            metadata["detail_status"] = "preview_only"
        if product or is_product_detail_url(platform, source_url):
            product_data = _product_data(product)
            description = _metadata_value(meta_tags, "description", "og:description")
            if description:
                product_data.setdefault("description", description)
            if product_data:
                metadata["product_data"] = product_data
            metadata.setdefault("price", _offer_value(product_data.get("offers"), "price"))
            metadata.setdefault(
                "rating", _nested_value(product_data, "aggregate_rating", "rating_value")
            )
            metadata.setdefault(
                "review_count", _nested_value(product_data, "aggregate_rating", "review_count")
            )
            metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
        if structured:
            metadata["structured_data"] = structured
        if meta_tags:
            metadata["page_metadata"] = meta_tags
        detail_status = _clean(raw.get("detail_status"))
        if detail_status:
            metadata["detail_status"] = detail_status
        elif is_platform_detail_url(platform, page_url) and is_platform_detail_url(
            platform, source_url
        ):
            metadata["detail_status"] = "complete"
        records.append(
            ResearchCrawlRecord(
                record_id=identifier,
                record_type=_RECORD_TYPES[platform],
                title=title,
                text=text,
                source_url=source_url,
                metadata=metadata,
                links=links,
                image_urls=images,
                video_urls=videos,
            )
        )
    return records


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _url(value: object) -> str | None:
    text = str(value or "")
    return text if text.startswith(("http://", "https://")) else None


def _urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(url for item in value if (url := _url(item))))


def _links(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    unique: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict) or not (url := _url(item.get("url"))):
            continue
        unique[url] = {"url": url, "text": _clean(item.get("text"))}
    return list(unique.values())


def _find_product(values: list[Any]) -> dict[str, Any]:
    for value in values:
        found = _find_typed_object(value, "product")
        if found is not None:
            return found
    return {}


def _find_typed_object(value: Any, expected: str) -> dict[str, Any] | None:
    if isinstance(value, list):
        for item in value:
            if found := _find_typed_object(item, expected):
                return found
        return None
    if not isinstance(value, dict):
        return None
    raw_type = value.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    if any(str(item).lower() == expected for item in types):
        return value
    for key in ("@graph", "mainEntity", "itemListElement"):
        if found := _find_typed_object(value.get(key), expected):
            return found
    return None


def _product_images(product: dict[str, Any]) -> list[str]:
    value = product.get("image")
    candidates = value if isinstance(value, list) else [value]
    urls: list[str] = []
    for item in candidates:
        candidate = item.get("url") if isinstance(item, dict) else item
        if url := _url(candidate):
            urls.append(url)
    return list(dict.fromkeys(urls))


def _metadata_images(values: list[Any]) -> list[str]:
    open_graph: list[str] = []
    twitter: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        key = str(item.get("property") or item.get("name") or "").lower()
        if not (url := _url(item.get("content"))):
            continue
        if key == "og:image":
            open_graph.append(url)
        elif key in {"twitter:image", "twitter:image:src"}:
            twitter.append(url)
    return list(dict.fromkeys(open_graph or twitter))


def _filter_product_images(platform: str, images: list[str], *, detail: bool) -> list[str]:
    if platform != "wayfair" or not detail:
        return images
    large: list[str] = []
    for url in images:
        match = re.search(r"/resize-h(\d+)-w(\d+)", url, re.I)
        if match and min(int(match.group(1)), int(match.group(2))) >= 600:
            large.append(url)
    return list(dict.fromkeys(large)) if large else images


def _metadata_value(values: list[Any], *keys: str) -> str:
    expected = {key.lower() for key in keys}
    for item in values:
        if not isinstance(item, dict):
            continue
        key = str(item.get("property") or item.get("name") or "").lower()
        if key in expected:
            return _clean(item.get("content"))
    return ""


def _visible_product_facts(text: str, title: str | None) -> dict[str, str]:
    section = text
    if title and (start := text.find(title)) >= 0:
        section = text[start : start + 3_000]
    facts: dict[str, str] = {}
    if match := re.search(r"\$\s?\d[\d,]*(?:\.\d{2})?", section):
        facts["price"] = match.group(0).replace("$ ", "$")
    if match := re.search(r"Rated\s+([0-5](?:\.\d+)?)\s+out of 5 stars", section, re.I):
        facts["rating"] = match.group(1)
    if match := re.search(r"([\d,]+)\s+(?:Reviews|total votes|ratings?)\b", section, re.I):
        facts["review_count"] = match.group(1)
    return facts


def _tiktok_facts(text: str) -> dict[str, str]:
    labels = {
        "Region": "region",
        "Industry": "industry",
        "Objective": "objective",
        "Brand name": "brand_name",
        "Landing Page": "landing_page",
        "Ad caption": "caption",
        "Likes": "likes",
        "Comments": "comments",
        "Shares": "shares",
        "CTR": "ctr",
        "Budget": "budget",
    }
    normalized = _clean(text)
    marker_pattern = "|".join(
        re.escape(label)
        for label in (
            *labels,
            "Ad performance",
            "Interactive time analysis",
            "Recommended for you",
        )
    )
    facts: dict[str, str] = {}
    for label, key in labels.items():
        match = re.search(
            rf"(?:^|\s){re.escape(label)}\s+(.+?)(?=\s+(?:{marker_pattern})(?:\s|$)|$)",
            normalized,
            re.I,
        )
        if match:
            facts[key] = match.group(1).strip()
    return facts


def _is_tiktok_creative_image(url: str) -> bool:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    return "tiktokcdn.com" in (parsed.hostname or "").lower() and any(
        extension in path for extension in (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")
    )


def _product_data(product: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "aggregateRating": "aggregate_rating",
        "additionalProperty": "additional_properties",
        "productID": "product_id",
        "review": "reviews",
    }
    fields = (
        "name",
        "description",
        "brand",
        "sku",
        "mpn",
        "gtin",
        "gtin8",
        "gtin12",
        "gtin13",
        "gtin14",
        "productID",
        "category",
        "material",
        "color",
        "size",
        "offers",
        "aggregateRating",
        "additionalProperty",
        "review",
    )
    return {
        aliases.get(field, field): product[field]
        for field in fields
        if field in product and product[field] not in (None, "", [], {})
    }


def _offer_value(offers: object, key: str) -> object:
    if isinstance(offers, list):
        return next((_offer_value(item, key) for item in offers if _offer_value(item, key)), None)
    return offers.get(key) if isinstance(offers, dict) else None


def _nested_value(value: dict[str, Any], parent: str, key: str) -> object:
    nested = value.get(parent)
    if not isinstance(nested, dict):
        return None
    aliases = {
        "rating_value": "ratingValue",
        "review_count": "reviewCount",
    }
    return nested.get(aliases.get(key, key))


def fallback_record_id(raw: dict[str, Any]) -> str:
    """Return a stable ID for malformed source cards without a URL."""
    payload = (
        f"{_clean(raw.get('title'))}\n{_clean(raw.get('text'))}\n"
        f"{_clean(raw.get('images'))}\n{_clean(raw.get('videos'))}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


__all__ = [
    "DETAIL_PLATFORMS",
    "PRODUCT_PLATFORMS",
    "PUBLIC_PLATFORM_RECORDS_SCRIPT",
    "SUPPORTED_PUBLIC_PLATFORMS",
    "is_product_detail_url",
    "is_platform_detail_url",
    "normalize_public_platform_records",
    "public_platform",
]
