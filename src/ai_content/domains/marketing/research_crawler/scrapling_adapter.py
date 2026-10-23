"""Crawler skeleton: fetches one page and returns it without extracting records."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .models import ResearchCrawlProgress

ProgressCallback = Callable[[ResearchCrawlProgress], Awaitable[None]]


class ScraplingCrawler:
    async def crawl(
        self, url: str, progress: ProgressCallback | None = None
    ) -> tuple[bytes, dict[str, Any]]:
        from scrapling.fetchers import AsyncFetcher

        if progress is not None:
            await progress(ResearchCrawlProgress(phase="opening_browser"))
        response = await AsyncFetcher.get(url)
        # TODO: extract platform records into extracted["records"].
        return bytes(response.body), {
            "final_url": str(response.url),
            "http_status": int(response.status),
            "records": [],
        }
