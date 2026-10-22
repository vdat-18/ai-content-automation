"""Meta Ad Library URL detection and normalized public-ad records."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .models import ResearchCrawlRecord

META_AD_LIBRARY_RECORDS_SCRIPT = r"""() => {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const absolute = (value) => {
    try { return new URL(value, location.href).href; } catch (_) { return ""; }
  };
  const imageUrls = (image) => [
    ...(image.getAttribute("srcset") || "").split(",")
      .map((part) => part.trim().split(/\s+/)[0]),
    image.currentSrc || image.src,
    image.getAttribute("data-src"),
  ].map(absolute).filter(Boolean);
  const markers = [...document.querySelectorAll("body *")].filter((element) =>
    element.children.length === 0 && /Library ID:\s*\d+/.test(clean(element.textContent))
  );
  return markers.map((marker) => {
    let card = marker;
    let node = marker;
    for (let depth = 0; depth < 20 && node.parentElement; depth += 1) {
      const parent = node.parentElement;
      const ids = clean(parent.innerText).match(/Library ID:\s*\d+/g) || [];
      if (ids.length > 1) break;
      card = parent;
      node = parent;
    }
    const text = clean(card.innerText);
    const libraryId = (text.match(/Library ID:\s*(\d+)/) || [])[1];
    return {
      library_id: libraryId,
      text,
      links: [...card.querySelectorAll("a[href]")].map((anchor) => ({
        text: clean(anchor.innerText),
        url: anchor.href,
      })),
      images: [...card.querySelectorAll("img")].flatMap((image) =>
        imageUrls(image).map((url) => ({alt: clean(image.alt), url}))
      ),
      videos: [...card.querySelectorAll("video, video source")]
        .map((video) => absolute(video.currentSrc || video.src))
        .filter(Boolean),
      posters: [...card.querySelectorAll("video[poster]")]
        .map((video) => absolute(video.poster)).filter(Boolean),
      aria_labels: [...card.querySelectorAll("[aria-label]")]
        .map((element) => clean(element.getAttribute("aria-label")))
        .filter(Boolean),
    };
  }).filter((record) => record.library_id);
}"""

_META_HOST_SUFFIXES = ("facebook.com",)


def is_meta_ad_library_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in _META_HOST_SUFFIXES
    ) and (parsed.path.rstrip("/") == "/ads/library")


def normalize_meta_ad_records(raw_records: list[dict[str, Any]]) -> list[ResearchCrawlRecord]:
    records: list[ResearchCrawlRecord] = []
    seen: set[str] = set()
    for raw in raw_records:
        library_id = _clean(str(raw.get("library_id") or ""))
        if not library_id or library_id in seen:
            continue
        seen.add(library_id)
        text = _clean(_clean(str(raw.get("text") or "")).replace("\u200b", ""))
        links = _normalize_links(raw.get("links"))
        advertiser = next(
            (link for link in links if _is_advertiser_link(link["url"]) and link["text"]),
            None,
        )
        started_match = re.search(r"Started running on (.+?)(?: Platforms|$)", text)
        status_match = re.match(r"^(Active|Inactive)\b", text)
        records.append(
            ResearchCrawlRecord(
                record_id=library_id,
                record_type="meta_ad",
                title=advertiser["text"] if advertiser else None,
                text=text,
                source_url=f"https://www.facebook.com/ads/library/?id={library_id}",
                metadata={
                    "status": status_match.group(1).lower() if status_match else None,
                    "started_running_on": started_match.group(1) if started_match else None,
                    "advertiser_url": advertiser["url"] if advertiser else None,
                    "aria_labels": _unique_strings(raw.get("aria_labels")),
                },
                links=links,
                image_urls=list(
                    dict.fromkeys(
                        [*_media_urls(raw.get("images")), *_unique_urls(raw.get("posters"))]
                    )
                ),
                video_urls=_unique_urls(raw.get("videos")),
            )
        )
    return records


def _normalize_links(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _unwrap_facebook_redirect(_clean(str(item.get("url") or "")))
        text = _clean(str(item.get("text") or ""))
        key = (url, text)
        if url.startswith(("http://", "https://")) and key not in seen:
            seen.add(key)
            links.append({"url": url, "text": text})
    return links


def _media_urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_urls(
        item.get("url") for item in value if isinstance(item, dict) and item.get("url")
    )


def _unique_urls(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) and not hasattr(value, "__iter__"):
        return []
    return list(
        dict.fromkeys(
            _clean(str(item))
            for item in value
            if item and _clean(str(item)).startswith(("http://", "https://"))
        )
    )


def _unique_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(_clean(str(item)) for item in value if _clean(str(item))))


def _unwrap_facebook_redirect(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname == "l.facebook.com" and parsed.path == "/l.php":
        destination = parse_qs(parsed.query).get("u", [])
        if destination and destination[0].startswith(("http://", "https://")):
            return destination[0]
    return url


def _is_advertiser_link(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host == "facebook.com" and not parsed.path.startswith("/ads/")


def _clean(value: str) -> str:
    return " ".join(value.split())


__all__ = [
    "META_AD_LIBRARY_RECORDS_SCRIPT",
    "is_meta_ad_library_url",
    "normalize_meta_ad_records",
]
