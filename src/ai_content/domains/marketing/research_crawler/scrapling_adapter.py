"""Browser crawler: Scrapling opens the page, Jev decides each step, media is collected."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

from .jev_navigation import JevBrowserNavigator, NavigationDecision
from .models import ResearchCrawlProgress, ResearchCrawlRecord

ProgressCallback = Callable[[ResearchCrawlProgress], Awaitable[None]]

_GOAL = (
    "Collect every image and video that can inspire advertising creative from this page, "
    "revealing more results when the page offers them."
)
_SNAPSHOT_SCRIPT = r"""() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const visible = (node) => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0
      && rect.bottom > -innerHeight && rect.top < innerHeight * 2;
  };
  const describe = (node) => {
    const link = node.closest('a[href]');
    return {
      link: link ? link.href : location.href,
      title: clean(node.alt || node.getAttribute('aria-label') || link?.innerText).slice(0, 300),
    };
  };
  const media = [];
  for (const img of document.querySelectorAll('img')) {
    const rect = img.getBoundingClientRect();
    const src = img.currentSrc || img.src;
    if (rect.width >= 100 && rect.height >= 100 && src.startsWith('http')) {
      media.push({kind: 'image', url: src, ...describe(img)});
    }
  }
  for (const video of document.querySelectorAll('video')) {
    const src = video.currentSrc || video.src || video.querySelector('source')?.src || '';
    if (src.startsWith('http')) media.push({kind: 'video', url: src, ...describe(video)});
    if (video.poster) media.push({kind: 'image', url: video.poster, ...describe(video)});
  }
  const controls = [];
  for (const node of document.querySelectorAll('button, a[href], [role="button"]')) {
    const text = clean(node.innerText || node.getAttribute('aria-label') || node.title);
    if (!text || !visible(node)) continue;
    const id = `control_${controls.length}`;
    node.setAttribute('data-aic-control', id);
    controls.push({id, text: text.slice(0, 120)});
    if (controls.length >= 40) break;
  }
  return {
    url: location.href,
    title: document.title || '',
    text: clean(document.body?.innerText).slice(0, 4000),
    media,
    controls,
  };
}"""


class ScraplingCrawler:
    def __init__(
        self,
        navigator: JevBrowserNavigator | None,
        *,
        timeout_seconds: float = 300,
        max_steps: int = 30,
        cookies_file: Path | None = None,
    ) -> None:
        self._navigator = navigator
        self._timeout_seconds = timeout_seconds
        self._max_steps = max_steps
        self._cookies_file = cookies_file

    async def crawl(
        self, url: str, progress: ProgressCallback | None = None
    ) -> tuple[bytes, dict[str, Any]]:
        from scrapling.fetchers import StealthyFetcher

        navigator = self._navigator
        if navigator is None:
            raise ValueError("Crawling needs JEV_API_KEY and AIC_AI_JEV_API_URL")
        if progress is not None:
            await progress(ResearchCrawlProgress(phase="opening_browser"))
        media: dict[str, dict[str, str]] = {}
        outcome: dict[str, Any] = {"stop_reason": None, "error": None}

        async def navigate(page: Any) -> None:
            try:
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                await page.wait_for_timeout(2_000)
                rounds_without_new_media = 0
                blocked_rounds = 0
                for step in range(1, self._max_steps + 1):
                    snapshot = await page.evaluate(_SNAPSHOT_SCRIPT)
                    before = len(media)
                    for item in snapshot["media"]:
                        media.setdefault(item["url"], item)
                    rounds_without_new_media = (
                        rounds_without_new_media + 1 if len(media) == before else 0
                    )
                    decision = await navigator.decide(
                        snapshot,
                        goal=_GOAL,
                        collected_media=len(media),
                        rounds_without_new_media=rounds_without_new_media,
                    )
                    logger.info(
                        "Crawl step {}: page_status={} action={} media={}",
                        step,
                        decision.page_status,
                        decision.action,
                        len(media),
                    )
                    walled = decision.page_status in {"login_required", "blocked"}
                    blocked_rounds = blocked_rounds + 1 if walled and len(media) == before else 0
                    if blocked_rounds >= 2:
                        outcome["stop_reason"] = decision.page_status
                    elif decision.action == "done":
                        outcome["stop_reason"] = "done"
                    if progress is not None:
                        await progress(_progress(media, step, decision, outcome["stop_reason"]))
                    if outcome["stop_reason"] is not None:
                        return
                    if decision.action == "scroll_down":
                        await page.mouse.wheel(0, 1_600)
                    else:
                        control = decision.action.removeprefix("click_")
                        await page.locator(f'[data-aic-control="{control}"]').first.click(
                            timeout=5_000
                        )
                    await page.wait_for_timeout(1_500)
                outcome["stop_reason"] = "step_limit"
            except Exception as error:
                outcome["error"] = error

        response = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            timeout=self._timeout_seconds * 1_000,
            locale="en-US",
            disable_resources=False,
            cookies=self._cookies(),
            page_action=navigate,
            additional_args={"viewport": {"width": 1_440, "height": 900}},
        )
        if outcome["error"] is not None:
            raise outcome["error"]
        body = bytes(response.body)
        records = [_record(item) for item in media.values()]
        return body, {
            "final_url": str(response.url),
            "platform": "generic",
            "http_status": int(response.status),
            "content_type": "text/html",
            "raw_size_bytes": len(body),
            "records": records,
            "records_complete": outcome["stop_reason"] == "done",
        }

    def _cookies(self) -> list[dict[str, Any]] | None:
        if self._cookies_file is None or not self._cookies_file.exists():
            return None
        return json.loads(self._cookies_file.read_text(encoding="utf-8"))


def _record(item: dict[str, str]) -> ResearchCrawlRecord:
    kind = item["kind"]
    return ResearchCrawlRecord(
        record_id=hashlib.sha256(item["url"].encode()).hexdigest()[:32],
        record_type=f"{kind}_reference",
        title=item["title"] or None,
        source_url=item["link"],
        image_urls=[item["url"]] if kind == "image" else [],
        video_urls=[item["url"]] if kind == "video" else [],
    )


def _progress(
    media: dict[str, dict[str, str]],
    step: int,
    decision: NavigationDecision,
    stop_reason: str | None,
) -> ResearchCrawlProgress:
    return ResearchCrawlProgress(
        phase="navigating",
        discovered_records=len(media),
        image_count=sum(item["kind"] == "image" for item in media.values()),
        video_count=sum(item["kind"] == "video" for item in media.values()),
        scroll_count=step,
        navigation_step=step,
        navigation_action=decision.action,
        page_status=decision.page_status,
        stop_reason=stop_reason,
        navigation_confidence=decision.confidence,
    )


__all__ = ["ScraplingCrawler"]
