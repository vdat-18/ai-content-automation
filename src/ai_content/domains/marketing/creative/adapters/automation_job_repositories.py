"""SQLite and PostgreSQL adapters for Creative automation monitoring."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.domains.marketing.creative.ports.automation_jobs import (
    CreativeAutomationBatchSnapshot,
    CreativeAutomationEvent,
    CreativeAutomationJobSnapshot,
)
from ai_content.platform.database.schema import (
    creative_automation_batches,
    creative_automation_events,
    creative_automation_jobs,
)
from ai_content.platform.execution import EnqueueCommand
from ai_content.platform.execution.celery_scheduler import enqueue_celery_command
from ai_content.platform.llm_routing import normalize_persisted_agent_model_id

_JOB_ADAPTER = TypeAdapter(CreativeAutomationJobSnapshot)
_BATCH_ADAPTER = TypeAdapter(CreativeAutomationBatchSnapshot)
_EVENT_ADAPTER = TypeAdapter(CreativeAutomationEvent)


def _validate_job_payload(payload: str | dict[str, object]) -> CreativeAutomationJobSnapshot:
    raw_payload = json.loads(payload) if isinstance(payload, str) else payload
    request = raw_payload.get("request")
    if isinstance(request, dict):
        model = request.get("agent_model_id")
        if isinstance(model, str):
            normalized_model = normalize_persisted_agent_model_id(model)
            if normalized_model != model:
                raw_payload = {
                    **raw_payload,
                    "request": {**request, "agent_model_id": normalized_model},
                }
    return _JOB_ADAPTER.validate_python(raw_payload)


class SqliteCreativeAutomationJobRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS creative_automation_batches (
                batch_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS creative_automation_jobs (
                job_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_creative_automation_jobs_batch
                ON creative_automation_jobs(batch_id);
            CREATE INDEX IF NOT EXISTS idx_creative_automation_jobs_status
                ON creative_automation_jobs(status);
            CREATE TABLE IF NOT EXISTS creative_automation_events (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_creative_automation_events_job
                ON creative_automation_events(job_id, created_at);
            """
        )
        self._connection.commit()

    async def create_batch(self, batch, jobs):
        existing = None
        if batch.idempotency_key is not None:
            existing = self._connection.execute(
                "SELECT payload FROM creative_automation_batches WHERE idempotency_key = ?",
                (batch.idempotency_key,),
            ).fetchone()
        if existing is not None:
            recorded = _BATCH_ADAPTER.validate_json(existing["payload"])
            if recorded.batch_id != batch.batch_id:
                raise ValueError("Creative automation batch idempotency payload drifted")
            requested_ids = set(batch.job_ids)
            if not requested_ids.issubset(recorded.job_ids):
                raise ValueError("Creative automation batch idempotency payload drifted")
            replayed = []
            for job_id in batch.job_ids:
                job = await self.get_job(job_id)
                if job is not None:
                    replayed.append(job)
            return tuple(replayed)
        with self._connection:
            self._connection.execute(
                "INSERT INTO creative_automation_batches(batch_id, idempotency_key, payload) VALUES (?, ?, ?)",
                (batch.batch_id, batch.idempotency_key, _dump(_BATCH_ADAPTER, batch)),
            )
            self._connection.executemany(
                "INSERT INTO creative_automation_jobs(job_id, batch_id, status, payload) VALUES (?, ?, ?, ?)",
                [(job.job_id, job.batch_id, job.status, _dump(_JOB_ADAPTER, job)) for job in jobs],
            )
        return jobs

    async def save_job(self, job, event=None) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE creative_automation_jobs SET status = ?, payload = ? WHERE job_id = ?",
                (job.status, _dump(_JOB_ADAPTER, job), job.job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Creative automation job does not exist")
            if event is not None:
                self._connection.execute(
                    "INSERT OR IGNORE INTO creative_automation_events(event_id, job_id, created_at, payload) VALUES (?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.job_id,
                        event.created_at.isoformat(),
                        _dump(_EVENT_ADAPTER, event),
                    ),
                )

    async def add_event(self, event) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO creative_automation_events(event_id, job_id, created_at, payload) VALUES (?, ?, ?, ?)",
                (
                    event.event_id,
                    event.job_id,
                    event.created_at.isoformat(),
                    _dump(_EVENT_ADAPTER, event),
                ),
            )

    async def get_job(self, job_id: str):
        row = self._connection.execute(
            "SELECT payload FROM creative_automation_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _validate_job_payload(row["payload"]) if row is not None else None

    async def list_jobs(self):
        rows = self._connection.execute(
            "SELECT payload FROM creative_automation_jobs ORDER BY rowid DESC"
        ).fetchall()
        return [_validate_job_payload(row["payload"]) for row in rows]

    async def list_events(self, job_id: str):
        rows = self._connection.execute(
            "SELECT payload FROM creative_automation_events WHERE job_id = ? ORDER BY created_at",
            (job_id,),
        ).fetchall()
        return [_EVENT_ADAPTER.validate_json(row["payload"]) for row in rows]

    def close(self) -> None:
        self._connection.close()


class PostgresCreativeAutomationJobRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_batch(self, batch, jobs):
        async with self._engine.begin() as connection:
            created = (
                await connection.execute(
                    insert(creative_automation_batches)
                    .values(
                        batch_id=batch.batch_id,
                        idempotency_key=batch.idempotency_key,
                        brand_id=batch.brand_id,
                        requested_by=batch.requested_by,
                        payload=_dump_python(_BATCH_ADAPTER, batch),
                        created_at=batch.created_at,
                        updated_at=batch.created_at,
                    )
                    .on_conflict_do_nothing(index_elements=[creative_automation_batches.c.batch_id])
                    .returning(creative_automation_batches.c.batch_id)
                )
            ).scalar_one_or_none()
            if created is None:
                rows = await connection.execute(
                    select(creative_automation_jobs.c.payload)
                    .where(creative_automation_jobs.c.batch_id == batch.batch_id)
                    .order_by(creative_automation_jobs.c.created_at)
                )
                return tuple(_validate_job_payload(row.payload) for row in rows)
            for job in jobs:
                await connection.execute(
                    insert(creative_automation_jobs).values(
                        job_id=job.job_id,
                        batch_id=job.batch_id,
                        sku_id=job.request.sku_id,
                        brand_id=job.request.brand,
                        market=job.request.market,
                        execution_mode=job.request.execution_mode.value,
                        status=job.status,
                        command_id=job.command_id,
                        payload=_dump_python(_JOB_ADAPTER, job),
                        created_at=job.created_at,
                        updated_at=job.updated_at,
                    )
                )
        return jobs

    async def create_batch_with_commands(
        self,
        batch,
        jobs,
        commands: tuple[EnqueueCommand, ...],
    ):
        """Atomically persist a new batch, per-SKU jobs, commands and outbox intents."""
        if len(jobs) != len(commands) or tuple(job.job_id for job in jobs) != batch.job_ids:
            raise ValueError("Creative automation launch jobs and commands do not match the batch")
        async with self._engine.begin() as connection:
            created = (
                await connection.execute(
                    insert(creative_automation_batches)
                    .values(
                        batch_id=batch.batch_id,
                        idempotency_key=batch.idempotency_key,
                        brand_id=batch.brand_id,
                        requested_by=batch.requested_by,
                        payload=_dump_python(_BATCH_ADAPTER, batch),
                        created_at=batch.created_at,
                        updated_at=batch.created_at,
                    )
                    .on_conflict_do_nothing(index_elements=[creative_automation_batches.c.batch_id])
                    .returning(creative_automation_batches.c.batch_id)
                )
            ).scalar_one_or_none()
            if created is None:
                rows = await connection.execute(
                    select(creative_automation_jobs.c.payload)
                    .where(creative_automation_jobs.c.batch_id == batch.batch_id)
                    .order_by(creative_automation_jobs.c.created_at)
                )
                recorded_by_id = {
                    job.job_id: job for job in (_validate_job_payload(row.payload) for row in rows)
                }
                if set(recorded_by_id) != set(batch.job_ids):
                    raise ValueError("Creative automation batch idempotency payload drifted")
                recorded = tuple(recorded_by_id[job_id] for job_id in batch.job_ids)
                for expected, existing in zip(jobs, recorded, strict=True):
                    if replace(expected.request, requested_at=existing.request.requested_at) != (
                        existing.request
                    ):
                        raise ValueError("Creative automation batch idempotency payload drifted")
                return recorded
            queued_jobs = []
            for job, command_request in zip(jobs, commands, strict=True):
                command, _ = await enqueue_celery_command(
                    connection,
                    command_request,
                    batch.created_at,
                )
                queued = replace(
                    job,
                    command_id=command.command_id,
                    status=command.status.value,
                    updated_at=command.updated_at,
                )
                await connection.execute(
                    insert(creative_automation_jobs).values(
                        job_id=queued.job_id,
                        batch_id=queued.batch_id,
                        sku_id=queued.request.sku_id,
                        brand_id=queued.request.brand,
                        market=queued.request.market,
                        execution_mode=queued.request.execution_mode.value,
                        status=queued.status,
                        command_id=queued.command_id,
                        payload=_dump_python(_JOB_ADAPTER, queued),
                        created_at=queued.created_at,
                        updated_at=queued.updated_at,
                    )
                )
                queued_jobs.append(queued)
        return tuple(queued_jobs)

    async def save_job(self, job, event=None) -> None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(creative_automation_jobs)
                .where(creative_automation_jobs.c.job_id == job.job_id)
                .values(
                    status=job.status,
                    command_id=job.command_id,
                    payload=_dump_python(_JOB_ADAPTER, job),
                    updated_at=job.updated_at,
                )
            )
            if result.rowcount != 1:
                raise ValueError("Creative automation job does not exist")
            if event is not None:
                await connection.execute(
                    insert(creative_automation_events)
                    .values(
                        event_id=event.event_id,
                        job_id=event.job_id,
                        event_type=event.event_type,
                        payload=_dump_python(_EVENT_ADAPTER, event),
                        created_at=event.created_at,
                    )
                    .on_conflict_do_nothing(index_elements=[creative_automation_events.c.event_id])
                )

    async def add_event(self, event) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(creative_automation_events)
                .values(
                    event_id=event.event_id,
                    job_id=event.job_id,
                    event_type=event.event_type,
                    payload=_dump_python(_EVENT_ADAPTER, event),
                    created_at=event.created_at,
                )
                .on_conflict_do_nothing(index_elements=[creative_automation_events.c.event_id])
            )

    async def get_job(self, job_id: str):
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(creative_automation_jobs.c.payload).where(
                        creative_automation_jobs.c.job_id == job_id
                    )
                )
            ).scalar_one_or_none()
        return _validate_job_payload(row) if row is not None else None

    async def list_jobs(self):
        async with self._engine.connect() as connection:
            rows = await connection.execute(
                select(creative_automation_jobs.c.payload).order_by(
                    creative_automation_jobs.c.created_at.desc()
                )
            )
        return [_validate_job_payload(row.payload) for row in rows]

    async def list_events(self, job_id: str):
        async with self._engine.connect() as connection:
            rows = await connection.execute(
                select(creative_automation_events.c.payload)
                .where(creative_automation_events.c.job_id == job_id)
                .order_by(creative_automation_events.c.created_at)
            )
        return [_EVENT_ADAPTER.validate_python(row.payload) for row in rows]


def _dump(adapter: TypeAdapter, value: object) -> str:
    return adapter.dump_json(value).decode()


def _dump_python(adapter: TypeAdapter, value: object) -> dict[str, object]:
    return json.loads(adapter.dump_json(value))


__all__ = [
    "PostgresCreativeAutomationJobRepository",
    "SqliteCreativeAutomationJobRepository",
]
