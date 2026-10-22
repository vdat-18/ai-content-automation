"""Single-node SQLite command queue with atomic leases and idempotent enqueue."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .models import CommandStatus, EnqueueCommand, ExecutionBackend, ExecutionCommand

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_commands (
    command_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_checksum TEXT NOT NULL,
    payload TEXT NOT NULL,
    workflow_run_id TEXT,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error_code TEXT,
    last_error_message TEXT,
    completed_at TEXT,
    execution_backend TEXT NOT NULL DEFAULT 'lease_worker',
    queue_name TEXT NOT NULL DEFAULT 'control',
    dispatch_generation INTEGER NOT NULL DEFAULT 0,
    execution_id TEXT,
    started_at TEXT,
    cancel_requested_at TEXT,
    cancelled_at TEXT,
    audit_log TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_commands_ready
ON execution_commands (status, available_at);
CREATE INDEX IF NOT EXISTS idx_execution_commands_workflow
ON execution_commands (workflow_run_id, created_at);
"""


class CommandPayloadDriftError(ValueError):
    """A dedupe key was reused with a different immutable command payload."""


class SqliteCommandQueue:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.executescript(_SCHEMA)
        self._ensure_execution_columns()
        self._connection.commit()

    def _ensure_execution_columns(self) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(execution_commands)")
        }
        additions = {
            "execution_backend": "TEXT NOT NULL DEFAULT 'lease_worker'",
            "queue_name": "TEXT NOT NULL DEFAULT 'control'",
            "dispatch_generation": "INTEGER NOT NULL DEFAULT 0",
            "execution_id": "TEXT",
            "started_at": "TEXT",
            "cancel_requested_at": "TEXT",
            "cancelled_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                self._connection.execute(
                    f"ALTER TABLE execution_commands ADD COLUMN {name} {definition}"
                )

    def close(self) -> None:
        self._connection.close()

    def enqueue(
        self, request: EnqueueCommand, now: datetime | None = None
    ) -> tuple[ExecutionCommand, bool]:
        created_at = now or datetime.now(UTC)
        _require_aware(created_at)
        payload_json = _canonical_json(request.payload)
        checksum = hashlib.sha256(payload_json.encode()).hexdigest()
        command_id = str(uuid5(NAMESPACE_URL, f"execution-command:{request.dedupe_key}"))
        audit = json.dumps([f"enqueued:{created_at.isoformat()}"])
        try:
            self._connection.execute(
                "INSERT INTO execution_commands ("
                "command_id, name, dedupe_key, payload_checksum, payload, workflow_run_id, "
                "status, attempts, max_attempts, created_at, updated_at, available_at, "
                "execution_backend, queue_name, audit_log"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (
                    command_id,
                    request.name,
                    request.dedupe_key,
                    checksum,
                    payload_json,
                    request.workflow_run_id,
                    CommandStatus.PENDING.value,
                    request.max_attempts,
                    created_at.isoformat(),
                    created_at.isoformat(),
                    created_at.isoformat(),
                    "lease_worker",
                    request.queue_name,
                    audit,
                ),
            )
            self._connection.commit()
            created = True
        except sqlite3.IntegrityError:
            self._connection.rollback()
            created = False
        existing = self.get_by_dedupe_key(request.dedupe_key)
        if existing is None:
            raise RuntimeError("Command enqueue did not persist a record")
        if existing.payload_checksum_sha256 != checksum or existing.name != request.name:
            raise CommandPayloadDriftError(
                "Command dedupe key was reused with a different immutable payload"
            )
        return existing, created

    def get(self, command_id: str) -> ExecutionCommand | None:
        row = self._connection.execute(
            "SELECT * FROM execution_commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        return _from_row(row) if row else None

    def get_by_dedupe_key(self, dedupe_key: str) -> ExecutionCommand | None:
        row = self._connection.execute(
            "SELECT * FROM execution_commands WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        return _from_row(row) if row else None

    def list(
        self,
        status: CommandStatus | None = None,
        workflow_run_id: str | None = None,
    ) -> list[ExecutionCommand]:
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if workflow_run_id is not None:
            clauses.append("workflow_run_id = ?")
            params.append(workflow_run_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM execution_commands{where} ORDER BY created_at DESC", params
        ).fetchall()
        return [_from_row(row) for row in rows]

    def claim_next(
        self,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> ExecutionCommand | None:
        claimed_at = now or datetime.now(UTC)
        _require_aware(claimed_at)
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "UPDATE execution_commands SET status = ?, updated_at = ?, lease_owner = NULL, "
                "lease_expires_at = NULL, last_error_code = ?, last_error_message = ?, "
                "audit_log = json_insert(audit_log, '$[#]', ?) "
                "WHERE status = ? AND lease_expires_at <= ? AND attempts >= max_attempts",
                (
                    CommandStatus.FAILED.value,
                    claimed_at.isoformat(),
                    "LEASE_EXHAUSTED",
                    "Worker lease expired after the final allowed attempt",
                    f"lease_exhausted:{claimed_at.isoformat()}",
                    CommandStatus.RUNNING.value,
                    claimed_at.isoformat(),
                ),
            )
            row = self._connection.execute(
                "SELECT command_id FROM execution_commands WHERE attempts < max_attempts AND ("
                "(status IN (?, ?) AND available_at <= ?) OR "
                "(status = ? AND lease_expires_at <= ?)"
                ") ORDER BY available_at, created_at LIMIT 1",
                (
                    CommandStatus.PENDING.value,
                    CommandStatus.RETRY_WAIT.value,
                    claimed_at.isoformat(),
                    CommandStatus.RUNNING.value,
                    claimed_at.isoformat(),
                ),
            ).fetchone()
            if row is None:
                self._connection.commit()
                return None
            command_id = str(row["command_id"])
            self._connection.execute(
                "UPDATE execution_commands SET status = ?, attempts = attempts + 1, "
                "updated_at = ?, lease_owner = ?, lease_expires_at = ?, "
                "audit_log = json_insert(audit_log, '$[#]', ?) WHERE command_id = ?",
                (
                    CommandStatus.RUNNING.value,
                    claimed_at.isoformat(),
                    worker_id,
                    lease_expires_at.isoformat(),
                    f"claimed:{worker_id}:{claimed_at.isoformat()}",
                    command_id,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.get(command_id)

    def complete(
        self, command_id: str, worker_id: str, now: datetime | None = None
    ) -> ExecutionCommand:
        completed_at = now or datetime.now(UTC)
        _require_aware(completed_at)
        updated = self._connection.execute(
            "UPDATE execution_commands SET status = ?, updated_at = ?, completed_at = ?, "
            "lease_owner = NULL, lease_expires_at = NULL, "
            "audit_log = json_insert(audit_log, '$[#]', ?) "
            "WHERE command_id = ? AND status = ? AND lease_owner = ?",
            (
                CommandStatus.COMPLETED.value,
                completed_at.isoformat(),
                completed_at.isoformat(),
                f"completed:{completed_at.isoformat()}",
                command_id,
                CommandStatus.RUNNING.value,
                worker_id,
            ),
        )
        self._connection.commit()
        if updated.rowcount != 1:
            raise ValueError("Command completion requires the active worker lease")
        command = self.get(command_id)
        assert command is not None
        return command

    def renew_lease(
        self,
        command_id: str,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> ExecutionCommand:
        renewed_at = now or datetime.now(UTC)
        _require_aware(renewed_at)
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        updated = self._connection.execute(
            "UPDATE execution_commands SET updated_at = ?, lease_expires_at = ? "
            "WHERE command_id = ? AND status IN (?, ?) AND lease_owner = ?",
            (
                renewed_at.isoformat(),
                (renewed_at + timedelta(seconds=lease_seconds)).isoformat(),
                command_id,
                CommandStatus.RUNNING.value,
                CommandStatus.CANCEL_REQUESTED.value,
                worker_id,
            ),
        )
        self._connection.commit()
        if updated.rowcount != 1:
            raise ValueError("Command lease renewal requires the active worker lease")
        command = self.get(command_id)
        assert command is not None
        return command

    def fail(
        self,
        command_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime | None = None,
        retry_delay_seconds: int = 5,
    ) -> ExecutionCommand:
        failed_at = now or datetime.now(UTC)
        _require_aware(failed_at)
        command = self.get(command_id)
        if command is None or command.status != CommandStatus.RUNNING:
            raise ValueError("Only a running command may fail")
        if command.lease_owner != worker_id:
            raise ValueError("Command failure requires the active worker lease")
        should_retry = retryable and command.attempts < command.max_attempts
        status = CommandStatus.RETRY_WAIT if should_retry else CommandStatus.FAILED
        available_at = failed_at + timedelta(seconds=retry_delay_seconds if should_retry else 0)
        updated = self._connection.execute(
            "UPDATE execution_commands SET status = ?, updated_at = ?, available_at = ?, "
            "lease_owner = NULL, lease_expires_at = NULL, last_error_code = ?, "
            "last_error_message = ?, audit_log = json_insert(audit_log, '$[#]', ?) "
            "WHERE command_id = ? AND status = ? AND lease_owner = ?",
            (
                status.value,
                failed_at.isoformat(),
                available_at.isoformat(),
                error_code,
                _sanitize_error(error_message),
                f"{status.value}:{error_code}:{failed_at.isoformat()}",
                command_id,
                CommandStatus.RUNNING.value,
                worker_id,
            ),
        )
        self._connection.commit()
        if updated.rowcount != 1:
            raise ValueError("Command failure requires the active worker lease")
        updated = self.get(command_id)
        assert updated is not None
        return updated

    def retry_failed(self, command_id: str, now: datetime | None = None) -> ExecutionCommand:
        retried_at = now or datetime.now(UTC)
        _require_aware(retried_at)
        updated = self._connection.execute(
            "UPDATE execution_commands SET status = ?, updated_at = ?, available_at = ?, "
            "max_attempts = CASE WHEN max_attempts <= attempts THEN attempts + 1 ELSE max_attempts END, "
            "completed_at = NULL, audit_log = json_insert(audit_log, '$[#]', ?) "
            "WHERE command_id = ? AND status = ?",
            (
                CommandStatus.PENDING.value,
                retried_at.isoformat(),
                retried_at.isoformat(),
                f"manual_retry:{retried_at.isoformat()}",
                command_id,
                CommandStatus.FAILED.value,
            ),
        )
        self._connection.commit()
        if updated.rowcount != 1:
            raise ValueError("Only a failed command may be retried")
        command = self.get(command_id)
        assert command is not None
        return command

    def request_cancel(self, command_id: str, now: datetime | None = None) -> ExecutionCommand:
        cancelled_at = now or datetime.now(UTC)
        _require_aware(cancelled_at)
        updated = self._connection.execute(
            "UPDATE execution_commands SET status = ?, updated_at = ?, "
            "cancel_requested_at = ?, cancelled_at = ?, lease_owner = NULL, "
            "lease_expires_at = NULL, audit_log = json_insert(audit_log, '$[#]', ?) "
            "WHERE command_id = ? AND status IN (?, ?, ?)",
            (
                CommandStatus.CANCELLED.value,
                cancelled_at.isoformat(),
                cancelled_at.isoformat(),
                cancelled_at.isoformat(),
                f"cancelled:{cancelled_at.isoformat()}",
                command_id,
                CommandStatus.PENDING.value,
                CommandStatus.RETRY_WAIT.value,
                CommandStatus.RUNNING.value,
            ),
        )
        self._connection.commit()
        if updated.rowcount != 1:
            raise ValueError("Only an active command may be cancelled")
        command = self.get(command_id)
        assert command is not None
        return command


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Queue timestamps must include timezone information")


def _sanitize_error(message: str) -> str:
    return " ".join(message.split())[:500]


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _from_row(row: sqlite3.Row) -> ExecutionCommand:
    return ExecutionCommand(
        command_id=str(row["command_id"]),
        name=str(row["name"]),
        dedupe_key=str(row["dedupe_key"]),
        payload_checksum_sha256=str(row["payload_checksum"]),
        payload=json.loads(row["payload"]),
        workflow_run_id=row["workflow_run_id"],
        status=CommandStatus(row["status"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        available_at=datetime.fromisoformat(row["available_at"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=_optional_datetime(row["lease_expires_at"]),
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        completed_at=_optional_datetime(row["completed_at"]),
        audit_log=tuple(json.loads(row["audit_log"])),
        execution_backend=ExecutionBackend(row["execution_backend"]),
        queue_name=str(row["queue_name"]),
        dispatch_generation=int(row["dispatch_generation"]),
        execution_id=row["execution_id"],
        started_at=_optional_datetime(row["started_at"]),
        cancel_requested_at=_optional_datetime(row["cancel_requested_at"]),
        cancelled_at=_optional_datetime(row["cancelled_at"]),
    )


__all__ = ["CommandPayloadDriftError", "SqliteCommandQueue"]
