"""SQLite persistence for Email production jobs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import EmailProductionJob
from .serialization import job_from_dict, job_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_production_jobs (
    job_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteEmailProductionRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, job: EmailProductionJob) -> None:
        payload = json.dumps(job_to_dict(job), ensure_ascii=False)
        self._connection.execute(
            "INSERT OR REPLACE INTO email_production_jobs "
            "(job_id, source_run_id, state, payload) VALUES (?, ?, ?, ?)",
            (job.job_id, job.source_run_id, job.state.value, payload),
        )
        self._connection.commit()

    async def get(self, job_id: str) -> EmailProductionJob | None:
        row = self._connection.execute(
            "SELECT payload FROM email_production_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return job_from_dict(json.loads(row["payload"])) if row is not None else None

    async def get_by_source_run_id(self, source_run_id: str) -> EmailProductionJob | None:
        row = self._connection.execute(
            "SELECT payload FROM email_production_jobs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return job_from_dict(json.loads(row["payload"])) if row is not None else None

    async def list(self) -> list[EmailProductionJob]:
        rows = self._connection.execute(
            "SELECT payload FROM email_production_jobs ORDER BY rowid"
        ).fetchall()
        return [job_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteEmailProductionRepository"]
