"""SQLite persistence for local AI usage tracking and dashboard development."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

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

_AGGREGATE_SQL = """
COUNT(*) AS attempts,
SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
SUM(CASE WHEN status = 'started' THEN 1 ELSE 0 END) AS incomplete,
COALESCE(SUM(request_count), 0) AS request_count,
COALESCE(SUM(input_tokens), 0) AS input_tokens,
COALESCE(SUM(output_tokens), 0) AS output_tokens,
COALESCE(SUM(output_count), 0) AS output_count,
COALESCE(SUM(output_bytes), 0) AS output_bytes,
SUM(CASE WHEN input_tokens IS NOT NULL OR output_tokens IS NOT NULL THEN 1 ELSE 0 END) AS token_reported_attempts,
SUM(CASE WHEN duration_ms IS NOT NULL THEN 1 ELSE 0 END) AS duration_reported_attempts,
COALESCE(SUM(duration_ms), 0) AS total_duration_ms,
SUM(CASE WHEN run_id IS NOT NULL OR workflow_run_id IS NOT NULL OR job_id IS NOT NULL OR source_run_id IS NOT NULL OR version_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_attempts,
SUM(CASE WHEN cost_amount IS NULL THEN 1 ELSE 0 END) AS unpriced_attempts
"""


class SqliteAIUsageRepository:
    def __init__(self, db_path: Path) -> None:
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_usage_events (
                event_id TEXT PRIMARY KEY, workstream TEXT NOT NULL, operation TEXT NOT NULL,
                backend TEXT NOT NULL, model TEXT NOT NULL, model_revision TEXT,
                status TEXT NOT NULL, request_count INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER, output_tokens INTEGER, output_count INTEGER,
                output_bytes INTEGER, cost_amount TEXT, cost_currency TEXT, error_code TEXT,
                source_run_id TEXT, workflow_run_id TEXT, job_id TEXT, version_id TEXT,
                brand_id TEXT, batch_id TEXT, run_id TEXT, parent_event_id TEXT,
                attempt_number INTEGER, provider_request_id TEXT,
                started_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER,
                CHECK (status IN ('started', 'succeeded', 'failed')),
                CHECK ((cost_amount IS NULL) = (cost_currency IS NULL)),
                CHECK (attempt_number IS NULL OR attempt_number > 0)
            );
            CREATE INDEX IF NOT EXISTS ix_ai_usage_started_at ON ai_usage_events(started_at);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_workstream_time ON ai_usage_events(workstream, started_at);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_model_time ON ai_usage_events(model, started_at);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_workflow ON ai_usage_events(workflow_run_id);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_job ON ai_usage_events(job_id);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_batch ON ai_usage_events(batch_id);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_run ON ai_usage_events(run_id, started_at);
            CREATE INDEX IF NOT EXISTS ix_ai_usage_status ON ai_usage_events(status);
            """
        )
        self._ensure_columns()
        self._connection.execute(
            """
            UPDATE ai_usage_events
            SET run_id = COALESCE(workflow_run_id, job_id, source_run_id, version_id)
            WHERE run_id IS NULL
            """
        )
        self._connection.commit()

    def _ensure_columns(self) -> None:
        existing = {
            row["name"] for row in self._connection.execute("PRAGMA table_info(ai_usage_events)")
        }
        for name, type_name in (
            ("batch_id", "TEXT"),
            ("run_id", "TEXT"),
            ("parent_event_id", "TEXT"),
            ("attempt_number", "INTEGER"),
            ("provider_request_id", "TEXT"),
        ):
            if name not in existing:
                self._connection.execute(
                    f"ALTER TABLE ai_usage_events ADD COLUMN {name} {type_name}"
                )

    def close(self) -> None:
        self._connection.close()

    async def start(self, event_id: str, usage: AIUsageStart) -> AIUsageEvent:
        values = {
            **usage.__dict__,
            "started_at": usage.started_at.isoformat(),
            "status": "started",
            "request_count": 0,
        }
        columns = ", ".join(("event_id", *values))
        placeholders = ", ".join("?" for _ in range(len(values) + 1))
        self._connection.execute(
            f"INSERT INTO ai_usage_events ({columns}) VALUES ({placeholders})",
            (event_id, *values.values()),
        )
        self._connection.commit()
        return AIUsageEvent(
            event_id=event_id,
            **usage.__dict__,
            status="started",
            request_count=0,
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
        values["cost_amount"] = str(values["cost_amount"]) if "cost_amount" in values else None
        if values["cost_amount"] is None:
            values.pop("cost_amount", None)
        started = self._connection.execute(
            "SELECT started_at FROM ai_usage_events WHERE event_id = ? AND status = 'started'",
            (event_id,),
        ).fetchone()
        if started is None:
            raise RuntimeError("AI usage event is missing or already completed")
        duration_ms = round(
            (completed_at - datetime.fromisoformat(started["started_at"])).total_seconds() * 1000
        )
        updates = {
            **values,
            "status": status,
            "error_code": error_code,
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
        }
        assignments = ", ".join(f"{key} = ?" for key in updates)
        cursor = self._connection.execute(
            f"UPDATE ai_usage_events SET {assignments} WHERE event_id = ? AND status = 'started'",
            (*updates.values(), event_id),
        )
        self._connection.commit()
        if cursor.rowcount != 1:
            raise RuntimeError("AI usage event is missing or already completed")

    async def summary(self, filters: AIUsageFilters) -> AIUsageSummary:
        where, params = _where(filters)
        total = self._connection.execute(
            f"SELECT {_AGGREGATE_SQL} FROM ai_usage_events WHERE {where}", params
        ).fetchone()
        costs = self._costs(where, params)
        durations = [
            row["duration_ms"]
            for row in self._connection.execute(
                f"SELECT duration_ms FROM ai_usage_events WHERE {where} AND duration_ms IS NOT NULL ORDER BY duration_ms",
                params,
            ).fetchall()
        ]
        failures = self._connection.execute(
            f"SELECT * FROM ai_usage_events WHERE {where} AND status = 'failed' ORDER BY started_at DESC LIMIT 10",
            params,
        ).fetchall()
        return AIUsageSummary(
            **_aggregate_dict(total),
            p50_duration_ms=percentile_duration(durations, 0.5),
            p95_duration_ms=percentile_duration(durations, 0.95),
            costs=costs,
            by_model=self._grouped("model", where, params),
            by_workstream=self._grouped("workstream", where, params),
            by_operation=self._grouped("operation", where, params),
            by_backend=self._grouped("backend", where, params),
            by_day=self._grouped("date(started_at)", where, params),
            recent_failures=tuple(_event(row) for row in failures),
        )

    async def list_events(
        self, filters: AIUsageFilters, *, limit: int, offset: int
    ) -> AIUsageEventPage:
        where, params = _where(filters)
        total = self._connection.execute(
            f"SELECT COUNT(*) AS total FROM ai_usage_events WHERE {where}", params
        ).fetchone()["total"]
        rows = self._connection.execute(
            f"SELECT * FROM ai_usage_events WHERE {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return AIUsageEventPage(
            items=tuple(_event(row) for row in rows), total=total, limit=limit, offset=offset
        )

    async def get_event(self, event_id: str) -> AIUsageEvent | None:
        row = self._connection.execute(
            "SELECT * FROM ai_usage_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return _event(row) if row is not None else None

    async def list_runs(
        self, filters: AIUsageFilters, *, limit: int, offset: int
    ) -> AIUsageRunPage:
        where, params = _where(filters)
        rows = self._connection.execute(
            f"SELECT * FROM ai_usage_events WHERE {where} AND run_id IS NOT NULL ORDER BY started_at DESC",
            params,
        ).fetchall()
        runs = build_usage_runs(_event(row) for row in rows)
        return AIUsageRunPage(
            items=runs[offset : offset + limit], total=len(runs), limit=limit, offset=offset
        )

    def _grouped(
        self, expression: str, where: str, params: tuple[object, ...]
    ) -> tuple[AIUsageBreakdown, ...]:
        rows = self._connection.execute(
            f"SELECT {expression} AS key, {_AGGREGATE_SQL} FROM ai_usage_events WHERE {where} GROUP BY {expression} ORDER BY {expression}",
            params,
        ).fetchall()
        return tuple(
            AIUsageBreakdown(
                key=str(row["key"]),
                **_aggregate_dict(row),
                costs=self._costs(f"{where} AND {expression} = ?", (*params, row["key"])),
            )
            for row in rows
        )

    def _costs(self, where: str, params: tuple[object, ...]) -> tuple[AIUsageCost, ...]:
        rows = self._connection.execute(
            f"SELECT cost_currency, cost_amount FROM ai_usage_events WHERE {where} AND cost_amount IS NOT NULL",
            params,
        ).fetchall()
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for row in rows:
            totals[row["cost_currency"]] += Decimal(row["cost_amount"])
        return tuple(AIUsageCost(currency, amount) for currency, amount in sorted(totals.items()))


def _where(filters: AIUsageFilters) -> tuple[str, tuple[object, ...]]:
    clauses = ["started_at >= ?", "started_at < ?"]
    params: list[object] = [filters.from_time.isoformat(), filters.to_time.isoformat()]
    for column, value in (
        ("workstream", filters.workstream),
        ("model", filters.model),
        ("brand_id", filters.brand_id),
        ("operation", filters.operation),
        ("backend", filters.backend),
        ("status", filters.status),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if filters.cost_state == "priced":
        clauses.append("cost_amount IS NOT NULL")
    if filters.cost_state == "unpriced":
        clauses.append("cost_amount IS NULL")
    if filters.correlation_id:
        clauses.append(
            "(batch_id = ? OR run_id = ? OR workflow_run_id = ? OR job_id = ? OR source_run_id = ? OR version_id = ?)"
        )
        params.extend([filters.correlation_id] * 6)
    return " AND ".join(clauses), tuple(params)


def _aggregate_dict(row: sqlite3.Row) -> dict[str, int]:
    return {
        key: int(row[key] or 0)
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


def _event(row: sqlite3.Row) -> AIUsageEvent:
    values = dict(row)
    for key in ("started_at", "completed_at"):
        if values[key] is not None:
            values[key] = datetime.fromisoformat(values[key])
    if values["cost_amount"] is not None:
        values["cost_amount"] = Decimal(values["cost_amount"])
    return AIUsageEvent(**values)


__all__ = ["SqliteAIUsageRepository"]
