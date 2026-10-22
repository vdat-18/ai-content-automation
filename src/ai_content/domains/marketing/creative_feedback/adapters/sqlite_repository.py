"""SQLite persistence for Creative feedback runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import CreativeFeedbackRun
from .serialization import run_from_dict, run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS creative_feedback_runs (
    run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    source_checksum TEXT NOT NULL,
    creative_version_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteCreativeFeedbackRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: CreativeFeedbackRun) -> None:
        payload = json.dumps(run_to_dict(run), ensure_ascii=False)
        self._connection.execute(
            "INSERT INTO creative_feedback_runs "
            "(run_id, source_run_id, source_checksum, creative_version_id, state, payload) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET state=excluded.state, payload=excluded.payload",
            (
                run.run_id,
                run.source_run_id,
                run.source_checksum_sha256,
                run.release.creative_version_id,
                run.state.value,
                payload,
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> CreativeFeedbackRun | None:
        row = self._connection.execute(
            "SELECT payload FROM creative_feedback_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeFeedbackRun | None:
        row = self._connection.execute(
            "SELECT payload FROM creative_feedback_runs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[CreativeFeedbackRun]:
        rows = self._connection.execute(
            "SELECT payload FROM creative_feedback_runs ORDER BY rowid DESC"
        ).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]

    async def list_approved_memory(
        self,
        *,
        brand_id: str,
        sku_id: str,
        limit: int = 20,
    ) -> list[CreativeFeedbackRun]:
        runs = await self.list()
        return [
            run
            for run in runs
            if run.decision is not None
            and run.decision.value == "approve"
            and run.release.brand_id == brand_id
            and run.release.sku_id == sku_id
        ][:limit]


__all__ = ["SqliteCreativeFeedbackRepository"]
