"""Business-facing AI usage and provider-reported cost API."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ai_content.platform.ai_usage import AIUsageFilters, AIUsageRepository, AIUsageStatus

from .dependencies import get_ai_usage_repository
from .schemas.ai_usage import (
    AIUsageEventPageResponse,
    AIUsageEventResponse,
    AIUsageRunPageResponse,
    AIUsageSummaryResponse,
)

router = APIRouter(prefix="/api/v1/ai-usage", tags=["ai-usage"])


@router.get("/summary", response_model=AIUsageSummaryResponse)
async def get_ai_usage_summary(
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    workstream: str | None = None,
    model: str | None = None,
    brand_id: str | None = None,
    operation: str | None = None,
    backend: str | None = None,
    status: AIUsageStatus | None = None,
    cost_state: Literal["priced", "unpriced"] | None = None,
    correlation_id: str | None = None,
    repository: AIUsageRepository = Depends(get_ai_usage_repository),
) -> AIUsageSummaryResponse:
    start, end = _range(from_time, to_time)
    summary = await repository.summary(
        _filters(
            start,
            end,
            workstream=workstream,
            model=model,
            brand_id=brand_id,
            operation=operation,
            backend=backend,
            status=status,
            cost_state=cost_state,
            correlation_id=correlation_id,
        )
    )
    return AIUsageSummaryResponse(
        **summary.__dict__,
        from_time=start,
        to_time=end,
    )


@router.get("/events", response_model=AIUsageEventPageResponse)
async def list_ai_usage_events(
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    workstream: str | None = None,
    model: str | None = None,
    brand_id: str | None = None,
    operation: str | None = None,
    backend: str | None = None,
    status: AIUsageStatus | None = None,
    cost_state: Literal["priced", "unpriced"] | None = None,
    correlation_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: AIUsageRepository = Depends(get_ai_usage_repository),
) -> AIUsageEventPageResponse:
    start, end = _range(from_time, to_time)
    page = await repository.list_events(
        _filters(
            start,
            end,
            workstream=workstream,
            model=model,
            brand_id=brand_id,
            operation=operation,
            backend=backend,
            status=status,
            cost_state=cost_state,
            correlation_id=correlation_id,
        ),
        limit=limit,
        offset=offset,
    )
    return AIUsageEventPageResponse.model_validate(page)


@router.get("/events/{event_id}", response_model=AIUsageEventResponse)
async def get_ai_usage_event(
    event_id: str,
    repository: AIUsageRepository = Depends(get_ai_usage_repository),
) -> AIUsageEventResponse:
    event = await repository.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="AI usage event not found")
    return AIUsageEventResponse.model_validate(event)


@router.get("/runs", response_model=AIUsageRunPageResponse)
async def list_ai_usage_runs(
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    workstream: str | None = None,
    model: str | None = None,
    brand_id: str | None = None,
    operation: str | None = None,
    backend: str | None = None,
    status: AIUsageStatus | None = None,
    cost_state: Literal["priced", "unpriced"] | None = None,
    correlation_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: AIUsageRepository = Depends(get_ai_usage_repository),
) -> AIUsageRunPageResponse:
    start, end = _range(from_time, to_time)
    page = await repository.list_runs(
        _filters(
            start,
            end,
            workstream=workstream,
            model=model,
            brand_id=brand_id,
            operation=operation,
            backend=backend,
            status=status,
            cost_state=cost_state,
            correlation_id=correlation_id,
        ),
        limit=limit,
        offset=offset,
    )
    return AIUsageRunPageResponse.model_validate(page)


def _range(from_time: datetime | None, to_time: datetime | None) -> tuple[datetime, datetime]:
    end = _utc(to_time or datetime.now(UTC))
    start = _utc(from_time or end - timedelta(days=30))
    if start >= end:
        raise HTTPException(status_code=422, detail="from must be earlier than to")
    return start, end


def _filters(
    from_time: datetime,
    to_time: datetime,
    *,
    workstream: str | None,
    model: str | None,
    brand_id: str | None,
    operation: str | None,
    backend: str | None,
    status: AIUsageStatus | None,
    cost_state: Literal["priced", "unpriced"] | None,
    correlation_id: str | None,
) -> AIUsageFilters:
    return AIUsageFilters(
        from_time,
        to_time,
        workstream,
        model,
        brand_id,
        operation,
        backend,
        status,
        cost_state,
        correlation_id,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["router"]
