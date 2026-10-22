"""PostgreSQL persistence for Media Lab planning jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import media_lab_planning_jobs

from ..domain.planning_jobs import PlanningJob, PlanningJobState
from .planning_job_serialization import planning_job_from_dict, planning_job_to_dict


class PostgresMediaLabPlanningJobRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save(self, job: PlanningJob) -> None:
        statement = insert(media_lab_planning_jobs).values(
            job_id=job.job_id,
            source_run_id=job.source_run_id,
            state=job.state.value,
            payload=planning_job_to_dict(job),
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[media_lab_planning_jobs.c.job_id],
            set_={
                "state": statement.excluded.state,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, job_id: str) -> PlanningJob | None:
        statement = select(media_lab_planning_jobs.c.payload).where(
            media_lab_planning_jobs.c.job_id == job_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return planning_job_from_dict(payload) if payload is not None else None

    async def get_by_source_run_id(self, source_run_id: str) -> PlanningJob | None:
        statement = select(media_lab_planning_jobs.c.payload).where(
            media_lab_planning_jobs.c.source_run_id == source_run_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return planning_job_from_dict(payload) if payload is not None else None

    async def list_active(self) -> list[PlanningJob]:
        statement = (
            select(media_lab_planning_jobs.c.payload)
            .where(media_lab_planning_jobs.c.state == PlanningJobState.PLANNING.value)
            .order_by(media_lab_planning_jobs.c.created_at)
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [planning_job_from_dict(payload) for payload in payloads]


__all__ = ["PostgresMediaLabPlanningJobRepository"]
