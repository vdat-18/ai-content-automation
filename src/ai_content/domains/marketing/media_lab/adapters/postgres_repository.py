"""PostgreSQL persistence for Media Lab image run metadata."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import media_lab_image_runs

from ..domain.models import ImageGenerationState, ImageReviewState, ImageRun
from .serialization import run_from_dict, run_to_dict


class PostgresMediaLabImageRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save(self, run: ImageRun) -> None:
        statement = insert(media_lab_image_runs).values(
            run_id=run.run_id,
            generation_state=run.generation_state.value,
            review_state=run.review_state.value,
            intent=run.intent.value,
            backend_run_id=run.backend_run_id,
            parent_run_id=run.parent_run_id,
            payload=run_to_dict(run),
            created_at=run.created_at,
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[media_lab_image_runs.c.run_id],
            set_={
                "generation_state": statement.excluded.generation_state,
                "review_state": statement.excluded.review_state,
                "intent": statement.excluded.intent,
                "backend_run_id": statement.excluded.backend_run_id,
                "parent_run_id": statement.excluded.parent_run_id,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, run_id: str) -> ImageRun | None:
        statement = select(media_lab_image_runs.c.payload).where(
            media_lab_image_runs.c.run_id == run_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return run_from_dict(payload) if payload is not None else None

    async def list(self) -> list[ImageRun]:
        statement = select(media_lab_image_runs.c.payload).order_by(
            media_lab_image_runs.c.created_at.desc(), media_lab_image_runs.c.run_id.desc()
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [run_from_dict(payload) for payload in payloads]

    async def delete(self, run_id: str) -> bool:
        statement = delete(media_lab_image_runs).where(media_lab_image_runs.c.run_id == run_id)
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        return result.rowcount > 0

    async def mark_inflight_interrupted(self) -> int:
        statement = select(media_lab_image_runs.c.payload).where(
            media_lab_image_runs.c.generation_state.in_(
                [ImageGenerationState.QUEUED.value, ImageGenerationState.RUNNING.value]
            )
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        now = datetime.now(UTC)
        for payload in payloads:
            run = run_from_dict(payload)
            await self.save(
                replace(
                    run,
                    generation_state=ImageGenerationState.INTERRUPTED,
                    review_state=ImageReviewState.NOT_READY,
                    completed_at=now,
                    error_code="api_restarted",
                )
            )
        return len(payloads)


__all__ = ["PostgresMediaLabImageRepository"]
