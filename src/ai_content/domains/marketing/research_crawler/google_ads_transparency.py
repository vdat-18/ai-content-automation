"""Google Ads Transparency URL detection and visible-card normalization."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from .models import ResearchCrawlRecord

GOOGLE_ADS_RECORDS_SCRIPT = r"""() => {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const creativePreviews = [...document.querySelectorAll('creative-preview')];
  const candidates = creativePreviews.length ? creativePreviews : [...document.querySelectorAll(
    '[data-ad-id], [data-creative-id], material-card, mat-card, [role="listitem"]'
  )].filter((card) => !card.querySelector('creative-preview'));
  return candidates.map((card) => {
    const text = clean(card.innerText);
    const links = [...card.querySelectorAll('a[href]')].map((a) => ({
      text: clean(a.innerText), url: a.href
    }));
    const detailLink = links.find((link) => /\/creative\/CR[0-9]+/i.test(link.url));
    const idSource = card.getAttribute('data-creative-id') ||
      card.getAttribute('data-ad-id') || detailLink?.url || '';
    const match = idSource.match(/(?:^|\/)(CR[0-9]+)(?:[/?#]|$)/i);
    const advertiser = clean(card.querySelector('.advertiser-name')?.innerText);
    return {
      creative_id: match ? match[1].toUpperCase() : null,
      advertiser: advertiser || null,
      text,
      links,
      images: [...card.querySelectorAll('img')].map((img) => img.currentSrc || img.src).filter(Boolean),
      videos: [...card.querySelectorAll('video')].map((video) => video.currentSrc || video.src).filter(Boolean)
    };
  }).filter((item) => item.text && (item.images.length || item.videos.length || item.links.length));
}"""

GOOGLE_AD_FRAME_RECORD_SCRIPT = r"""() => {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const backgroundUrls = [...document.querySelectorAll('*')].flatMap((element) => {
    const value = getComputedStyle(element).backgroundImage || '';
    return [...value.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map((match) => match[1]);
  });
  const allowed = (value) => {
    if (!value || !value.startsWith('https://')) return false;
    try {
      const parsed = new URL(value);
      return parsed.hostname !== 'maps.googleapis.com' &&
        !(parsed.hostname === 'googleads.g.doubleclick.net' && parsed.pathname.startsWith('/pagead/images/'));
    } catch (_) {
      return false;
    }
  };
  return {
    text: clean(document.body?.innerText),
    images: [...document.querySelectorAll('img')]
      .map((image) => image.currentSrc || image.src).concat(backgroundUrls).filter(allowed),
    videos: [...document.querySelectorAll('video, source')]
      .map((video) => video.currentSrc || video.src).filter(allowed)
  };
}"""


def is_google_ads_transparency_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return host == "adstransparency.google.com"


def parse_google_ads_count(value: str) -> int | None:
    match = re.search(r"~?([0-9]+(?:[.,][0-9]+)?)\s*([KM])?", value, re.IGNORECASE)
    if not match:
        return None
    suffix = (match.group(2) or "").upper()
    raw_number = match.group(1)
    if suffix:
        number = float(raw_number.replace(",", "."))
        return int(number * (1_000 if suffix == "K" else 1_000_000))
    return int(raw_number.replace(",", "").replace(".", ""))


def normalize_google_ad_records(raw_records: list[dict[str, Any]]) -> list[ResearchCrawlRecord]:
    records: list[ResearchCrawlRecord] = []
    seen: set[str] = set()
    for raw in raw_records:
        text = " ".join(str(raw.get("text") or "").split())
        links = _links(raw.get("links"))
        identifier = (
            str(raw.get("creative_id") or "").strip()
            or hashlib.sha256(f"{text}\n{links}".encode()).hexdigest()[:24]
        )
        if not text or identifier in seen:
            continue
        seen.add(identifier)
        advertiser = str(raw.get("advertiser") or "").strip() or _advertiser(text)
        records.append(
            ResearchCrawlRecord(
                record_id=identifier,
                record_type="google_ad",
                title=advertiser,
                text=text,
                source_url=next((link["url"] for link in links), None),
                metadata={"advertiser": advertiser},
                links=links,
                image_urls=_urls(raw.get("images")),
                video_urls=_urls(raw.get("videos")),
            )
        )
    return records


def _advertiser(text: str) -> str | None:
    match = re.search(r"Advertiser\s*[:\-]?\s*([^|·]{2,80})", text, re.IGNORECASE)
    return " ".join(match.group(1).split()) if match else None


def _links(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return list(
        {
            (str(item.get("url")), str(item.get("text") or "")): {
                "url": str(item.get("url")),
                "text": str(item.get("text") or ""),
            }
            for item in value
            if isinstance(item, dict)
            and str(item.get("url") or "").startswith(("http://", "https://"))
        }.values()
    )


def _urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).startswith("https://")))


__all__ = [
    "GOOGLE_ADS_RECORDS_SCRIPT",
    "GOOGLE_AD_FRAME_RECORD_SCRIPT",
    "is_google_ads_transparency_url",
    "normalize_google_ad_records",
    "parse_google_ads_count",
]
