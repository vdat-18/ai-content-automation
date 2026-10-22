"""PostgreSQL command queue with concurrent lease-safe claims."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import execution_commands

from .identifiers import command_id_for, payload_checksum
from .models import CommandStatus, EnqueueCommand, ExecutionBackend, ExecutionCommand
from .sqlite_queue import CommandPayloadDriftError


class PostgresCommandQueue:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        """The process composition root owns the shared engine."""

    async def enqueue(
        self, request: EnqueueCommand, now: datetime | None = None
    ) -> tuple[ExecutionCommand, bool]:
        created_at = now or datetime.now(UTC)
        _require_aware(created_at)
        checksum = payload_checksum(request.payload)
        command_id = command_id_for(request.dedupe_key)
        statement = (
            insert(execution_commands)
            .values(
                command_id=command_id,
                name=request.name,
                dedupe_key=request.dedupe_key,
                payload_checksum=checksum,
                payload=request.payload,
                workflow_run_id=request.workflow_run_id,
                status=CommandStatus.PENDING.value,
                attempts=0,
                max_attempts=request.max_attempts,
                created_at=created_at,
                updated_at=created_at,
                available_at=created_at,
                execution_backend=ExecutionBackend.LEASE_WORKER.value,
                queue_name=request.queue_name,
                audit_log=[f"enqueued:{created_at.isoformat()}"],
            )
            .on_conflict_do_nothing(index_elements=[execution_commands.c.dedupe_key])
            .returning(execution_commands)
        )
        async with self._engine.begin() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        created = row is not None
        existing = (
            _from_mapping(row)
            if row is not None
            else await self.get_by_dedupe_key(request.dedupe_key)
        )
        if existing is None:
            raise RuntimeError("Command enqueue did not persist a record")
        if existing.payload_checksum_sha256 != checksum or existing.name != request.name:
            raise CommandPayloadDriftError(
                "Command dedupe key was reused with a different immutable payload"
            )
        return existing, created

    async def get(self, command_id: str) -> ExecutionCommand | None:
        return await self._get(execution_commands.c.command_id, command_id)

    async def get_by_dedupe_key(self, dedupe_key: str) -> ExecutionCommand | None:
        return await self._get(execution_commands.c.dedupe_key, dedupe_key)

    async def _get(self, column, value: str) -> ExecutionCommand | None:
        statement = select(execution_commands).where(column == value)
        async with self._engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        return _from_mapping(row) if row is not None else None

    async def list(
        self,
        status: CommandStatus | None = None,
        workflow_run_id: str | None = None,
    ) -> list[ExecutionCommand]:
        statement = select(execution_commands)
        if status is not None:
            statement = statement.where(execution_commands.c.status == status.value)
        if workflow_run_id is not None:
            statement = statement.where(execution_commands.c.workflow_run_id == workflow_run_id)
        statement = statement.order_by(execution_commands.c.created_at.desc())
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [_from_mapping(row) for row in rows]

    async def claim_next(
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
        async with self._engine.begin() as connection:
            await connection.execute(
                update(execution_commands)
                .where(
                    execution_commands.c.status == CommandStatus.RUNNING.value,
                    execution_commands.c.lease_expires_at <= claimed_at,
                    execution_commands.c.attempts >= execution_commands.c.max_attempts,
                )
                .values(
                    status=CommandStatus.FAILED.value,
                    updated_at=claimed_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code="LEASE_EXHAUSTED",
                    last_error_message="Worker lease expired after the final allowed attempt",
                    audit_log=execution_commands.c.audit_log
                    + [f"lease_exhausted:{claimed_at.isoformat()}"],
                )
            )
            candidate = (
                await connection.execute(
                    select(execution_commands.c.command_id)
                    .where(
                        execution_commands.c.attempts < execution_commands.c.max_attempts,
                        or_(
                            and_(
                                execution_commands.c.status.in_(
                                    (
                                        CommandStatus.PENDING.value,
                                        CommandStatus.RETRY_WAIT.value,
                                    )
                                ),
                                execution_commands.c.available_at <= claimed_at,
                            ),
                            and_(
                                execution_commands.c.status == CommandStatus.RUNNING.value,
                                execution_commands.c.lease_expires_at <= claimed_at,
                            ),
                        ),
                    )
                    .order_by(
                        execution_commands.c.available_at,
                        execution_commands.c.created_at,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if candidate is None:
                return None
            row = (
                (
                    await connection.execute(
                        update(execution_commands)
                        .where(execution_commands.c.command_id == candidate)
                        .values(
                            status=CommandStatus.RUNNING.value,
                            attempts=execution_commands.c.attempts + 1,
                            updated_at=claimed_at,
                            started_at=case(
                                (execution_commands.c.started_at.is_(None), claimed_at),
                                else_=execution_commands.c.started_at,
                            ),
                            lease_owner=worker_id,
                            lease_expires_at=lease_expires_at,
                            audit_log=execution_commands.c.audit_log
                            + [f"claimed:{worker_id}:{claimed_at.isoformat()}"],
                        )
                        .returning(execution_commands)
                    )
                )
                .mappings()
                .one()
            )
        return _from_mapping(row)

    async def claim_command(
        self,
        command_id: str,
        dispatch_generation: int,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 3600,
    ) -> ExecutionCommand | None:
        claimed_at = now or datetime.now(UTC)
        _require_aware(claimed_at)
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        async with self._engine.begin() as connection:
            command = await _find_locked_command(connection, command_id)
            if command is None:
                return None
            if (
                command["execution_backend"] != ExecutionBackend.CELERY.value
                or int(command["dispatch_generation"]) != dispatch_generation
            ):
                return None
            status = CommandStatus(command["status"])
            lease_expired = (
                command["lease_expires_at"] is None or command["lease_expires_at"] <= claimed_at
            )
            if status == CommandStatus.CANCEL_REQUESTED:
                if not lease_expired:
                    return None
                cancelled = await _update_locked_command(
                    connection,
                    command_id,
                    status=CommandStatus.CANCELLED.value,
                    updated_at=claimed_at,
                    cancelled_at=claimed_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    audit_log=command["audit_log"] + [f"cancelled:{claimed_at.isoformat()}"],
                )
                return _from_mapping(cancelled)
            ready = (
                status in {CommandStatus.PENDING, CommandStatus.RETRY_WAIT}
                and command["available_at"] <= claimed_at
            )
            expired = status == CommandStatus.RUNNING and lease_expired
            attempts_exhausted = int(command["attempts"]) >= int(command["max_attempts"])
            if expired and attempts_exhausted:
                failed = await _update_locked_command(
                    connection,
                    command_id,
                    status=CommandStatus.FAILED.value,
                    updated_at=claimed_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code="LEASE_EXHAUSTED",
                    last_error_message="Worker lease expired after the final allowed attempt",
                    audit_log=command["audit_log"] + [f"lease_exhausted:{claimed_at.isoformat()}"],
                )
                return _from_mapping(failed)
            if not (ready or expired) or attempts_exhausted:
                return None
            lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
            claimed = await _update_locked_command(
                connection,
                command_id,
                status=CommandStatus.RUNNING.value,
                attempts=int(command["attempts"]) + 1,
                updated_at=claimed_at,
                started_at=command["started_at"] or claimed_at,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                last_error_code=None,
                last_error_message=None,
                audit_log=command["audit_log"] + [f"claimed:{worker_id}:{claimed_at.isoformat()}"],
            )
        return _from_mapping(claimed)

    async def complete(
        self, command_id: str, worker_id: str, now: datetime | None = None
    ) -> ExecutionCommand:
        completed_at = now or datetime.now(UTC)
        _require_aware(completed_at)
        async with self._engine.begin() as connection:
            command = await _locked_command(connection, command_id)
            if command["lease_owner"] != worker_id or CommandStatus(command["status"]) not in {
                CommandStatus.RUNNING,
                CommandStatus.CANCEL_REQUESTED,
            }:
                raise ValueError("Command completion requires the active worker lease")
            cancelled = CommandStatus(command["status"]) == CommandStatus.CANCEL_REQUESTED
            row = await _update_locked_command(
                connection,
                command_id,
                status=(
                    CommandStatus.CANCELLED.value if cancelled else CommandStatus.COMPLETED.value
                ),
                updated_at=completed_at,
                completed_at=None if cancelled else completed_at,
                cancelled_at=completed_at if cancelled else command["cancelled_at"],
                lease_owner=None,
                lease_expires_at=None,
                audit_log=command["audit_log"]
                + [f"{'cancelled' if cancelled else 'completed'}:{completed_at.isoformat()}"],
            )
        return _from_mapping(row)

    async def renew_lease(
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
        statement = (
            update(execution_commands)
            .where(
                execution_commands.c.command_id == command_id,
                execution_commands.c.status.in_(
                    (CommandStatus.RUNNING.value, CommandStatus.CANCEL_REQUESTED.value)
                ),
                execution_commands.c.lease_owner == worker_id,
            )
            .values(
                updated_at=renewed_at,
                lease_expires_at=renewed_at + timedelta(seconds=lease_seconds),
            )
            .returning(execution_commands)
        )
        async with self._engine.begin() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            raise ValueError("Command lease renewal requires the active worker lease")
        return _from_mapping(row)

    async def request_cancel(
        self, command_id: str, now: datetime | None = None
    ) -> ExecutionCommand:
        requested_at = now or datetime.now(UTC)
        _require_aware(requested_at)
        async with self._engine.begin() as connection:
            command = await _locked_command(connection, command_id)
            status = CommandStatus(command["status"])
            if status == CommandStatus.CANCELLED:
                return _from_mapping(command)
            if status not in {
                CommandStatus.PENDING,
                CommandStatus.RETRY_WAIT,
                CommandStatus.RUNNING,
                CommandStatus.CANCEL_REQUESTED,
            }:
                raise ValueError("Only an active command may be cancelled")
            running = status in {CommandStatus.RUNNING, CommandStatus.CANCEL_REQUESTED}
            row = await _update_locked_command(
                connection,
                command_id,
                status=(
                    CommandStatus.CANCEL_REQUESTED.value
                    if running
                    else CommandStatus.CANCELLED.value
                ),
                updated_at=requested_at,
                cancel_requested_at=requested_at,
                cancelled_at=None if running else requested_at,
                lease_owner=command["lease_owner"] if running else None,
                lease_expires_at=command["lease_expires_at"] if running else None,
                audit_log=command["audit_log"]
                + [f"{'cancel_requested' if running else 'cancelled'}:{requested_at.isoformat()}"],
            )
        return _from_mapping(row)

    async def fail(
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
        async with self._engine.begin() as connection:
            command = (
                (
                    await connection.execute(
                        select(execution_commands)
                        .where(execution_commands.c.command_id == command_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                command is None
                or command["lease_owner"] != worker_id
                or CommandStatus(command["status"])
                not in {CommandStatus.RUNNING, CommandStatus.CANCEL_REQUESTED}
            ):
                raise ValueError("Command failure requires the active worker lease")
            cancelled = CommandStatus(command["status"]) == CommandStatus.CANCEL_REQUESTED
            should_retry = (
                not cancelled and retryable and command["attempts"] < command["max_attempts"]
            )
            status = (
                CommandStatus.CANCELLED
                if cancelled
                else CommandStatus.RETRY_WAIT
                if should_retry
                else CommandStatus.FAILED
            )
            available_at = failed_at + timedelta(seconds=retry_delay_seconds if should_retry else 0)
            row = (
                (
                    await connection.execute(
                        update(execution_commands)
                        .where(execution_commands.c.command_id == command_id)
                        .values(
                            status=status.value,
                            updated_at=failed_at,
                            available_at=available_at,
                            lease_owner=None,
                            lease_expires_at=None,
                            cancelled_at=failed_at if cancelled else command["cancelled_at"],
                            last_error_code=None if cancelled else error_code,
                            last_error_message=(
                                None if cancelled else _sanitize_error(error_message)
                            ),
                            audit_log=execution_commands.c.audit_log
                            + [
                                f"{status.value}:{error_code if not cancelled else 'requested'}:"
                                f"{failed_at.isoformat()}"
                            ],
                        )
                        .returning(execution_commands)
                    )
                )
                .mappings()
                .one()
            )
        return _from_mapping(row)

    async def retry_failed(self, command_id: str, now: datetime | None = None) -> ExecutionCommand:
        retried_at = now or datetime.now(UTC)
        _require_aware(retried_at)
        statement = (
            update(execution_commands)
            .where(
                execution_commands.c.command_id == command_id,
                execution_commands.c.status == CommandStatus.FAILED.value,
            )
            .values(
                status=CommandStatus.PENDING.value,
                updated_at=retried_at,
                available_at=retried_at,
                max_attempts=case(
                    (
                        execution_commands.c.max_attempts <= execution_commands.c.attempts,
                        execution_commands.c.attempts + 1,
                    ),
                    else_=execution_commands.c.max_attempts,
                ),
                completed_at=None,
                audit_log=execution_commands.c.audit_log
                + [f"manual_retry:{retried_at.isoformat()}"],
            )
            .returning(execution_commands)
        )
        async with self._engine.begin() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            raise ValueError("Only a failed command may be retried")
        return _from_mapping(row)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Queue timestamps must include timezone information")


def _sanitize_error(message: str) -> str:
    return " ".join(message.split())[:500]


async def _find_locked_command(connection: Any, command_id: str) -> Any | None:
    return (
        (
            await connection.execute(
                select(execution_commands)
                .where(execution_commands.c.command_id == command_id)
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )


async def _locked_command(connection: Any, command_id: str) -> Any:
    row = await _find_locked_command(connection, command_id)
    if row is None:
        raise ValueError("Execution command not found")
    return row


async def _update_locked_command(connection: Any, command_id: str, **values: Any) -> Any:
    return (
        (
            await connection.execute(
                update(execution_commands)
                .where(execution_commands.c.command_id == command_id)
                .values(**values)
                .returning(execution_commands)
            )
        )
        .mappings()
        .one()
    )


def _from_mapping(row: Any) -> ExecutionCommand:
    return ExecutionCommand(
        command_id=str(row["command_id"]),
        name=str(row["name"]),
        dedupe_key=str(row["dedupe_key"]),
        payload_checksum_sha256=str(row["payload_checksum"]),
        payload=dict(row["payload"]),
        workflow_run_id=row["workflow_run_id"],
        status=CommandStatus(row["status"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        available_at=row["available_at"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        completed_at=row["completed_at"],
        audit_log=tuple(row["audit_log"]),
        execution_backend=ExecutionBackend(row["execution_backend"]),
        queue_name=str(row["queue_name"]),
        dispatch_generation=int(row["dispatch_generation"]),
        execution_id=row["execution_id"],
        started_at=row["started_at"],
        cancel_requested_at=row["cancel_requested_at"],
        cancelled_at=row["cancelled_at"],
    )


__all__ = ["PostgresCommandQueue"]
