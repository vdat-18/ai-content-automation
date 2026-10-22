"""SQLite persistence for Creative intake runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import CreativeIntakeRun
from .serialization import run_from_dict, run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS creative_intake_runs (
    run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    source_checksum TEXT NOT NULL,
    state TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteCreativeIntakeRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: CreativeIntakeRun) -> None:
        self._connection.execute(
            "INSERT INTO creative_intake_runs "
            "(run_id, source_run_id, source_checksum, state, brand_id, sku_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET state=excluded.state, payload=excluded.payload",
            (
                run.run_id,
                run.source_run_id,
                run.source_checksum_sha256,
                run.state.value,
                run.context.brand_id,
                run.context.sku_id,
                json.dumps(run_to_dict(run), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> CreativeIntakeRun | None:
        row = self._connection.execute(
            "SELECT payload FROM creative_intake_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeIntakeRun | None:
        row = self._connection.execute(
            "SELECT payload FROM creative_intake_runs WHERE source_run_id = ?", (source_run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_task_source_run_id(self, source_run_id: str) -> CreativeIntakeRun | None:
        for run in await self.list():
            if run.release is not None and run.release.source_run_id == source_run_id:
                return run
        return None

    async def list(self) -> list[CreativeIntakeRun]:
        rows = self._connection.execute(
            "SELECT payload FROM creative_intake_runs ORDER BY rowid DESC"
        ).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteCreativeIntakeRepository"]
