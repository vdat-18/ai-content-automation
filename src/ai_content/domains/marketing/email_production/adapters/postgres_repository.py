"""PostgreSQL persistence for Email production jobs."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import email_production_jobs

from ..domain.models import EmailProductionJob
from .serialization import job_from_dict, job_to_dict


class PostgresEmailProductionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, email_production_jobs, job_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, job: EmailProductionJob) -> None:
        await self._store.upsert(
            {
                "job_id": job.job_id,
                "source_run_id": job.source_run_id,
                "state": job.state.value,
                "payload": job_to_dict(job),
            },
            ("state", "payload"),
        )

    async def get(self, job_id: str) -> EmailProductionJob | None:
        return await self._store.get(email_production_jobs.c.job_id, job_id)

    async def get_by_source_run_id(self, source_run_id: str) -> EmailProductionJob | None:
        return await self._store.get(email_production_jobs.c.source_run_id, source_run_id)

    async def list(self) -> list[EmailProductionJob]:
        return await self._store.list(ascending=True)


__all__ = ["PostgresEmailProductionRepository"]
