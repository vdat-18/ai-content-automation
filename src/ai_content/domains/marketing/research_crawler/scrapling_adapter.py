"""Scrapling adapter with public-network and response-size boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from loguru import logger

from .extraction import extract_page
from .google_ads_transparency import (
    GOOGLE_AD_FRAME_RECORD_SCRIPT,
    GOOGLE_ADS_RECORDS_SCRIPT,
    is_google_ads_transparency_url,
    normalize_google_ad_records,
    parse_google_ads_count,
)
from .identity import canonicalize_source_url, source_record_id
from .jev_navigation import JevBrowserNavigator
from .meta_ad_library import (
    META_AD_LIBRARY_RECORDS_SCRIPT,
    is_meta_ad_library_url,
    normalize_meta_ad_records,
)
from .models import ResearchCrawlProgress, ResearchCrawlRecord
from .public_platforms import (
    DETAIL_PLATFORMS,
    PUBLIC_PLATFORM_RECORDS_SCRIPT,
    is_platform_detail_url,
    normalize_public_platform_records,
    public_platform,
)

DEFAULT_MAX_RESPONSE_BYTES = 5_000_000
DEFAULT_MAX_META_RESPONSE_BYTES = 25_000_000
MAX_DISCOVERED_RECORDS = 10_000
MAX_NAVIGATION_STEPS = 240
PRODUCT_DETAIL_CONCURRENCY = 2
STABLE_ROUNDS_TO_FINISH = 4
ProgressCallback = Callable[[ResearchCrawlProgress], Awaitable[None]]
MetaFetcher = Callable[[str, float, ProgressCallback | None], Awaitable["FetchedPage"]]


@dataclass(frozen=True)
class FetchedPage:
    body: bytes
    final_url: str
    status: int
    content_type: str
    records: tuple[dict[str, Any], ...] = ()
    records_complete: bool | None = None


class ScraplingUnavailableError(ValueError):
    pass


class ScraplingCrawler:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_meta_response_bytes: int = DEFAULT_MAX_META_RESPONSE_BYTES,
        fetch: Callable[[str, float], Awaitable[FetchedPage]] | None = None,
        meta_fetch: MetaFetcher | None = None,
        google_fetch: MetaFetcher | None = None,
        platform_fetch: MetaFetcher | None = None,
        navigator: JevBrowserNavigator | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_meta_response_bytes = max_meta_response_bytes
        self._fetch = fetch or _fetch_with_scrapling
        self._meta_fetch = meta_fetch or (
            partial(_fetch_meta_with_scrapling, navigator=navigator) if fetch is None else None
        )
        self._google_fetch = google_fetch or (
            partial(_fetch_google_with_scrapling, navigator=navigator) if fetch is None else None
        )
        self._platform_fetch = platform_fetch or (
            partial(_fetch_public_platform_with_scrapling, navigator=navigator)
            if fetch is None
            else None
        )

    async def crawl(
        self, url: str, progress: ProgressCallback | None = None
    ) -> tuple[bytes, dict[str, Any]]:
        await validate_public_url(url)
        meta_ad_library = is_meta_ad_library_url(url)
        google_ads = is_google_ads_transparency_url(url)
        platform = public_platform(url)
        if progress is not None:
            await progress(ResearchCrawlProgress(phase="opening_browser"))
        if meta_ad_library and self._meta_fetch is not None:
            page = await self._meta_fetch(url, self._timeout_seconds, progress)
        elif google_ads and self._google_fetch is not None:
            page = await self._google_fetch(url, self._timeout_seconds, progress)
        elif platform is not None and self._platform_fetch is not None:
            page = await self._platform_fetch(url, self._timeout_seconds, progress)
        else:
            page = await self._fetch(url, self._timeout_seconds)
        await validate_public_url(page.final_url)
        if page.status >= 400:
            raise ValueError(f"Source returned HTTP {page.status}")
        max_response_bytes = (
            self._max_meta_response_bytes
            if meta_ad_library or google_ads or platform is not None
            else self._max_response_bytes
        )
        if len(page.body) > max_response_bytes:
            raise ValueError(
                f"Source response exceeds the {max_response_bytes // 1_000_000} MB limit"
            )
        content_type = page.content_type.split(";", 1)[0].strip().lower()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("Basic crawler currently supports public HTML pages only")
        html = page.body.decode("utf-8", errors="replace")
        extracted = extract_page(html, page.final_url)
        records = (
            normalize_meta_ad_records(list(page.records))
            if meta_ad_library
            else normalize_google_ad_records(list(page.records))
            if google_ads
            else normalize_public_platform_records(
                list(page.records),
                platform=platform,
                page_url=page.final_url,
                structured_data=extracted.get("json_ld", []),
                page_metadata=extracted.get("metadata", []),
            )
            if platform is not None
            else []
        )
        if not meta_ad_library and not google_ads and platform is None:
            records = [_generic_page_record(extracted, page.final_url)]
        extracted["records"] = records
        extracted["records_complete"] = page.records_complete
        if progress is not None:
            await progress(
                ResearchCrawlProgress(
                    phase="extracting",
                    discovered_records=len(records),
                    processed_records=len(records),
                    image_count=sum(len(record.image_urls) for record in records),
                    video_count=sum(len(record.video_urls) for record in records),
                )
            )
        extracted.update(
            {
                "final_url": page.final_url,
                "http_status": page.status,
                "content_type": content_type,
                "raw_size_bytes": len(page.body),
            }
        )
        return page.body, extracted


def _generic_page_record(extracted: dict[str, Any], final_url: str) -> ResearchCrawlRecord:
    return ResearchCrawlRecord(
        record_id=source_record_id(final_url),
        record_type="web_page",
        title=extracted.get("title"),
        text=str(extracted.get("text") or ""),
        source_url=final_url,
        metadata={
            "description": extracted.get("description"),
            "headings": extracted.get("headings", {}),
            "meta_tags": extracted.get("metadata", []),
            "json_ld": extracted.get("json_ld", []),
        },
        links=extracted.get("links", []),
        image_urls=extracted.get("image_urls", []),
        video_urls=extracted.get("video_urls", []),
    )


async def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Source URL must be a credential-free HTTP or HTTPS URL")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Source URL must resolve to the public internet")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except (ValueError, socket.gaierror) as error:
        raise ValueError("Source URL host could not be resolved") from error
    if not addresses:
        raise ValueError("Source URL host could not be resolved")
    for address in {item[4][0] for item in addresses}:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Source URL must resolve to the public internet")


async def _fetch_with_scrapling(url: str, timeout_seconds: float) -> FetchedPage:
    try:
        from scrapling.fetchers import AsyncFetcher
    except ImportError as error:
        raise ScraplingUnavailableError(
            "Scrapling fetchers are not installed; install the project dependencies"
        ) from error
    response = await AsyncFetcher.get(
        url,
        timeout=timeout_seconds,
        retries=2,
        follow_redirects="safe",
        stealthy_headers=True,
        impersonate="chrome",
    )
    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    final_url = str(getattr(response, "url", url))
    return FetchedPage(
        body=bytes(response.body),
        final_url=final_url,
        status=int(response.status),
        content_type=headers.get("content-type", ""),
    )


async def _fetch_meta_with_scrapling(
    url: str,
    timeout_seconds: float,
    progress: ProgressCallback | None = None,
    *,
    navigator: JevBrowserNavigator | None,
) -> FetchedPage:
    try:
        from scrapling.fetchers import DynamicFetcher
    except ImportError as error:
        raise ScraplingUnavailableError(
            "Scrapling browser fetchers are not installed; install the project dependencies"
        ) from error

    captured: dict[str, dict[str, Any]] = {}
    capture_error: list[Exception] = []
    state: dict[str, Any] = {
        "complete": False,
        "expected": None,
        "scrolls": 0,
        "stop_reason": None,
    }

    async def capture_and_scroll(page: Any) -> None:
        try:
            if navigator is None:
                raise ValueError("TypeSafe Jev API is required for browser crawling")
            await page.wait_for_timeout(4_000)
            expected = await page.evaluate(
                r"""() => {
                  const text = document.body?.innerText || "";
                  const match = text.match(/~?([0-9,]+)\s+results/i);
                  return match ? Number(match[1].replaceAll(",", "")) : null;
                }"""
            )
            state["expected"] = expected
            stable_rounds = 0
            for index in range(MAX_NAVIGATION_STEPS):
                state["scrolls"] = index + 1
                records = await page.evaluate(META_AD_LIBRARY_RECORDS_SCRIPT)
                before = len(captured)
                for record in records:
                    if len(captured) >= MAX_DISCOVERED_RECORDS:
                        break
                    captured[str(record["library_id"])] = record
                if expected is not None and len(captured) >= expected:
                    state["complete"] = True
                    state["stop_reason"] = "expected_records_reached"
                    break
                if len(captured) >= MAX_DISCOVERED_RECORDS:
                    state["stop_reason"] = "safety_record_limit"
                    break
                stable_rounds = stable_rounds + 1 if len(captured) == before else 0
                if progress is not None:
                    await progress(
                        ResearchCrawlProgress(
                            phase="scrolling",
                            discovered_records=len(captured),
                            processed_records=len(captured),
                            image_count=sum(
                                len(record.get("images", [])) for record in captured.values()
                            ),
                            video_count=sum(
                                len(record.get("videos", [])) for record in captured.values()
                            ),
                            scroll_count=index + 1,
                            expected_records=expected,
                        )
                    )
                decision = await navigator.step(
                    page,
                    goal="Expose every public ad in this Meta Ad Library result set.",
                    discovered_records=len(captured),
                    stable_rounds=stable_rounds,
                    may_finish=stable_rounds >= STABLE_ROUNDS_TO_FINISH,
                )
                if progress is not None:
                    await progress(
                        ResearchCrawlProgress(
                            phase="navigating",
                            discovered_records=len(captured),
                            scroll_count=index + 1,
                            expected_records=expected,
                            navigation_step=index + 1,
                            navigation_action=decision.action,
                            navigation_confidence=decision.confidence,
                        )
                    )
                if decision.action == "done":
                    state["complete"] = True
                    state["stop_reason"] = "jev_source_exhausted"
                    break
                await page.wait_for_timeout(750)
        except Exception as error:
            capture_error.append(error)
            raise

    response = await DynamicFetcher.async_fetch(
        url,
        headless=True,
        timeout=timeout_seconds * 1_000,
        retries=1,
        locale="en-US",
        network_idle=False,
        disable_resources=False,
        page_action=capture_and_scroll,
        additional_args={"viewport": {"width": 1_440, "height": 900}},
    )
    if capture_error:
        raise capture_error[0]
    if progress is not None:
        stop_reason = state["stop_reason"] or "scroll_limit"
        await progress(
            ResearchCrawlProgress(
                phase="extracting",
                discovered_records=len(captured),
                processed_records=len(captured),
                image_count=sum(len(record.get("images", [])) for record in captured.values()),
                video_count=sum(len(record.get("videos", [])) for record in captured.values()),
                scroll_count=int(state["scrolls"]),
                expected_records=state["expected"],
                stop_reason=stop_reason,
            )
        )
    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    return FetchedPage(
        body=bytes(response.body),
        final_url=str(getattr(response, "url", url)),
        status=int(response.status),
        content_type=headers.get("content-type", "text/html"),
        records=tuple(captured.values()),
        records_complete=state["complete"],
    )


async def _fetch_google_with_scrapling(
    url: str,
    timeout_seconds: float,
    progress: ProgressCallback | None = None,
    *,
    navigator: JevBrowserNavigator | None,
) -> FetchedPage:
    try:
        from scrapling.fetchers import DynamicFetcher
    except ImportError as error:
        raise ScraplingUnavailableError(
            "Scrapling browser fetchers are not installed; install the project dependencies"
        ) from error

    captured: dict[str, dict[str, Any]] = {}
    capture_error: list[Exception] = []
    state: dict[str, Any] = {
        "complete": False,
        "expected": None,
        "scrolls": 0,
        "stop_reason": None,
    }

    async def capture_and_scroll(page: Any) -> None:
        try:
            if navigator is None:
                raise ValueError("TypeSafe Jev API is required for browser crawling")
            await page.wait_for_timeout(4_000)
            count_text = await page.evaluate(
                "() => document.querySelector('.ads-count')?.innerText || ''"
            )
            expected = parse_google_ads_count(str(count_text))
            state["expected"] = expected
            stable_rounds = 0
            for index in range(MAX_NAVIGATION_STEPS):
                state["scrolls"] = index + 1
                records = await page.evaluate(GOOGLE_ADS_RECORDS_SCRIPT)
                before = len(captured)
                for record in records:
                    key = str(
                        record.get("creative_id")
                        or hashlib.sha256(
                            json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
                        ).hexdigest()
                    )
                    captured[key] = record
                    if len(captured) >= MAX_DISCOVERED_RECORDS:
                        break
                if expected is not None and len(captured) >= expected:
                    state["complete"] = True
                    state["stop_reason"] = "expected_records_reached"
                    break
                stable_rounds = stable_rounds + 1 if len(captured) == before else 0
                if progress is not None:
                    await progress(
                        ResearchCrawlProgress(
                            phase="scrolling",
                            discovered_records=len(captured),
                            processed_records=len(captured),
                            image_count=sum(
                                len(item.get("images", [])) for item in captured.values()
                            ),
                            video_count=sum(
                                len(item.get("videos", [])) for item in captured.values()
                            ),
                            scroll_count=index + 1,
                            expected_records=expected,
                        )
                    )
                if len(captured) >= MAX_DISCOVERED_RECORDS:
                    state["stop_reason"] = "safety_record_limit"
                    break
                decision = await navigator.step(
                    page,
                    goal="Expose every public creative in this Google Ads Transparency result set.",
                    discovered_records=len(captured),
                    stable_rounds=stable_rounds,
                    may_finish=stable_rounds >= STABLE_ROUNDS_TO_FINISH,
                )
                if progress is not None:
                    await progress(
                        ResearchCrawlProgress(
                            phase="navigating",
                            discovered_records=len(captured),
                            scroll_count=index + 1,
                            expected_records=expected,
                            navigation_step=index + 1,
                            navigation_action=decision.action,
                            navigation_confidence=decision.confidence,
                        )
                    )
                if decision.action == "done":
                    state["complete"] = True
                    state["stop_reason"] = "jev_source_exhausted"
                    break
                await page.wait_for_timeout(750)
            await _enrich_google_records_from_frames(page, captured)
        except Exception as error:
            capture_error.append(error)
            raise

    response = await DynamicFetcher.async_fetch(
        url,
        headless=True,
        timeout=timeout_seconds * 1_000,
        retries=1,
        locale="en-US",
        network_idle=False,
        disable_resources=False,
        page_action=capture_and_scroll,
        additional_args={"viewport": {"width": 1_440, "height": 900}},
    )
    if capture_error:
        raise capture_error[0]
    if progress is not None:
        await progress(
            ResearchCrawlProgress(
                phase="extracting",
                discovered_records=len(captured),
                processed_records=len(captured),
                image_count=sum(len(item.get("images", [])) for item in captured.values()),
                video_count=sum(len(item.get("videos", [])) for item in captured.values()),
                scroll_count=int(state["scrolls"]),
                expected_records=state["expected"],
                stop_reason=state["stop_reason"] or "scroll_limit",
            )
        )
    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    return FetchedPage(
        body=bytes(response.body),
        final_url=str(getattr(response, "url", url)),
        status=int(response.status),
        content_type=headers.get("content-type", "text/html"),
        records=tuple(captured.values()),
        records_complete=state["complete"],
    )


async def _fetch_public_platform_with_scrapling(
    url: str,
    timeout_seconds: float,
    progress: ProgressCallback | None = None,
    *,
    navigator: JevBrowserNavigator | None,
) -> FetchedPage:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as error:
        raise ScraplingUnavailableError(
            "Scrapling browser fetchers are not installed; install the project dependencies"
        ) from error

    source_platform = public_platform(url)
    captured: dict[str, dict[str, Any]] = {}
    capture_error: list[Exception] = []
    state: dict[str, Any] = {"scrolls": 0, "stop_reason": None}

    async def capture_and_scroll(page: Any) -> None:
        try:
            if navigator is None:
                raise ValueError("TypeSafe Jev API is required for browser crawling")
            await page.wait_for_timeout(3_000)
            stable_rounds = 0
            for index in range(MAX_NAVIGATION_STEPS):
                state["scrolls"] = index + 1
                candidates = await page.evaluate(PUBLIC_PLATFORM_RECORDS_SCRIPT)
                before = len(captured)
                for candidate in candidates:
                    serialized = json.dumps(candidate, sort_keys=True, ensure_ascii=False)
                    key = str(
                        candidate.get("external_id")
                        or next(iter(candidate.get("images") or []), None)
                        or next(iter(candidate.get("videos") or []), None)
                        or candidate.get("source_url")
                        or hashlib.sha256(serialized.encode()).hexdigest()
                    )
                    captured[key] = candidate
                    if len(captured) >= MAX_DISCOVERED_RECORDS:
                        break
                stable_rounds = stable_rounds + 1 if len(captured) == before else 0
                if progress is not None:
                    await progress(
                        ResearchCrawlProgress(
                            phase="scrolling",
                            discovered_records=len(captured),
                            processed_records=len(captured),
                            image_count=sum(
                                len(item.get("images", [])) for item in captured.values()
                            ),
                            video_count=sum(
                                len(item.get("videos", [])) for item in captured.values()
                            ),
                            scroll_count=index + 1,
                        )
                    )
                if len(captured) >= MAX_DISCOVERED_RECORDS:
                    state["stop_reason"] = "safety_record_limit"
                    break
                decision = await navigator.step(
                    page,
                    goal=(
                        "Expose every public product or creative in this result set without "
                        "opening a product purchase flow."
                    ),
                    discovered_records=len(captured),
                    stable_rounds=stable_rounds,
                    may_finish=stable_rounds >= STABLE_ROUNDS_TO_FINISH,
                )
                if progress is not None:
                    await progress(
                        ResearchCrawlProgress(
                            phase="navigating",
                            discovered_records=len(captured),
                            scroll_count=index + 1,
                            navigation_step=index + 1,
                            navigation_action=decision.action,
                            navigation_confidence=decision.confidence,
                        )
                    )
                if decision.action == "done":
                    state["stop_reason"] = "jev_source_exhausted"
                    break
                await page.wait_for_timeout(750)
        except Exception as error:
            capture_error.append(error)
            raise

    response = await StealthyFetcher.async_fetch(
        url,
        headless=True,
        timeout=timeout_seconds * 1_000,
        retries=1,
        locale="en-US",
        network_idle=False,
        solve_cloudflare=source_platform != "tiktok",
        disable_resources=False,
        page_action=capture_and_scroll,
        additional_args={"viewport": {"width": 1_440, "height": 900}},
    )
    if capture_error:
        raise capture_error[0]
    final_url = str(getattr(response, "url", url))
    platform = public_platform(final_url) or public_platform(url)
    if platform in DETAIL_PLATFORMS and not is_platform_detail_url(platform, final_url):
        product_urls = list(
            dict.fromkeys(
                canonicalize_source_url(str(candidate.get("source_url")))
                for candidate in captured.values()
                if is_platform_detail_url(platform, str(candidate.get("source_url") or ""))
            )
        )
        if progress is not None and product_urls:
            await progress(
                ResearchCrawlProgress(
                    phase="loading_results",
                    discovered_records=len(product_urls),
                    processed_records=0,
                    scroll_count=int(state["scrolls"]),
                )
            )
        detailed = await _fetch_public_product_details(
            product_urls,
            platform=platform,
            timeout_seconds=timeout_seconds,
            fetcher=StealthyFetcher,
            progress=progress,
            navigator=navigator,
        )
        captured = {
            str(record.get("external_id") or source_url): detailed.get(source_url, record)
            for record in captured.values()
            if (source_url := canonicalize_source_url(str(record.get("source_url") or "")))
        }
        if product_urls and len(detailed) < len(product_urls):
            state["stop_reason"] = "product_detail_failures"
    if progress is not None:
        await progress(
            ResearchCrawlProgress(
                phase="extracting",
                discovered_records=len(captured),
                processed_records=len(captured),
                image_count=sum(len(item.get("images", [])) for item in captured.values()),
                video_count=sum(len(item.get("videos", [])) for item in captured.values()),
                scroll_count=int(state["scrolls"]),
                stop_reason=state["stop_reason"] or "scroll_limit",
            )
        )
    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    return FetchedPage(
        body=bytes(response.body),
        final_url=final_url,
        status=int(response.status),
        content_type=headers.get("content-type", "text/html"),
        records=tuple(captured.values()),
        records_complete=state["stop_reason"] == "jev_source_exhausted",
    )


async def _fetch_public_product_details(
    urls: list[str],
    *,
    platform: str,
    timeout_seconds: float,
    fetcher: Any,
    progress: ProgressCallback | None,
    navigator: JevBrowserNavigator,
) -> dict[str, dict[str, Any]]:
    semaphore = asyncio.Semaphore(PRODUCT_DETAIL_CONCURRENCY)
    processed = 0
    lock = asyncio.Lock()

    async def fetch_one(detail_url: str) -> tuple[str, dict[str, Any] | None]:
        nonlocal processed
        try:
            await validate_public_url(detail_url)
            async with semaphore:
                record = await _fetch_public_product_detail(
                    detail_url,
                    platform=platform,
                    timeout_seconds=timeout_seconds,
                    fetcher=fetcher,
                    navigator=navigator,
                )
        except Exception as error:
            logger.warning(
                "Could not enrich one {} product detail: {}",
                platform,
                type(error).__name__,
            )
            record = None
        async with lock:
            processed += 1
            if progress is not None:
                await progress(
                    ResearchCrawlProgress(
                        phase="loading_results",
                        discovered_records=len(urls),
                        processed_records=processed,
                    )
                )
        return detail_url, record

    results = await asyncio.gather(*(fetch_one(url) for url in urls))
    return {url: record for url, record in results if record is not None}


async def _fetch_public_product_detail(
    url: str,
    *,
    platform: str,
    timeout_seconds: float,
    fetcher: Any,
    navigator: JevBrowserNavigator,
) -> dict[str, Any] | None:
    captured: list[dict[str, Any]] = []

    async def capture_detail(page: Any) -> None:
        await page.wait_for_timeout(2_500)
        if platform == "tiktok":
            # TikTok renders the complete creative payload on the detail page. Jev already
            # drives discovery on the listing; opening several detail browsers and asking
            # Jev to rediscover a page with no pagination only adds latency and memory use.
            await page.mouse.wheel(0, 1_600)
            await page.wait_for_timeout(750)
            records = await page.evaluate(PUBLIC_PLATFORM_RECORDS_SCRIPT)
            if records:
                captured[:] = [records[0]]
            return
        stable_rounds = 0
        for _ in range(12):
            records = await page.evaluate(PUBLIC_PLATFORM_RECORDS_SCRIPT)
            if records:
                previous = json.dumps(captured[0], sort_keys=True) if captured else ""
                captured[:] = [records[0]]
                current = json.dumps(captured[0], sort_keys=True)
                stable_rounds = stable_rounds + 1 if current == previous else 0
            decision = await navigator.step(
                page,
                goal="Expose all public product details, images, videos, variants and metadata.",
                discovered_records=1 if captured else 0,
                stable_rounds=stable_rounds,
                may_finish=stable_rounds >= 2,
            )
            if decision.action == "done":
                break
            await page.wait_for_timeout(350)
        records = await page.evaluate(PUBLIC_PLATFORM_RECORDS_SCRIPT)
        if records:
            captured[:] = [records[0]]

    response = await fetcher.async_fetch(
        url,
        headless=True,
        timeout=timeout_seconds * 1_000,
        retries=1,
        locale="en-US",
        network_idle=False,
        solve_cloudflare=platform != "tiktok",
        disable_resources=False,
        page_action=capture_detail,
        additional_args={"viewport": {"width": 1_440, "height": 900}},
    )
    if int(response.status) >= 400 or not captured:
        return None
    final_url = str(getattr(response, "url", url))
    if not is_platform_detail_url(platform, final_url):
        return None
    extracted = extract_page(bytes(response.body).decode("utf-8", errors="replace"), final_url)
    record = captured[0]
    record["source_url"] = final_url
    record["structured_data"] = extracted.get("json_ld", [])
    record["page_metadata"] = extracted.get("metadata", [])
    record["detail_status"] = "complete"
    return record


async def _enrich_google_records_from_frames(
    page: Any, captured: dict[str, dict[str, Any]]
) -> None:
    for frame in page.frames:
        if not str(frame.url).startswith("https://adstransparency.google.com/adframe"):
            continue
        frame_element = await frame.frame_element()
        creative_id = await frame_element.evaluate(
            r"""(element) => {
              const url = element.closest('creative-preview')
                ?.querySelector('a[href*="/creative/"]')?.href || '';
              return url.match(/\/creative\/(CR[0-9]+)/i)?.[1]?.toUpperCase() || null;
            }"""
        )
        if not creative_id or creative_id not in captured:
            continue
        enrichment = await frame.evaluate(GOOGLE_AD_FRAME_RECORD_SCRIPT)
        record = captured[creative_id]
        frame_text = str(enrichment.get("text") or "").strip()
        if frame_text and frame_text not in str(record.get("text") or ""):
            record["text"] = " ".join(part for part in (record.get("text"), frame_text) if part)
        for field in ("images", "videos"):
            record[field] = list(
                dict.fromkeys([*record.get(field, []), *enrichment.get(field, [])])
            )


__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_MAX_META_RESPONSE_BYTES",
    "FetchedPage",
    "ScraplingCrawler",
    "ScraplingUnavailableError",
    "validate_public_url",
]
