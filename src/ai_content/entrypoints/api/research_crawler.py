"""Public web research crawl API for Marketing workspaces."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from ai_content.domains.marketing.research_crawler.commands import crawl_url_command
from ai_content.domains.marketing.research_crawler.identity import crawl_fingerprint
from ai_content.domains.marketing.research_crawler.models import (
    ResearchCrawlJob,
    ResearchRecordQuery,
)
from ai_content.domains.marketing.research_crawler.repositories import (
    PostgresResearchCrawlRepository,
)
from ai_content.domains.marketing.research_crawler.repository import (
    ResearchCrawlRepository,
)
from ai_content.domains.marketing.research_crawler.service import ResearchCrawlService
from ai_content.platform.execution import CeleryCommandScheduler, CommandScheduler

from .dependencies import (
    get_command_scheduler,
    get_research_crawl_repository,
    get_research_crawl_service,
    get_runtime_settings,
)
from .schemas.research_crawler import (
    ResearchCrawlCreateRequest,
    ResearchCrawlJobResponse,
    ResearchCrawlListResponse,
    ResearchKeywordSuggestionListResponse,
    ResearchRecordBulkReviewRequest,
    ResearchRecordBulkReviewResponse,
    ResearchRecordDeleteRequest,
    ResearchRecordDeleteResponse,
    ResearchRecordDetailResponse,
    ResearchRecordPageResponse,
    ResearchRecordReviewRequest,
    StoredResearchRecordResponse,
)

router = APIRouter(prefix="/api/v1/marketing/research-crawls")
library_router = APIRouter(prefix="/api/v1/marketing/research-records")


@router.post("", response_model=ResearchCrawlJobResponse, status_code=status.HTTP_201_CREATED)
async def create_research_crawl(
    payload: ResearchCrawlCreateRequest,
    response: Response,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
    service: ResearchCrawlService = Depends(get_research_crawl_service),
    scheduler: CommandScheduler = Depends(get_command_scheduler),
) -> ResearchCrawlJobResponse:
    """Create a crawl job, reusing an identical request that is already active."""
    fingerprint = crawl_fingerprint(
        workspace_id=payload.workspace_id,
        brand_id=payload.brand_id,
        project_id=payload.project_id,
        source_url=payload.source_url,
        media_mode=payload.media_mode,
        analysis_model_id=payload.analysis_model_id,
    )
    active = await repository.find_active_by_fingerprint(fingerprint)
    if active is not None:
        response.status_code = status.HTTP_200_OK
        return ResearchCrawlJobResponse.model_validate(active, from_attributes=True)

    now = datetime.now(UTC)
    job = ResearchCrawlJob(
        job_id=f"crawl_{uuid4().hex}",
        workspace_id=payload.workspace_id,
        brand_id=payload.brand_id,
        project_id=payload.project_id,
        source_url=payload.source_url,
        media_mode=payload.media_mode,
        analysis_model_id=payload.analysis_model_id,
        crawl_fingerprint=fingerprint,
        status="queued",
        created_at=now,
        updated_at=now,
    )
    settings = get_runtime_settings()
    if settings.execution_backend == "celery":
        if not isinstance(repository, PostgresResearchCrawlRepository) or not isinstance(
            scheduler, CeleryCommandScheduler
        ):
            raise HTTPException(
                status_code=503,
                detail="Research crawling requires PostgreSQL when Celery is enabled",
            )
        try:
            queued = await repository.create_with_command(job, crawl_url_command(job.job_id))
        except IntegrityError:
            active = await repository.find_active_by_fingerprint(fingerprint)
            if active is None:
                raise
            response.status_code = status.HTTP_200_OK
            return ResearchCrawlJobResponse.model_validate(active, from_attributes=True)
        response.status_code = status.HTTP_202_ACCEPTED
        return ResearchCrawlJobResponse.model_validate(queued, from_attributes=True)

    try:
        await repository.create(job)
    except (IntegrityError, sqlite3.IntegrityError):
        active = await repository.find_active_by_fingerprint(fingerprint)
        if active is None:
            raise
        response.status_code = status.HTTP_200_OK
        return ResearchCrawlJobResponse.model_validate(active, from_attributes=True)
    try:
        await service.execute(job.job_id)
    except ValueError as error:
        await service.record_error(
            job.job_id,
            status="failed",
            code="INVALID_RESEARCH_SOURCE",
            message=str(error),
        )
    except Exception:
        await service.record_error(
            job.job_id,
            status="failed",
            code="RESEARCH_CRAWL_FAILED",
            message="The public page could not be fetched",
        )
    stored = await repository.get(job.job_id)
    if stored is None:
        raise RuntimeError("Research crawl job disappeared after execution")
    return ResearchCrawlJobResponse.model_validate(stored, from_attributes=True)


@router.get("", response_model=ResearchCrawlListResponse)
async def list_research_crawls(
    workspace_id: str | None = Query(default=None, min_length=1),
    brand_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> ResearchCrawlListResponse:
    jobs = await repository.list(limit=limit)
    filtered = [
        job
        for job in jobs
        if (workspace_id is None or job.workspace_id == workspace_id)
        and (brand_id is None or job.brand_id == brand_id)
    ]
    return ResearchCrawlListResponse(
        items=[
            ResearchCrawlJobResponse.model_validate(job, from_attributes=True) for job in filtered
        ],
        total=len(filtered),
    )


@router.get("/keyword-suggestions", response_model=ResearchKeywordSuggestionListResponse)
async def list_research_keyword_suggestions(
    brand_id: str = Query(min_length=1, max_length=120),
) -> ResearchKeywordSuggestionListResponse:
    """Return the curated short terms Marketing uses to find reference material."""
    settings = get_runtime_settings()
    suggestions = _load_reference_keywords(settings.config_dir, brand_id)
    return ResearchKeywordSuggestionListResponse(
        brand_id=brand_id.strip(),
        items=[{"keyword": keyword} for keyword in suggestions],
    )


@router.get("/{job_id}", response_model=ResearchCrawlJobResponse)
async def get_research_crawl(
    job_id: str,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> ResearchCrawlJobResponse:
    job = await repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Research crawl job not found")
    return ResearchCrawlJobResponse.model_validate(job, from_attributes=True)


@library_router.get("", response_model=ResearchRecordPageResponse)
async def list_research_records(
    workspace_id: str | None = Query(default=None, min_length=1),
    brand_id: str | None = Query(default=None, min_length=1),
    project_id: str | None = Query(default=None, min_length=1),
    platform: str | None = Query(default=None, min_length=1),
    record_status: str | None = Query(default=None, alias="status", min_length=1),
    review_status: str | None = Query(
        default=None,
        pattern="^(pending_review|approved|rejected)$",
    ),
    screening_status: Literal["visible", "auto_filtered", "unavailable", "all"] = Query(
        default="visible"
    ),
    media_type: str = Query(default="all", pattern="^(all|image|video|mixed|none)$"),
    media_status: str = Query(default="all", pattern="^(all|available|failed|source_only)$"),
    category: str | None = Query(default=None, min_length=1),
    query: str | None = Query(default=None, alias="q", min_length=1),
    sort: str = Query(
        default="last_seen_desc",
        pattern="^(last_seen_desc|first_seen_desc|title_asc)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=48, ge=1, le=100),
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> ResearchRecordPageResponse:
    await repository.backfill_records()
    result = await repository.search_records(
        ResearchRecordQuery(
            workspace_id=workspace_id,
            brand_id=brand_id,
            project_id=project_id,
            platform=platform,
            status=record_status,
            review_status=review_status,
            screening_status=screening_status,
            media_type=media_type,
            media_status=media_status,
            category=category,
            query=query,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    )
    return ResearchRecordPageResponse.model_validate(result, from_attributes=True)


@library_router.get("/export")
async def export_research_records(
    workspace_id: str | None = Query(default=None),
    brand_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    record_status: str | None = Query(default=None, alias="status"),
    review_status: str | None = Query(
        default=None,
        pattern="^(pending_review|approved|rejected)$",
    ),
    screening_status: Literal["visible", "auto_filtered", "unavailable", "all"] = Query(
        default="visible"
    ),
    media_type: str = Query(default="all", pattern="^(all|image|video|mixed|none)$"),
    media_status: str = Query(default="all", pattern="^(all|available|failed|source_only)$"),
    category: str | None = Query(default=None),
    query: str | None = Query(default=None, alias="q"),
    sort: str = Query(
        default="last_seen_desc",
        pattern="^(last_seen_desc|first_seen_desc|title_asc)$",
    ),
    export_format: str = Query(default="csv", alias="format", pattern="^(csv|json)$"),
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> Response:
    await repository.backfill_records()
    items: list[dict[str, object]] = []
    page = 1
    while len(items) < 10_000:
        result = await repository.search_records(
            ResearchRecordQuery(
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                platform=platform,
                status=record_status,
                review_status=review_status,
                screening_status=screening_status,
                media_type=media_type,
                media_status=media_status,
                category=category,
                query=query,
                sort=sort,
                page=page,
                page_size=100,
            )
        )
        items.extend(item.model_dump(mode="json") for item in result.items)
        if not result.items or len(items) >= result.total:
            break
        page += 1
    if export_format == "json":
        return Response(
            json.dumps(items, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="research-records.json"'},
        )
    output = io.StringIO()
    fields = [
        "record_key",
        "platform",
        "external_id",
        "title",
        "status",
        "screening_status",
        "usable",
        "ai_summary",
        "project_relevance",
        "screening_reason",
        "screening_confidence",
        "review_status",
        "reviewer_alias",
        "reviewed_at",
        "review_reason",
        "advertiser",
        "destination_domain",
        "text",
        "image_count",
        "video_count",
        "last_seen_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in items:
        writer.writerow(
            {
                key: value
                for key, value in {
                    **item,
                    "usable": (item["screening"]["usable"] if item.get("screening") else None),
                    "ai_summary": (
                        (item["screening"].get("profile") or {}).get("summary")
                        if item.get("screening")
                        else None
                    ),
                    "project_relevance": (
                        (item["screening"].get("profile") or {}).get("relevance_to_project")
                        if item.get("screening")
                        else None
                    ),
                    "screening_reason": (
                        item["screening"]["reason"] if item.get("screening") else None
                    ),
                    "screening_confidence": (
                        item["screening"]["confidence"] if item.get("screening") else None
                    ),
                    "image_count": len(item["image_urls"]),
                    "video_count": len(item["video_urls"]),
                }.items()
                if key in fields
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="research-records.csv"'},
    )


@library_router.post("/review", response_model=ResearchRecordBulkReviewResponse)
async def review_research_records(
    payload: ResearchRecordBulkReviewRequest,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> ResearchRecordBulkReviewResponse:
    await repository.backfill_records()
    records = await _review_records(repository, tuple(payload.record_keys), payload)
    return ResearchRecordBulkReviewResponse(
        items=[
            StoredResearchRecordResponse.model_validate(record, from_attributes=True)
            for record in records
        ],
        total=len(records),
    )


@library_router.post("/delete", response_model=ResearchRecordDeleteResponse)
async def delete_research_records(
    payload: ResearchRecordDeleteRequest,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> ResearchRecordDeleteResponse:
    try:
        deleted = await repository.delete_records(tuple(payload.record_keys))
    except ValueError as error:
        _raise_record_mutation_error(error)
    return ResearchRecordDeleteResponse(deleted=deleted)


@library_router.delete(
    "/{record_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_research_record(
    record_key: str,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> Response:
    try:
        await repository.delete_records((record_key,))
    except ValueError as error:
        _raise_record_mutation_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library_router.post("/{record_key}/review", response_model=StoredResearchRecordResponse)
async def review_research_record(
    record_key: str,
    payload: ResearchRecordReviewRequest,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> StoredResearchRecordResponse:
    await repository.backfill_records()
    records = await _review_records(repository, (record_key,), payload)
    return StoredResearchRecordResponse.model_validate(records[0], from_attributes=True)


@library_router.post("/{record_key}/reanalyze", response_model=StoredResearchRecordResponse)
async def reanalyze_research_record(
    record_key: str,
    service: ResearchCrawlService = Depends(get_research_crawl_service),
) -> StoredResearchRecordResponse:
    try:
        record = await service.reanalyze_record(record_key)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return StoredResearchRecordResponse.model_validate(record, from_attributes=True)


@library_router.get("/{record_key}", response_model=ResearchRecordDetailResponse)
async def get_research_record(
    record_key: str,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
) -> ResearchRecordDetailResponse:
    record = await repository.get_record(record_key)
    if record is None:
        raise HTTPException(status_code=404, detail="Research record not found")
    versions = await repository.list_record_versions(record_key)
    return ResearchRecordDetailResponse.model_validate(
        {"record": record, "versions": versions}, from_attributes=True
    )


async def _review_records(
    repository: ResearchCrawlRepository,
    record_keys: tuple[str, ...],
    payload: ResearchRecordReviewRequest,
):
    review_status = {
        "approve": "approved",
        "reject": "rejected",
        "review_later": "pending_review",
    }[payload.decision]
    try:
        return await repository.review_records(
            record_keys,
            review_status=review_status,
            reviewer_alias=payload.reviewer_alias,
            review_reason=payload.reason,
        )
    except ValueError as error:
        _raise_record_mutation_error(error)


def _raise_record_mutation_error(error: ValueError) -> None:
    detail = str(error)
    status_code = 404 if "do not exist" in detail else 409 if "used by Creative" in detail else 400
    raise HTTPException(status_code=status_code, detail=detail) from error


def _load_reference_keywords(config_dir: Path, brand_id: str) -> tuple[str, ...]:
    path = config_dir / "research" / "reference_keywords.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    brands = payload.get("brands")
    if not isinstance(brands, dict):
        raise ValueError("Research keyword config must contain a brands object")
    requested = brand_id.strip().casefold()
    for configured_brand, values in brands.items():
        if str(configured_brand).casefold() != requested:
            continue
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"Research keywords for {configured_brand} must be strings")
        return tuple(value.strip() for value in values if value.strip())
    return ()


__all__ = ["library_router", "router"]
