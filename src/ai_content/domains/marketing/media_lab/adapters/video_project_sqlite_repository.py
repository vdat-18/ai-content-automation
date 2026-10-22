"""SQLite persistence for final Media Lab video projects."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.video_projects import VideoProject
from .video_project_serialization import video_project_from_dict, video_project_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_lab_video_projects (
    project_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_media_lab_video_projects_state
    ON media_lab_video_projects(state);
"""


class SqliteMediaLabVideoProjectRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, project: VideoProject) -> None:
        self._connection.execute(
            "INSERT INTO media_lab_video_projects (project_id, source_run_id, state, payload) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET "
            "state=excluded.state, payload=excluded.payload",
            (
                project.project_id,
                project.source_run_id,
                project.state.value,
                json.dumps(video_project_to_dict(project), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, project_id: str) -> VideoProject | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_video_projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        return video_project_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> VideoProject | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_video_projects WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return video_project_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[VideoProject]:
        rows = self._connection.execute(
            "SELECT payload FROM media_lab_video_projects ORDER BY rowid DESC"
        ).fetchall()
        return [video_project_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteMediaLabVideoProjectRepository"]
