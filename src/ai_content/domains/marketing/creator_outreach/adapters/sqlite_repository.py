"""SQLite persistence for Creator outreach runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import CreatorOutreachRun
from .serialization import run_from_dict, run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS creator_outreach_runs (
    run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteCreatorOutreachRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: CreatorOutreachRun) -> None:
        payload = json.dumps(run_to_dict(run), ensure_ascii=False)
        self._connection.execute(
            "INSERT OR REPLACE INTO creator_outreach_runs "
            "(run_id, source_run_id, candidate_id, state, payload) VALUES (?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.source_run_id,
                run.trigger.candidate_id,
                run.state.value,
                payload,
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> CreatorOutreachRun | None:
        row = self._connection.execute(
            "SELECT payload FROM creator_outreach_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row is not None else None

    async def get_by_source_run_id(self, source_run_id: str) -> CreatorOutreachRun | None:
        row = self._connection.execute(
            "SELECT payload FROM creator_outreach_runs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row is not None else None

    async def list(self) -> list[CreatorOutreachRun]:
        rows = self._connection.execute(
            "SELECT payload FROM creator_outreach_runs ORDER BY rowid"
        ).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteCreatorOutreachRepository"]
