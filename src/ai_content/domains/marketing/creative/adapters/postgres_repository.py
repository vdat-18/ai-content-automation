"""PostgreSQL persistence for Creative jobs and versions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import creative_jobs, creative_versions

from ..domain.entities import AssetVersion, CreativeJob, CreativeJobId, VersionId
from .sqlite_repository import _job_from_dict, _job_to_dict, _version_from_dict, _version_to_dict


class PostgresCreativeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        """The process composition root owns the shared engine."""

    async def save_job(self, job: CreativeJob) -> None:
        statement = insert(creative_jobs).values(
            job_id=job.job_id.value,
            source_run_id=job.source_run_id,
            status=job.status.value,
            payload=_job_to_dict(job),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[creative_jobs.c.job_id],
            set_={
                "status": statement.excluded.status,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get_job(self, job_id: CreativeJobId) -> CreativeJob | None:
        return await self._get_job(creative_jobs.c.job_id, job_id.value)

    async def get_job_by_source_run_id(self, source_run_id: str) -> CreativeJob | None:
        return await self._get_job(creative_jobs.c.source_run_id, source_run_id)

    async def _get_job(self, column, value: str) -> CreativeJob | None:
        statement = select(creative_jobs.c.payload).where(column == value)
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        if payload is None:
            return None
        job = _job_from_dict(payload)
        job.versions.extend(await self.get_versions_for_job(job.job_id))
        return job

    async def list_jobs(self) -> list[CreativeJob]:
        jobs_statement = select(creative_jobs.c.payload).order_by(
            creative_jobs.c.created_at.asc(), creative_jobs.c.job_id
        )
        versions_statement = select(
            creative_versions.c.job_id,
            creative_versions.c.payload,
        ).order_by(creative_versions.c.job_id, creative_versions.c.attempt_number)
        async with self._engine.connect() as connection:
            job_payloads = (await connection.execute(jobs_statement)).scalars().all()
            version_rows = (await connection.execute(versions_statement)).all()

        versions_by_job: dict[str, list[AssetVersion]] = {}
        for job_id, payload in version_rows:
            versions_by_job.setdefault(job_id, []).append(_version_from_dict(payload))

        jobs = [_job_from_dict(payload) for payload in job_payloads]
        for job in jobs:
            job.versions.extend(versions_by_job.get(job.job_id.value, ()))
        return jobs

    async def save_version(self, version: AssetVersion) -> None:
        statement = insert(creative_versions).values(
            version_id=version.version_id.value,
            job_id=version.version_id.job_id.value,
            attempt_number=version.attempt_number,
            payload=_version_to_dict(version),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[creative_versions.c.version_id],
            set_={
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get_version(self, version_id: VersionId) -> AssetVersion | None:
        statement = select(creative_versions.c.payload).where(
            creative_versions.c.version_id == version_id.value
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return _version_from_dict(payload) if payload is not None else None

    async def get_versions_for_job(self, job_id: CreativeJobId) -> list[AssetVersion]:
        statement = (
            select(creative_versions.c.payload)
            .where(creative_versions.c.job_id == job_id.value)
            .order_by(creative_versions.c.attempt_number)
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [_version_from_dict(payload) for payload in payloads]


__all__ = ["PostgresCreativeRepository"]
