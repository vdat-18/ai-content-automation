"""SQLite persistence for aggregate Email Marketing report runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.models import EmailPerformanceReport
from .serialization import report_from_dict, report_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_reports (
    report_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteEmailReportRepository:
    """Persist complete immutable report payloads in the pilot SQLite database."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, report: EmailPerformanceReport) -> None:
        payload = json.dumps(report_to_dict(report), ensure_ascii=False)
        self._connection.execute(
            "INSERT INTO email_reports (report_id, source_run_id, status, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                report.report_id,
                report.specification.source_run_id,
                report.status.value,
                payload,
            ),
        )
        self._connection.commit()

    async def get(self, report_id: str) -> EmailPerformanceReport | None:
        row = self._connection.execute(
            "SELECT payload FROM email_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return report_from_dict(json.loads(row["payload"])) if row else None

    async def get_by_source_run_id(self, source_run_id: str) -> EmailPerformanceReport | None:
        row = self._connection.execute(
            "SELECT payload FROM email_reports WHERE source_run_id = ?", (source_run_id,)
        ).fetchone()
        return report_from_dict(json.loads(row["payload"])) if row else None

    async def list(self) -> list[EmailPerformanceReport]:
        rows = self._connection.execute(
            "SELECT payload FROM email_reports ORDER BY rowid DESC"
        ).fetchall()
        return [report_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteEmailReportRepository"]
