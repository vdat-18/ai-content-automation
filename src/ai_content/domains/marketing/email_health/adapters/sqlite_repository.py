"""SQLite persistence for Email Operations health runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import EmailHealthRun
from .serialization import run_from_dict, run_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_health_runs (
    run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    source_checksum TEXT NOT NULL,
    issue_fingerprint TEXT NOT NULL,
    account_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_health_issue_fingerprint
ON email_health_runs(issue_fingerprint);
"""


class SqliteEmailHealthRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, run: EmailHealthRun) -> None:
        payload = json.dumps(run_to_dict(run), ensure_ascii=False)
        subject = run.snapshot.subject
        self._connection.execute(
            "INSERT INTO email_health_runs "
            "(run_id, source_run_id, source_checksum, issue_fingerprint, account_id, "
            "subject_type, subject_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload",
            (
                run.run_id,
                run.source_run_id,
                run.source_checksum_sha256,
                run.issue_fingerprint,
                subject.account_id,
                subject.subject_type.value,
                subject.subject_id,
                payload,
            ),
        )
        self._connection.commit()

    async def get(self, run_id: str) -> EmailHealthRun | None:
        row = self._connection.execute(
            "SELECT payload FROM email_health_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> EmailHealthRun | None:
        row = self._connection.execute(
            "SELECT payload FROM email_health_runs WHERE source_run_id = ?", (source_run_id,)
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[EmailHealthRun]:
        rows = self._connection.execute(
            "SELECT payload FROM email_health_runs ORDER BY rowid DESC"
        ).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteEmailHealthRepository"]
