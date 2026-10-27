"""Bounded capture of public research media into immutable artifact storage."""

from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import urlsplit, urlunsplit

import httpx

from .artifacts import ResearchCrawlArtifactWriter
from .identity import media_source_fingerprint
from .models import ResearchMediaAsset
from .perceptual_hash import perceptual_hash


class ResearchMediaCapturer:
    def __init__(
        self,
        artifacts: ResearchCrawlArtifactWriter,
        *,
        timeout_seconds: float = 30,
        concurrency: int = 4,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._timeout = timeout_seconds
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._client = client

    @property
    def max_concurrency(self) -> int:
        return self._concurrency

    async def capture(
        self,
        *,
        record_key: str,
        brand_id: str,
        image_urls: list[str],
        video_urls: list[str],
        existing: list[ResearchMediaAsset],
        reuse_existing: bool = True,
    ) -> list[ResearchMediaAsset]:
        reusable = {
            (asset.media_kind, asset.source_url_fingerprint): asset
            for asset in existing
            if reuse_existing and asset.status == "available"
        }
        inputs = list(
            {
                (kind, media_source_fingerprint(url)): (kind, url)
                for kind, urls in (("image", image_urls), ("video", video_urls))
                for url in urls
            }.values()
        )
        tasks = [
            self._capture_one(record_key, brand_id, kind, index, url, reusable)
            for index, (kind, url) in enumerate(inputs)
        ]
        return list(await asyncio.gather(*tasks))

    async def _capture_one(
        self,
        record_key: str,
        brand_id: str,
        kind: str,
        index: int,
        url: str,
        reusable: dict[tuple[str, str], ResearchMediaAsset],
    ) -> ResearchMediaAsset:
        fingerprint = media_source_fingerprint(url)
        identity = "\n".join((record_key, kind, fingerprint))
        media_id = f"media_{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        cached = reusable.get((kind, fingerprint))
        if cached is not None:
            return cached
        try:
            async with self._semaphore:
                content, content_type = await self._download(url)
            extension = _extension(content_type)
            artifact_ref, checksum = await self._artifacts.write_media(
                record_key=record_key,
                filename=f"{kind}-{index}.{extension}",
                content=content,
                brand_id=brand_id,
            )
            return ResearchMediaAsset(
                media_id=media_id,
                media_kind=kind,
                source_url_fingerprint=fingerprint,
                source_url=_redact_url(url),
                status="available",
                artifact_ref=artifact_ref,
                content_type=content_type,
                sha256=checksum,
                perceptual_hash=perceptual_hash(content) if kind == "image" else None,
                size_bytes=len(content),
            )
        except (ValueError, httpx.HTTPError, OSError):
            return ResearchMediaAsset(
                media_id=media_id,
                media_kind=kind,
                source_url_fingerprint=fingerprint,
                source_url=_redact_url(url),
                status="failed",
                error_code="MEDIA_CAPTURE_FAILED",
            )

    async def _download(self, url: str) -> tuple[bytes, str]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        try:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            return response.content, content_type
        finally:
            if owns_client:
                await client.aclose()


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _extension(content_type: str) -> str:
    return content_type.rsplit("/", 1)[-1]


__all__ = ["ResearchMediaCapturer"]
