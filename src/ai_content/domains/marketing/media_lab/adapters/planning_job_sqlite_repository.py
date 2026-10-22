"""SQLite persistence for Media Lab planning jobs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.planning_jobs import PlanningJob, PlanningJobState
from .planning_job_serialization import planning_job_from_dict, planning_job_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_lab_planning_jobs (
    job_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_media_lab_planning_jobs_state
    ON media_lab_planning_jobs(state);
"""


class SqliteMediaLabPlanningJobRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, job: PlanningJob) -> None:
        self._connection.execute(
            "INSERT INTO media_lab_planning_jobs (job_id, source_run_id, state, payload) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET "
            "state=excluded.state, payload=excluded.payload",
            (
                job.job_id,
                job.source_run_id,
                job.state.value,
                json.dumps(planning_job_to_dict(job), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, job_id: str) -> PlanningJob | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_planning_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return planning_job_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> PlanningJob | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_planning_jobs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return planning_job_from_dict(json.loads(row["payload"])) if row else None

    async def list_active(self) -> list[PlanningJob]:
        rows = self._connection.execute(
            "SELECT payload FROM media_lab_planning_jobs WHERE state = ? ORDER BY rowid",
            (PlanningJobState.PLANNING.value,),
        ).fetchall()
        return [planning_job_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteMediaLabPlanningJobRepository"]
