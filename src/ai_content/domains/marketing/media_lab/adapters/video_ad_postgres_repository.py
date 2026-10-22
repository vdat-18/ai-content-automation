"""PostgreSQL persistence for autonomous final Video Ad jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import media_lab_video_ad_jobs

from ..domain.video_ads import VideoAdJob, VideoAdJobState
from .video_ad_serialization import video_ad_job_from_dict, video_ad_job_to_dict

_ACTIVE_STATES = (
    VideoAdJobState.PLANNING,
    VideoAdJobState.GENERATING_SHOTS,
    VideoAdJobState.SELECTING_SEGMENTS,
    VideoAdJobState.ASSEMBLING,
    VideoAdJobState.CANCEL_REQUESTED,
)


class PostgresMediaLabVideoAdRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save(self, job: VideoAdJob) -> None:
        statement = insert(media_lab_video_ad_jobs).values(
            job_id=job.job_id,
            source_run_id=job.source_run_id,
            state=job.state.value,
            payload=video_ad_job_to_dict(job),
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[media_lab_video_ad_jobs.c.job_id],
            set_={
                "state": statement.excluded.state,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, job_id: str) -> VideoAdJob | None:
        statement = select(media_lab_video_ad_jobs.c.payload).where(
            media_lab_video_ad_jobs.c.job_id == job_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return video_ad_job_from_dict(payload) if payload is not None else None

    async def get_by_source_run_id(self, source_run_id: str) -> VideoAdJob | None:
        statement = select(media_lab_video_ad_jobs.c.payload).where(
            media_lab_video_ad_jobs.c.source_run_id == source_run_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return video_ad_job_from_dict(payload) if payload is not None else None

    async def list(self) -> list[VideoAdJob]:
        statement = select(media_lab_video_ad_jobs.c.payload).order_by(
            media_lab_video_ad_jobs.c.created_at.desc(), media_lab_video_ad_jobs.c.job_id.desc()
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [video_ad_job_from_dict(payload) for payload in payloads]

    async def list_active(self) -> list[VideoAdJob]:
        statement = (
            select(media_lab_video_ad_jobs.c.payload)
            .where(media_lab_video_ad_jobs.c.state.in_([item.value for item in _ACTIVE_STATES]))
            .order_by(media_lab_video_ad_jobs.c.created_at)
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [video_ad_job_from_dict(payload) for payload in payloads]

    async def delete(self, job_id: str) -> bool:
        statement = delete(media_lab_video_ad_jobs).where(
            media_lab_video_ad_jobs.c.job_id == job_id
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        return result.rowcount > 0


__all__ = ["PostgresMediaLabVideoAdRepository"]
