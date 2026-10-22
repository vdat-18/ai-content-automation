"""PostgreSQL persistence and SQL aggregation for AI usage events."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import ai_usage_events

from .models import (
    AIUsageBreakdown,
    AIUsageCompletion,
    AIUsageCost,
    AIUsageEvent,
    AIUsageEventPage,
    AIUsageFailure,
    AIUsageFilters,
    AIUsageRunPage,
    AIUsageStart,
    AIUsageSummary,
)
from .reporting import build_usage_runs, percentile_duration


class PostgresAIUsageRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        """The process composition root owns the shared engine."""

    async def start(self, event_id: str, usage: AIUsageStart) -> AIUsageEvent:
        values = {
            "event_id": event_id,
            **usage.__dict__,
            "status": "started",
            "request_count": 0,
        }
        async with self._engine.begin() as connection:
            await connection.execute(ai_usage_events.insert().values(**values))
        return AIUsageEvent(
            **values,
            input_tokens=None,
            output_tokens=None,
            output_count=None,
            output_bytes=None,
            cost_amount=None,
            cost_currency=None,
            error_code=None,
            provider_request_id=None,
            completed_at=None,
            duration_ms=None,
        )

    async def succeed(self, event_id: str, completion: AIUsageCompletion) -> None:
        await self._complete(event_id, "succeeded", dict(completion.__dict__), None)

    async def fail(self, event_id: str, failure: AIUsageFailure) -> None:
        await self._complete(event_id, "failed", dict(failure.__dict__), failure.error_code)

    async def _complete(
        self, event_id: str, status: str, values: dict[str, Any], error_code: str | None
    ) -> None:
        completed_at = values.pop("completed_at")
        values.pop("error_code", None)
        values = {key: value for key, value in values.items() if value is not None}
        statement = (
            update(ai_usage_events)
            .where(ai_usage_events.c.event_id == event_id)
            .where(ai_usage_events.c.status == "started")
            .values(
                **values,
                status=status,
                error_code=error_code,
                completed_at=completed_at,
                duration_ms=func.round(
                    func.extract("epoch", completed_at - ai_usage_events.c.started_at) * 1000
                ),
            )
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        if result.rowcount != 1:
            raise RuntimeError("AI usage event is missing or already completed")

    async def summary(self, filters: AIUsageFilters) -> AIUsageSummary:
        where = _where(filters)
        aggregate = _aggregate_columns()
        async with self._engine.connect() as connection:
            total = (await connection.execute(select(*aggregate).where(*where))).one()
            costs = await _costs(connection, where)
            by_model = await _grouped(connection, filters, ai_usage_events.c.model)
            by_workstream = await _grouped(connection, filters, ai_usage_events.c.workstream)
            by_operation = await _grouped(connection, filters, ai_usage_events.c.operation)
            by_backend = await _grouped(connection, filters, ai_usage_events.c.backend)
            day = func.date(ai_usage_events.c.started_at)
            by_day = await _grouped(connection, filters, day)
            durations = list(
                (
                    await connection.execute(
                        select(ai_usage_events.c.duration_ms)
                        .where(*where, ai_usage_events.c.duration_ms.is_not(None))
                        .order_by(ai_usage_events.c.duration_ms)
                    )
                ).scalars()
            )
            failures = (
                (
                    await connection.execute(
                        select(ai_usage_events)
                        .where(*where, ai_usage_events.c.status == "failed")
                        .order_by(ai_usage_events.c.started_at.desc())
                        .limit(10)
                    )
                )
                .mappings()
                .all()
            )
        return AIUsageSummary(
            **_aggregate_dict(total),
            p50_duration_ms=percentile_duration(durations, 0.5),
            p95_duration_ms=percentile_duration(durations, 0.95),
            costs=costs,
            by_model=by_model,
            by_workstream=by_workstream,
            by_operation=by_operation,
            by_backend=by_backend,
            by_day=by_day,
            recent_failures=tuple(_event(row) for row in failures),
        )

    async def list_events(
        self, filters: AIUsageFilters, *, limit: int, offset: int
    ) -> AIUsageEventPage:
        where = _where(filters)
        async with self._engine.connect() as connection:
            total = (
                await connection.execute(
                    select(func.count()).select_from(ai_usage_events).where(*where)
                )
            ).scalar_one()
            rows = (
                (
                    await connection.execute(
                        select(ai_usage_events)
                        .where(*where)
                        .order_by(ai_usage_events.c.started_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                )
                .mappings()
                .all()
            )
        return AIUsageEventPage(
            items=tuple(_event(row) for row in rows), total=total, limit=limit, offset=offset
        )

    async def get_event(self, event_id: str) -> AIUsageEvent | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(ai_usage_events).where(ai_usage_events.c.event_id == event_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _event(row) if row is not None else None

    async def list_runs(
        self, filters: AIUsageFilters, *, limit: int, offset: int
    ) -> AIUsageRunPage:
        where = (*_where(filters), ai_usage_events.c.run_id.is_not(None))
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ai_usage_events)
                        .where(*where)
                        .order_by(ai_usage_events.c.started_at.desc())
                    )
                )
                .mappings()
                .all()
            )
        runs = build_usage_runs(_event(row) for row in rows)
        return AIUsageRunPage(
            items=runs[offset : offset + limit], total=len(runs), limit=limit, offset=offset
        )


def _where(filters: AIUsageFilters) -> tuple[Any, ...]:
    clauses = [
        ai_usage_events.c.started_at >= filters.from_time,
        ai_usage_events.c.started_at < filters.to_time,
    ]
    if filters.workstream:
        clauses.append(ai_usage_events.c.workstream == filters.workstream)
    if filters.model:
        clauses.append(ai_usage_events.c.model == filters.model)
    if filters.brand_id:
        clauses.append(ai_usage_events.c.brand_id == filters.brand_id)
    if filters.operation:
        clauses.append(ai_usage_events.c.operation == filters.operation)
    if filters.backend:
        clauses.append(ai_usage_events.c.backend == filters.backend)
    if filters.status:
        clauses.append(ai_usage_events.c.status == filters.status)
    if filters.cost_state == "priced":
        clauses.append(ai_usage_events.c.cost_amount.is_not(None))
    if filters.cost_state == "unpriced":
        clauses.append(ai_usage_events.c.cost_amount.is_(None))
    if filters.correlation_id:
        clauses.append(
            or_(
                ai_usage_events.c.batch_id == filters.correlation_id,
                ai_usage_events.c.run_id == filters.correlation_id,
                ai_usage_events.c.workflow_run_id == filters.correlation_id,
                ai_usage_events.c.job_id == filters.correlation_id,
                ai_usage_events.c.source_run_id == filters.correlation_id,
                ai_usage_events.c.version_id == filters.correlation_id,
            )
        )
    return tuple(clauses)


def _aggregate_columns() -> tuple[Any, ...]:
    status = ai_usage_events.c.status
    return (
        func.count().label("attempts"),
        func.sum(case((status == "succeeded", 1), else_=0)).label("succeeded"),
        func.sum(case((status == "failed", 1), else_=0)).label("failed"),
        func.sum(case((status == "started", 1), else_=0)).label("incomplete"),
        func.coalesce(func.sum(ai_usage_events.c.request_count), 0).label("request_count"),
        func.coalesce(func.sum(ai_usage_events.c.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(ai_usage_events.c.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(ai_usage_events.c.output_count), 0).label("output_count"),
        func.coalesce(func.sum(ai_usage_events.c.output_bytes), 0).label("output_bytes"),
        func.sum(
            case(
                (
                    (ai_usage_events.c.input_tokens.is_not(None))
                    | (ai_usage_events.c.output_tokens.is_not(None)),
                    1,
                ),
                else_=0,
            )
        ).label("token_reported_attempts"),
        func.sum(case((ai_usage_events.c.duration_ms.is_not(None), 1), else_=0)).label(
            "duration_reported_attempts"
        ),
        func.coalesce(func.sum(ai_usage_events.c.duration_ms), 0).label("total_duration_ms"),
        func.sum(
            case(
                (
                    or_(
                        ai_usage_events.c.run_id.is_not(None),
                        ai_usage_events.c.workflow_run_id.is_not(None),
                        ai_usage_events.c.job_id.is_not(None),
                        ai_usage_events.c.source_run_id.is_not(None),
                        ai_usage_events.c.version_id.is_not(None),
                    ),
                    1,
                ),
                else_=0,
            )
        ).label("linked_attempts"),
        func.sum(case((ai_usage_events.c.cost_amount.is_(None), 1), else_=0)).label(
            "unpriced_attempts"
        ),
    )


async def _grouped(
    connection: Any, filters: AIUsageFilters, key: Any
) -> tuple[AIUsageBreakdown, ...]:
    rows = (
        await connection.execute(
            select(key.label("key"), *_aggregate_columns())
            .where(*_where(filters))
            .group_by(key)
            .order_by(key)
        )
    ).all()
    cost_rows = (
        await connection.execute(
            select(
                key.label("key"),
                ai_usage_events.c.cost_currency,
                func.sum(ai_usage_events.c.cost_amount).label("amount"),
            )
            .where(*_where(filters), ai_usage_events.c.cost_amount.is_not(None))
            .group_by(key, ai_usage_events.c.cost_currency)
            .order_by(key, ai_usage_events.c.cost_currency)
        )
    ).all()
    costs_by_key: dict[str, list[AIUsageCost]] = {}
    for row in cost_rows:
        costs_by_key.setdefault(str(row.key), []).append(
            AIUsageCost(row.cost_currency, Decimal(row.amount))
        )
    return tuple(
        AIUsageBreakdown(
            key=str(row.key),
            **_aggregate_dict(row),
            costs=tuple(costs_by_key.get(str(row.key), ())),
        )
        for row in rows
    )


async def _costs(connection: Any, where: tuple[Any, ...]) -> tuple[AIUsageCost, ...]:
    rows = (
        await connection.execute(
            select(
                ai_usage_events.c.cost_currency,
                func.sum(ai_usage_events.c.cost_amount).label("amount"),
            )
            .where(*where, ai_usage_events.c.cost_amount.is_not(None))
            .group_by(ai_usage_events.c.cost_currency)
            .order_by(ai_usage_events.c.cost_currency)
        )
    ).all()
    return tuple(AIUsageCost(row.cost_currency, Decimal(row.amount)) for row in rows)


def _aggregate_dict(row: Any) -> dict[str, int]:
    return {
        key: int(getattr(row, key) or 0)
        for key in (
            "attempts",
            "succeeded",
            "failed",
            "incomplete",
            "request_count",
            "input_tokens",
            "output_tokens",
            "output_count",
            "output_bytes",
            "token_reported_attempts",
            "duration_reported_attempts",
            "total_duration_ms",
            "linked_attempts",
            "unpriced_attempts",
        )
    }


def _event(row: Any) -> AIUsageEvent:
    return AIUsageEvent(**dict(row))


__all__ = ["PostgresAIUsageRepository"]
