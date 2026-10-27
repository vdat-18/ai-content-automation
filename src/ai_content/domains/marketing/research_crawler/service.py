"""Application service for one public-page research crawl."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from loguru import logger

from .artifacts import ResearchCrawlArtifactWriter
from .brand_context import ResearchBrandContextResolver
from .identity import canonicalize_media_url, research_record_content_hash, research_record_key
from .media_capture import ResearchMediaCapturer
from .models import (
    MediaFingerprint,
    ResearchBrandContext,
    ResearchCrawlJob,
    ResearchCrawlProgress,
    ResearchCrawlRecord,
    ResearchCrawlResult,
    ResearchCrawlStatus,
    ResearchScreening,
    StoredResearchRecord,
)
from .perceptual_hash import is_duplicate_hash
from .repository import ResearchCrawlRepository
from .scrapling_adapter import ScraplingCrawler
from .screening import NineRouterResearchScreener


class ResearchCrawlService:
    def __init__(
        self,
        repository: ResearchCrawlRepository,
        crawler: ScraplingCrawler,
        artifacts: ResearchCrawlArtifactWriter,
        media_capturer: ResearchMediaCapturer | None = None,
        brand_context_resolver: ResearchBrandContextResolver | None = None,
        screener: NineRouterResearchScreener | None = None,
    ) -> None:
        self._repository = repository
        self._crawler = crawler
        self._artifacts = artifacts
        self._media_capturer = media_capturer
        self._screener = screener
        self._brand_context_resolver = brand_context_resolver

    async def execute(self, job_id: str) -> None:
        job = await self._repository.get(job_id)
        if job is None:
            raise ValueError("Research crawl job does not exist")
        brand_context = await self._resolve_brand_context(job)
        running = job.model_copy(
            update={
                "brand_context": brand_context,
                "status": "running",
                "progress": ResearchCrawlProgress(phase="opening_browser"),
                "error_code": None,
                "error_message": None,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save(running)
        raw, extracted = await self._crawler.crawl(
            job.source_url,
            progress=lambda value: self._record_progress(job_id, value),
        )
        records = _media_reference_records(extracted, running.media_mode)
        duplicate_records = max(
            0,
            _media_candidate_occurrences(extracted, running.media_mode) - len(records),
        )
        artifact_ref = await self._artifacts.write(job.job_id, raw, job.brand_id)
        discovered = _accepted_extraction(extracted, records)
        result = ResearchCrawlResult(raw_artifact_ref=artifact_ref, **discovered)
        latest = await self._repository.get(job_id)
        if latest is None:
            raise ValueError("Research crawl job does not exist")
        saving = latest.model_copy(
            update={
                "result": result,
                "progress": latest.progress.model_copy(
                    update={
                        "phase": "saving",
                        "processed_records": len(records),
                        "source_records_discovered": len(extracted.get("records", [])),
                        "media_candidates": len(records),
                        "duplicate_records": duplicate_records,
                    }
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save(saving)
        summary = await self._repository.upsert_records(saving, records=records)
        failed_enrichments = await self._capture_media(saving)
        review_records, auto_filtered, analysis_unavailable = await self._screen_records(
            saving,
            records,
            brand_context,
            str(extracted.get("platform") or "generic"),
        )
        accepted = _accepted_extraction(extracted, review_records)
        final_result = ResearchCrawlResult(raw_artifact_ref=artifact_ref, **accepted)
        latest = await self._repository.get(job_id)
        if latest is None:
            raise ValueError("Research crawl job does not exist")
        await self._repository.save(
            latest.model_copy(
                update={
                    "result": final_result,
                    "status": "completed",
                    "progress": latest.progress.model_copy(
                        update={
                            "phase": "completed",
                            "saved_records": len(review_records),
                            "new_records": summary.created,
                            "updated_records": summary.updated,
                            "unchanged_records": summary.unchanged,
                            "failed_records": failed_enrichments,
                            "accepted_records": len(review_records),
                            "rejected_records": auto_filtered,
                            "auto_filtered_records": auto_filtered,
                            "analysis_unavailable_records": analysis_unavailable,
                        }
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
        )

    async def _resolve_brand_context(self, job: ResearchCrawlJob) -> ResearchBrandContext | None:
        if self._brand_context_resolver is None:
            return job.brand_context
        try:
            return await self._brand_context_resolver.resolve(job.brand_id)
        except Exception as error:
            logger.warning(
                "Research screening will run without brand context because it could not be resolved: {}",
                type(error).__name__,
            )
            return None

    async def _screen_records(
        self,
        job: ResearchCrawlJob,
        records: list[ResearchCrawlRecord],
        brand_context: ResearchBrandContext | None,
        platform: str,
    ) -> tuple[list[ResearchCrawlRecord], int, int]:
        if self._screener is None:
            return [], 0, len(records)
        screener = self._screener

        async def screen_one(
            index: int,
            record: ResearchCrawlRecord,
        ) -> tuple[int, ResearchCrawlRecord, ResearchScreening, bool, str]:
            candidate = _candidate_record(job, record, platform)
            existing = await self._repository.get_record(candidate.record_key)
            if existing is None:
                raise ValueError("Research record was not persisted before analysis")
            if existing.screening is not None and screener.can_reuse(
                existing.screening, existing, brand_context
            ):
                return index, record, existing.screening, False, existing.screening_status
            own = _image_fingerprints(existing)
            duplicate_of = _duplicate_of(own, known) if existing.screening is None else None
            if duplicate_of is not None:
                screening = screener.duplicate_screening(
                    existing, brand_context, duplicate_of=duplicate_of
                )
                return index, record, screening, True, "auto_filtered"
            screening = await screener.screen(existing, brand_context=brand_context)
            if screening.status == "completed":
                known.extend(own)
            status = (
                "unavailable"
                if screening.status == "failed"
                else ("kept" if screening.usable else "auto_filtered")
            )
            return index, record, screening, True, status

        known = await self._repository.known_media_fingerprints(
            job.workspace_id, job.brand_id, exclude_record_key=""
        )
        concurrency = max(1, int(getattr(screener, "max_concurrency", 1)))
        results: list[tuple[int, ResearchCrawlRecord, ResearchScreening, bool, str]] = []
        processed = 0
        auto_filtered = 0
        analysis_unavailable = 0
        for offset in range(0, len(records), concurrency):
            tasks = [
                asyncio.create_task(screen_one(index, record))
                for index, record in enumerate(records[offset : offset + concurrency], offset + 1)
            ]
            for task in asyncio.as_completed(tasks):
                result = await task
                results.append(result)
                processed += 1
                if result[4] == "auto_filtered":
                    auto_filtered += 1
                elif result[4] == "unavailable":
                    analysis_unavailable += 1
                await self._record_progress(
                    job.job_id,
                    ResearchCrawlProgress(
                        phase="classifying",
                        discovered_records=len(records),
                        processed_records=processed,
                        accepted_records=processed - auto_filtered - analysis_unavailable,
                        rejected_records=auto_filtered,
                        auto_filtered_records=auto_filtered,
                        analysis_unavailable_records=analysis_unavailable,
                        media_candidates=len(records),
                        media_analysis_completed=processed,
                    ),
                )
        results.sort(key=lambda value: value[0])
        visible: list[ResearchCrawlRecord] = []
        for _, record, screening, evaluated, analysis_status in results:
            if evaluated:
                candidate = _candidate_record(job, record, platform)
                await self._repository.save_record_enrichment(
                    candidate.record_key,
                    screening=screening,
                )
            if analysis_status == "kept":
                visible.append(record)
        return visible, auto_filtered, analysis_unavailable

    async def _capture_media(self, job: ResearchCrawlJob) -> int:
        if job.result is None:
            return 0
        failures = 0

        async def capture_one(index: int, record: ResearchCrawlRecord) -> tuple[int, int]:
            key = research_record_key(
                workspace_id=job.workspace_id,
                brand_id=job.brand_id,
                platform=job.result.platform,
                external_id=record.record_id,
            )
            stored = await self._repository.get_record(key)
            if stored is None:
                return index, 1
            if self._media_capturer is not None and (record.image_urls or record.video_urls):
                assets = await self._media_capturer.capture(
                    record_key=key,
                    brand_id=job.brand_id,
                    image_urls=record.image_urls,
                    video_urls=record.video_urls,
                    existing=stored.media_assets,
                    reuse_existing=False,
                )
                await self._repository.save_record_enrichment(key, media_assets=assets)
                return index, sum(asset.status == "failed" for asset in assets)
            return index, 0

        concurrency = max(
            1,
            int(getattr(self._media_capturer, "max_concurrency", 1)),
        )
        records = job.result.records
        processed = 0
        for offset in range(0, len(records), concurrency):
            tasks = [
                asyncio.create_task(capture_one(index, record))
                for index, record in enumerate(records[offset : offset + concurrency], offset + 1)
            ]
            for task in asyncio.as_completed(tasks):
                _, task_failures = await task
                failures += task_failures
                processed += 1
                await self._record_progress(
                    job.job_id,
                    ResearchCrawlProgress(
                        phase="capturing_media",
                        discovered_records=len(records),
                        processed_records=processed,
                        media_candidates=len(records),
                        media_captured=processed,
                    ),
                )
        return failures

    async def reanalyze_record(self, record_key: str) -> StoredResearchRecord:
        """Retry capture and automatic analysis for one quarantined reference."""
        if self._screener is None:
            raise RuntimeError("Automatic research analysis is not configured")
        stored = await self._repository.get_record(record_key)
        if stored is None:
            raise ValueError("Research record does not exist")
        job = await self._repository.get(stored.latest_run_id)
        if job is None:
            raise ValueError("Research crawl job does not exist")
        if not any(asset.status == "available" for asset in stored.media_assets):
            if self._media_capturer is None:
                raise RuntimeError("Research media capture is not configured")
            assets = await self._media_capturer.capture(
                record_key=record_key,
                brand_id=stored.brand_id,
                image_urls=stored.image_urls,
                video_urls=stored.video_urls,
                existing=stored.media_assets,
            )
            stored = await self._repository.save_record_enrichment(
                record_key,
                media_assets=assets,
            )
        brand_context = await self._resolve_brand_context(job)
        screening = await self._screener.screen(stored, brand_context=brand_context)
        return await self._repository.save_record_enrichment(
            record_key,
            screening=screening,
        )

    async def _record_progress(self, job_id: str, progress: ResearchCrawlProgress) -> None:
        job = await self._repository.get(job_id)
        if job is None:
            return
        current = job.progress
        merged = current.model_copy(
            update={
                "phase": progress.phase,
                "discovered_records": max(current.discovered_records, progress.discovered_records),
                "processed_records": max(current.processed_records, progress.processed_records),
                "source_records_discovered": max(
                    current.source_records_discovered,
                    progress.source_records_discovered,
                ),
                "media_candidates": max(current.media_candidates, progress.media_candidates),
                "duplicate_records": max(current.duplicate_records, progress.duplicate_records),
                "media_captured": max(current.media_captured, progress.media_captured),
                "media_analysis_completed": max(
                    current.media_analysis_completed,
                    progress.media_analysis_completed,
                ),
                "accepted_records": max(current.accepted_records, progress.accepted_records),
                "rejected_records": max(current.rejected_records, progress.rejected_records),
                "auto_filtered_records": max(
                    current.auto_filtered_records, progress.auto_filtered_records
                ),
                "analysis_unavailable_records": max(
                    current.analysis_unavailable_records,
                    progress.analysis_unavailable_records,
                ),
                "image_count": max(current.image_count, progress.image_count),
                "video_count": max(current.video_count, progress.video_count),
                "scroll_count": max(current.scroll_count, progress.scroll_count),
                "expected_records": progress.expected_records or current.expected_records,
                "stop_reason": progress.stop_reason or current.stop_reason,
                "navigation_step": max(current.navigation_step, progress.navigation_step),
                "navigation_action": (progress.navigation_action or current.navigation_action),
                "navigation_confidence": (
                    progress.navigation_confidence
                    if progress.navigation_confidence is not None
                    else current.navigation_confidence
                ),
            }
        )
        await self._repository.save(
            job.model_copy(update={"progress": merged, "updated_at": datetime.now(UTC)})
        )

    async def record_error(
        self,
        job_id: str,
        *,
        status: ResearchCrawlStatus,
        code: str,
        message: str,
    ) -> None:
        job = await self._repository.get(job_id)
        if job is None:
            return
        await self._repository.save(
            job.model_copy(
                update={
                    "status": status,
                    "progress": job.progress.model_copy(
                        update={"phase": "failed" if status == "failed" else job.progress.phase}
                    ),
                    "error_code": code,
                    "error_message": message[:500],
                    "updated_at": datetime.now(UTC),
                }
            )
        )


def _image_fingerprints(record: StoredResearchRecord) -> list[MediaFingerprint]:
    return [
        MediaFingerprint(
            record_key=record.record_key,
            sha256=asset.sha256,
            perceptual_hash=asset.perceptual_hash,
        )
        for asset in record.media_assets
        if asset.media_kind == "image" and asset.status == "available"
    ]


def _duplicate_of(own: list[MediaFingerprint], known: list[MediaFingerprint]) -> str | None:
    """Return the record that already shows the same picture, if there is one."""

    for mine in own:
        for other in known:
            if other.record_key == mine.record_key:
                continue
            same_file = mine.sha256 is not None and mine.sha256 == other.sha256
            same_picture = (
                mine.perceptual_hash is not None
                and other.perceptual_hash is not None
                and is_duplicate_hash(mine.perceptual_hash, other.perceptual_hash)
            )
            if same_file or same_picture:
                return other.record_key
    return None


def _candidate_record(
    job: ResearchCrawlJob,
    record: ResearchCrawlRecord,
    platform: str,
) -> StoredResearchRecord:
    now = datetime.now(UTC)
    content_hash = research_record_content_hash(record)
    destination = next(
        (
            urlsplit(link["url"]).hostname
            for link in record.links
            if urlsplit(link["url"]).hostname
            and not (urlsplit(link["url"]).hostname or "").endswith("facebook.com")
        ),
        None,
    )
    return StoredResearchRecord(
        record_key=research_record_key(
            workspace_id=job.workspace_id,
            brand_id=job.brand_id,
            platform=platform,
            external_id=record.record_id,
        ),
        workspace_id=job.workspace_id,
        brand_id=job.brand_id,
        platform=platform,
        external_id=record.record_id,
        record_type=record.record_type,
        title=record.title,
        text=record.text,
        source_url=record.source_url,
        advertiser=record.title,
        destination_domain=destination,
        metadata={
            **record.metadata,
            **({"research_focus": job.project_id} if job.project_id else {}),
        },
        links=record.links,
        image_urls=record.image_urls,
        video_urls=record.video_urls,
        content_hash=content_hash,
        first_seen_at=now,
        last_seen_at=now,
        latest_run_id=job.job_id,
    )


def _accepted_extraction(
    extracted: dict[str, Any],
    records: list[ResearchCrawlRecord],
) -> dict[str, Any]:
    accepted = dict(extracted)
    accepted["records"] = records
    accepted["text"] = "\n".join(record.text for record in records if record.text)
    accepted["links"] = _unique_links(record.links for record in records)
    accepted["image_urls"] = list(
        dict.fromkeys(url for record in records for url in record.image_urls)
    )
    accepted["video_urls"] = list(
        dict.fromkeys(url for record in records for url in record.video_urls)
    )
    return accepted


def _media_reference_records(
    extracted: dict[str, Any],
    media_mode: str,
) -> list[ResearchCrawlRecord]:
    """Turn discovered media into one minimal candidate per selected image or video."""
    candidates: list[ResearchCrawlRecord] = []
    seen: dict[str, int] = {}
    page_url = str(extracted.get("final_url") or "")
    source_records = [
        item for item in extracted.get("records", []) if isinstance(item, ResearchCrawlRecord)
    ]

    def add(kind: str, url: str, source_url: str | None) -> None:
        stable_url = canonicalize_media_url(url)
        identity = f"{kind}:{stable_url}"
        if not stable_url:
            return
        if identity in seen:
            return
        seen[identity] = len(candidates)
        candidates.append(
            ResearchCrawlRecord(
                record_id=f"{kind}_{hashlib.sha256(stable_url.encode()).hexdigest()[:32]}",
                record_type=f"{kind}_reference",
                source_url=source_url or page_url or None,
                image_urls=[url] if kind == "image" else [],
                video_urls=[url] if kind == "video" else [],
            )
        )

    for record in source_records:
        if media_mode in {"images", "images_and_videos"}:
            for image_url in record.image_urls:
                add("image", image_url, record.source_url)
        if media_mode in {"videos", "images_and_videos"}:
            for video_url in record.video_urls:
                add("video", video_url, record.source_url)
    if media_mode in {"images", "images_and_videos"}:
        for image_url in extracted.get("image_urls", []):
            if isinstance(image_url, str):
                add("image", image_url, page_url)
    if media_mode in {"videos", "images_and_videos"}:
        for video_url in extracted.get("video_urls", []):
            if isinstance(video_url, str):
                add("video", video_url, page_url)
    return candidates


def _media_candidate_occurrences(extracted: dict[str, Any], media_mode: str) -> int:
    urls: set[str] = set()
    source_records = [
        item for item in extracted.get("records", []) if isinstance(item, ResearchCrawlRecord)
    ]
    if media_mode in {"images", "images_and_videos"}:
        urls.update(f"image:{url}" for record in source_records for url in record.image_urls)
        urls.update(
            f"image:{url}" for url in extracted.get("image_urls", []) if isinstance(url, str)
        )
    if media_mode in {"videos", "images_and_videos"}:
        urls.update(f"video:{url}" for record in source_records for url in record.video_urls)
        urls.update(
            f"video:{url}" for url in extracted.get("video_urls", []) if isinstance(url, str)
        )
    return len(urls)


def _unique_links(groups: Any) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for link in group:
            url = link.get("url", "")
            if url and url not in seen:
                seen.add(url)
                links.append(link)
    return links


__all__ = ["ResearchCrawlService"]
