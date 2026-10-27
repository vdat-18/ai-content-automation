"""Persistence contracts for public web research crawl jobs."""

from __future__ import annotations

from typing import Protocol

from ai_content.platform.execution import EnqueueCommand

from .models import (
    MediaFingerprint,
    ResearchClassification,
    ResearchCrawlJob,
    ResearchCrawlRecord,
    ResearchMediaAsset,
    ResearchRecordPage,
    ResearchRecordQuery,
    ResearchRecordUpsertSummary,
    ResearchRecordVersion,
    ResearchReviewStatus,
    ResearchScreening,
    StoredResearchRecord,
)


class ResearchCrawlRepository(Protocol):
    async def create(self, job: ResearchCrawlJob) -> ResearchCrawlJob: ...

    async def create_with_command(
        self, job: ResearchCrawlJob, command: EnqueueCommand
    ) -> ResearchCrawlJob: ...

    async def save(self, job: ResearchCrawlJob) -> None: ...

    async def get(self, job_id: str) -> ResearchCrawlJob | None: ...

    async def list(self, *, limit: int = 100) -> list[ResearchCrawlJob]: ...

    async def find_active_by_fingerprint(self, fingerprint: str) -> ResearchCrawlJob | None: ...

    async def upsert_records(
        self,
        job: ResearchCrawlJob,
        classifications: dict[str, ResearchClassification] | None = None,
        screenings: dict[str, ResearchScreening] | None = None,
        *,
        records: list[ResearchCrawlRecord] | None = None,
    ) -> ResearchRecordUpsertSummary: ...

    async def backfill_records(self) -> int: ...

    async def search_records(self, query: ResearchRecordQuery) -> ResearchRecordPage: ...

    async def get_record(self, record_key: str) -> StoredResearchRecord | None: ...

    async def save_record_enrichment(
        self,
        record_key: str,
        *,
        media_assets: list[ResearchMediaAsset] | None = None,
        classification: ResearchClassification | None = None,
        screening: ResearchScreening | None = None,
    ) -> StoredResearchRecord: ...

    async def record_reference_uses(
        self, reference_ids: tuple[str, ...], batch_id: str
    ) -> None: ...

    async def reference_use_counts(self, record_keys: tuple[str, ...]) -> dict[str, int]: ...

    async def known_media_fingerprints(
        self, workspace_id: str, brand_id: str, *, exclude_record_key: str
    ) -> list[MediaFingerprint]: ...

    async def review_records(
        self,
        record_keys: tuple[str, ...],
        *,
        review_status: ResearchReviewStatus,
        reviewer_alias: str | None,
        review_reason: str | None,
    ) -> list[StoredResearchRecord]: ...

    async def delete_records(self, record_keys: tuple[str, ...]) -> int: ...

    async def list_record_versions(self, record_key: str) -> list[ResearchRecordVersion]: ...

    def close(self) -> None: ...


__all__ = ["ResearchCrawlRepository"]
