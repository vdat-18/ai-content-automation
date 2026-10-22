"""SQLite repository for GMC ingestion run metadata."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import GmcIngestionRun
from .serialization import run_from_dict, run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gmc_ingestion_runs (
    run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    source_checksum TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteGmcRunRepository:
    """Persist complete immutable run summaries in pilot SQLite."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: GmcIngestionRun) -> None:
        self._connection.execute(
            "INSERT INTO gmc_ingestion_runs "
            "(run_id, source_run_id, source_checksum, status, payload) VALUES (?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.specification.source_run_id,
                run.source.checksum_sha256,
                run.status.value,
                json.dumps(run_to_dict(run), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> GmcIngestionRun | None:
        row = self._connection.execute(
            "SELECT payload FROM gmc_ingestion_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> GmcIngestionRun | None:
        row = self._connection.execute(
            "SELECT payload FROM gmc_ingestion_runs WHERE source_run_id = ?", (source_run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[GmcIngestionRun]:
        rows = self._connection.execute(
            "SELECT payload FROM gmc_ingestion_runs ORDER BY rowid DESC"
        ).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteGmcRunRepository"]
