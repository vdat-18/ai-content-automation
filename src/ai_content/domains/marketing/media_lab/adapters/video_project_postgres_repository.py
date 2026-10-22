"""PostgreSQL persistence for final Media Lab video projects."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import media_lab_video_projects

from ..domain.video_projects import VideoProject
from .video_project_serialization import video_project_from_dict, video_project_to_dict


class PostgresMediaLabVideoProjectRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save(self, project: VideoProject) -> None:
        statement = insert(media_lab_video_projects).values(
            project_id=project.project_id,
            source_run_id=project.source_run_id,
            state=project.state.value,
            payload=video_project_to_dict(project),
            created_at=project.created_at,
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[media_lab_video_projects.c.project_id],
            set_={
                "state": statement.excluded.state,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, project_id: str) -> VideoProject | None:
        statement = select(media_lab_video_projects.c.payload).where(
            media_lab_video_projects.c.project_id == project_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return video_project_from_dict(payload) if payload is not None else None

    async def get_by_source_run_id(self, source_run_id: str) -> VideoProject | None:
        statement = select(media_lab_video_projects.c.payload).where(
            media_lab_video_projects.c.source_run_id == source_run_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return video_project_from_dict(payload) if payload is not None else None

    async def list(self) -> list[VideoProject]:
        statement = select(media_lab_video_projects.c.payload).order_by(
            media_lab_video_projects.c.created_at.desc(),
            media_lab_video_projects.c.project_id.desc(),
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [video_project_from_dict(payload) for payload in payloads]


__all__ = ["PostgresMediaLabVideoProjectRepository"]
