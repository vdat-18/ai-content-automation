"""SQLite persistence for autonomous final Video Ad jobs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.video_ads import VideoAdJob, VideoAdJobState
from .video_ad_serialization import video_ad_job_from_dict, video_ad_job_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_lab_video_ad_jobs (
    job_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_media_lab_video_ad_jobs_state
    ON media_lab_video_ad_jobs(state);
"""

_ACTIVE_STATES = (
    VideoAdJobState.PLANNING,
    VideoAdJobState.GENERATING_SHOTS,
    VideoAdJobState.SELECTING_SEGMENTS,
    VideoAdJobState.ASSEMBLING,
    VideoAdJobState.CANCEL_REQUESTED,
)


class SqliteMediaLabVideoAdRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, job: VideoAdJob) -> None:
        self._connection.execute(
            "INSERT INTO media_lab_video_ad_jobs (job_id, source_run_id, state, payload) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET "
            "state=excluded.state, payload=excluded.payload",
            (
                job.job_id,
                job.source_run_id,
                job.state.value,
                json.dumps(video_ad_job_to_dict(job), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, job_id: str) -> VideoAdJob | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_video_ad_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return video_ad_job_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> VideoAdJob | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_video_ad_jobs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return video_ad_job_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[VideoAdJob]:
        rows = self._connection.execute(
            "SELECT payload FROM media_lab_video_ad_jobs ORDER BY rowid DESC"
        ).fetchall()
        return [video_ad_job_from_dict(json.loads(row["payload"])) for row in rows]

    async def list_active(self) -> list[VideoAdJob]:
        placeholders = ",".join("?" for _ in _ACTIVE_STATES)
        rows = self._connection.execute(
            f"SELECT payload FROM media_lab_video_ad_jobs WHERE state IN ({placeholders}) "
            "ORDER BY rowid",  # noqa: S608 - placeholders are generated internally
            tuple(item.value for item in _ACTIVE_STATES),
        ).fetchall()
        return [video_ad_job_from_dict(json.loads(row["payload"])) for row in rows]

    async def delete(self, job_id: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM media_lab_video_ad_jobs WHERE job_id = ?", (job_id,)
        )
        self._connection.commit()
        return cursor.rowcount > 0


__all__ = ["SqliteMediaLabVideoAdRepository"]
