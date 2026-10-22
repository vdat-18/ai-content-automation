"""Generic, platform-neutral extraction from one fetched public page."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.headings: dict[str, list[str]] = {f"h{level}": [] for level in range(1, 7)}
        self.metadata: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.image_urls: list[str] = []
        self.video_urls: list[str] = []
        self.json_ld_raw: list[str] = []
        self._ignored_depth = 0
        self._title_depth = 0
        self._heading: str | None = None
        self._heading_parts: list[str] = []
        self._link_url: str | None = None
        self._link_parts: list[str] = []
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"style", "noscript"}:
            self._ignored_depth += 1
        elif tag == "script":
            if attributes.get("type", "").lower() == "application/ld+json":
                self._json_ld_depth += 1
                self._json_ld_parts = []
            else:
                self._ignored_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag in self.headings:
            self._heading = tag
            self._heading_parts = []
        if tag == "meta":
            item = {
                key: attributes[key]
                for key in ("name", "property", "http-equiv", "itemprop", "content")
                if attributes.get(key)
            }
            if item:
                self.metadata.append(item)
            meta_key = (attributes.get("property") or attributes.get("name") or "").lower()
            if meta_key in {"og:image", "twitter:image", "twitter:image:src"} and attributes.get(
                "content"
            ):
                self.image_urls.append(urljoin(self.base_url, attributes["content"]))
            if meta_key in {"og:video", "og:video:url", "twitter:player:stream"} and attributes.get(
                "content"
            ):
                self.video_urls.append(urljoin(self.base_url, attributes["content"]))
        if tag == "a" and attributes.get("href"):
            self._link_url = urljoin(self.base_url, attributes["href"])
            self._link_parts = []
        media_type = attributes.get("type", "")
        if tag == "img" or (tag == "source" and not media_type.startswith("video/")):
            self._collect_media(attributes, self.image_urls, ("src", "data-src"))
            self._collect_srcset(attributes, self.image_urls)
        if tag in {"video", "source"} and (tag == "video" or media_type.startswith("video/")):
            self._collect_media(attributes, self.video_urls, ("src", "data-src"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if self._heading == tag:
            value = _clean_text(" ".join(self._heading_parts))
            if value:
                self.headings[tag].append(value)
            self._heading = None
            self._heading_parts = []
        if tag == "a" and self._link_url is not None:
            self.links.append(
                {"url": self._link_url, "text": _clean_text(" ".join(self._link_parts))}
            )
            self._link_url = None
            self._link_parts = []
        if tag == "script" and self._json_ld_depth:
            self.json_ld_raw.append("".join(self._json_ld_parts).strip())
            self._json_ld_depth -= 1
            self._json_ld_parts = []
        elif tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
            return
        if self._ignored_depth:
            return
        value = _clean_text(data)
        if not value:
            return
        self.text_parts.append(value)
        if self._title_depth:
            self.title_parts.append(value)
        if self._heading is not None:
            self._heading_parts.append(value)
        if self._link_url is not None:
            self._link_parts.append(value)

    def _collect_media(
        self,
        attributes: dict[str, str],
        target: list[str],
        keys: tuple[str, ...],
    ) -> None:
        for key in keys:
            if attributes.get(key):
                target.append(urljoin(self.base_url, attributes[key]))

    def _collect_srcset(self, attributes: dict[str, str], target: list[str]) -> None:
        for candidate in attributes.get("srcset", "").split(","):
            url = candidate.strip().split(" ", 1)[0]
            if url:
                target.append(urljoin(self.base_url, url))


def extract_page(html: str, final_url: str) -> dict[str, Any]:
    parser = _PageParser(final_url)
    parser.feed(html)
    parser.close()
    metadata = parser.metadata
    description = next(
        (
            item["content"]
            for item in metadata
            if item.get("name", "").lower() == "description"
            or item.get("property", "").lower() == "og:description"
        ),
        None,
    )
    return {
        "platform": detect_platform(final_url),
        "title": _clean_text(" ".join(parser.title_parts)) or None,
        "description": description,
        "text": "\n".join(parser.text_parts),
        "headings": {key: values for key, values in parser.headings.items() if values},
        "metadata": metadata,
        "json_ld": _parse_json_ld(parser.json_ld_raw),
        "links": parser.links,
        "image_urls": _unique(parser.image_urls),
        "video_urls": _unique(parser.video_urls),
    }


def detect_platform(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    platforms = {
        "etsy.com": "etsy",
        "facebook.com": "meta_ad_library",
        "pinterest.com": "pinterest",
        "tiktok.com": "tiktok",
        "amazon.com": "amazon",
        "houzz.com": "houzz",
        "wayfair.com": "wayfair",
        "adstransparency.google.com": "google_ads_transparency",
    }
    for suffix, platform in platforms.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return platform
    return "generic"


def _parse_json_ld(values: list[str]) -> list[Any]:
    parsed: list[Any] = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append(json.loads(value))
        except json.JSONDecodeError:
            parsed.append({"unparsed": value})
    return parsed


def _unique(values: list[str]) -> list[str]:
    return list(
        dict.fromkeys(value for value in values if value.startswith(("http://", "https://")))
    )


def _clean_text(value: str) -> str:
    return " ".join(value.split())


__all__ = ["detect_platform", "extract_page"]
