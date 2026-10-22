"""SQLite persistence for Performance decision pilot runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import PerformanceDecisionRun
from .serialization import run_from_dict, run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS performance_decision_runs (
    run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    source_checksum TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqlitePerformanceDecisionRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: PerformanceDecisionRun) -> None:
        payload = json.dumps(run_to_dict(run), ensure_ascii=False)
        self._connection.execute(
            "INSERT INTO performance_decision_runs "
            "(run_id, source_run_id, source_checksum, subject_type, subject_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload",
            (
                run.run_id,
                run.source_run_id,
                run.source_checksum_sha256,
                run.snapshot.subject.subject_type.value,
                run.snapshot.subject.subject_id,
                payload,
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> PerformanceDecisionRun | None:
        row = self._connection.execute(
            "SELECT payload FROM performance_decision_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> PerformanceDecisionRun | None:
        row = self._connection.execute(
            "SELECT payload FROM performance_decision_runs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[PerformanceDecisionRun]:
        rows = self._connection.execute(
            "SELECT payload FROM performance_decision_runs ORDER BY rowid DESC"
        ).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqlitePerformanceDecisionRepository"]
