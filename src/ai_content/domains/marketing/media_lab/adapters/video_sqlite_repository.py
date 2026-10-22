"""SQLite persistence for Media Lab video run metadata."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from ..domain.video_models import VideoGenerationState, VideoReviewState, VideoRun
from .video_serialization import video_run_from_dict, video_run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_lab_video_runs (
    run_id TEXT PRIMARY KEY,
    generation_state TEXT NOT NULL,
    review_state TEXT NOT NULL,
    intent TEXT NOT NULL,
    backend_run_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_media_lab_video_runs_backend
    ON media_lab_video_runs(backend_run_id);
"""


class SqliteMediaLabVideoRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: VideoRun) -> None:
        self._connection.execute(
            "INSERT INTO media_lab_video_runs "
            "(run_id, generation_state, review_state, intent, backend_run_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "generation_state=excluded.generation_state, review_state=excluded.review_state, "
            "backend_run_id=excluded.backend_run_id, payload=excluded.payload",
            (
                run.run_id,
                run.generation_state.value,
                run.review_state.value,
                run.intent.value,
                run.backend_run_id,
                json.dumps(video_run_to_dict(run), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> VideoRun | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_video_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return video_run_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[VideoRun]:
        rows = self._connection.execute(
            "SELECT payload FROM media_lab_video_runs ORDER BY rowid DESC"
        ).fetchall()
        return [video_run_from_dict(json.loads(row["payload"])) for row in rows]

    async def delete(self, run_id: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM media_lab_video_runs WHERE run_id = ?", (run_id,)
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def mark_inflight_interrupted(self) -> int:
        rows = self._connection.execute(
            "SELECT payload FROM media_lab_video_runs WHERE generation_state IN (?, ?)",
            (VideoGenerationState.QUEUED.value, VideoGenerationState.RUNNING.value),
        ).fetchall()
        now = datetime.now(UTC)
        for row in rows:
            run = video_run_from_dict(json.loads(row["payload"]))
            await self.save(
                replace(
                    run,
                    generation_state=VideoGenerationState.INTERRUPTED,
                    review_state=VideoReviewState.NOT_READY,
                    completed_at=now,
                    error_code="api_restarted",
                )
            )
        return len(rows)


__all__ = ["SqliteMediaLabVideoRepository"]
