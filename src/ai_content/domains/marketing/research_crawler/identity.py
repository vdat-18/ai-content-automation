"""Stable identities and change fingerprints for public research records."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

from .models import ResearchCrawlRecord

_SIGNED_CDN_SUFFIXES = ("fbcdn.net", "cdninstagram.com")
_PINTEREST_SIZE = re.compile(r"^/(?:\d+x\d*|originals)/")


def canonicalize_source_url(url: str) -> str:
    return url.strip()


def crawl_fingerprint(
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str | None,
    source_url: str,
    media_mode: str = "images_and_videos",
    analysis_model_id: str | None = None,
) -> str:
    value = "\n".join(
        (
            workspace_id,
            brand_id,
            project_id or "",
            canonicalize_source_url(source_url),
            media_mode,
            analysis_model_id or "",
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def research_record_key(
    *, workspace_id: str, brand_id: str, platform: str, external_id: str
) -> str:
    value = "\n".join((workspace_id, brand_id, platform, external_id))
    return f"record_{hashlib.sha256(value.encode()).hexdigest()[:32]}"


def source_record_id(url: str) -> str:
    return hashlib.sha256(canonicalize_source_url(url).encode()).hexdigest()[:32]


def canonicalize_media_url(url: str) -> str:
    """Drop what changes between visits but does not change the picture."""

    stripped = url.strip()
    parsed = urlsplit(stripped)
    host = (parsed.hostname or "").lower()
    if host.endswith(_SIGNED_CDN_SUFFIXES):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if host.endswith("pinimg.com"):
        return urlunsplit(
            (parsed.scheme, parsed.netloc, _PINTEREST_SIZE.sub("/size/", parsed.path, 1), "", "")
        )
    return stripped


def media_source_fingerprint(url: str) -> str:
    return hashlib.sha256(canonicalize_media_url(url).encode()).hexdigest()


def research_record_content_hash(record: ResearchCrawlRecord) -> str:
    payload = record.model_dump(mode="json")
    if record.source_url:
        payload["source_url"] = canonicalize_source_url(record.source_url)
    payload["image_urls"] = [_stable_media_url(url) for url in record.image_urls]
    payload["video_urls"] = [_stable_media_url(url) for url in record.video_urls]
    payload["links"] = [
        {"url": canonicalize_source_url(link["url"]), "text": link.get("text", "")}
        for link in record.links
    ]
    payload["metadata"] = _stable_value(record.metadata)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _stable_media_url(url: str) -> str:
    return canonicalize_media_url(url)


def _stable_value(value: object) -> object:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return canonicalize_source_url(value)
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable_value(item) for key, item in value.items()}
    return value


__all__ = [
    "canonicalize_source_url",
    "canonicalize_media_url",
    "crawl_fingerprint",
    "media_source_fingerprint",
    "research_record_content_hash",
    "research_record_key",
    "source_record_id",
]
