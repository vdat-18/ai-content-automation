"""PostgreSQL persistence for Media Lab video run metadata."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import media_lab_video_runs

from ..domain.video_models import VideoGenerationState, VideoReviewState, VideoRun
from .video_serialization import video_run_from_dict, video_run_to_dict


class PostgresMediaLabVideoRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save(self, run: VideoRun) -> None:
        statement = insert(media_lab_video_runs).values(
            run_id=run.run_id,
            generation_state=run.generation_state.value,
            review_state=run.review_state.value,
            intent=run.intent.value,
            backend_run_id=run.backend_run_id,
            payload=video_run_to_dict(run),
            created_at=run.created_at,
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[media_lab_video_runs.c.run_id],
            set_={
                "generation_state": statement.excluded.generation_state,
                "review_state": statement.excluded.review_state,
                "intent": statement.excluded.intent,
                "backend_run_id": statement.excluded.backend_run_id,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, run_id: str) -> VideoRun | None:
        statement = select(media_lab_video_runs.c.payload).where(
            media_lab_video_runs.c.run_id == run_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return video_run_from_dict(payload) if payload is not None else None

    async def list(self) -> list[VideoRun]:
        statement = select(media_lab_video_runs.c.payload).order_by(
            media_lab_video_runs.c.created_at.desc(), media_lab_video_runs.c.run_id.desc()
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [video_run_from_dict(payload) for payload in payloads]

    async def delete(self, run_id: str) -> bool:
        statement = delete(media_lab_video_runs).where(media_lab_video_runs.c.run_id == run_id)
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        return result.rowcount > 0

    async def mark_inflight_interrupted(self) -> int:
        statement = select(media_lab_video_runs.c.payload).where(
            media_lab_video_runs.c.generation_state.in_(
                [VideoGenerationState.QUEUED.value, VideoGenerationState.RUNNING.value]
            )
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        now = datetime.now(UTC)
        for payload in payloads:
            run = video_run_from_dict(payload)
            await self.save(
                replace(
                    run,
                    generation_state=VideoGenerationState.INTERRUPTED,
                    review_state=VideoReviewState.NOT_READY,
                    completed_at=now,
                    error_code="api_restarted",
                )
            )
        return len(payloads)


__all__ = ["PostgresMediaLabVideoRepository"]
