"""Celery scheduler backed by an atomic PostgreSQL transactional outbox."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ai_content.platform.database.schema import execution_commands, execution_outbox

from .identifiers import command_id_for, execution_id_for, outbox_id_for, payload_checksum
from .models import CommandStatus, EnqueueCommand, ExecutionBackend, ExecutionCommand
from .postgres_queue import PostgresCommandQueue, _from_mapping
from .sqlite_queue import CommandPayloadDriftError

CELERY_CONTROL_QUEUE = "control"
CELERY_EXECUTE_COMMAND_TASK = "aicontent.execution.execute_command"


class CeleryCommandScheduler:
    """Persist commands and broker publication intents in one transaction."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._status = PostgresCommandQueue(engine)

    async def enqueue(
        self, request: EnqueueCommand, now: datetime | None = None
    ) -> tuple[ExecutionCommand, bool]:
        created_at = now or datetime.now(UTC)
        _require_aware(created_at)
        if request.queue_name != CELERY_CONTROL_QUEUE:
            raise ValueError("Celery execution currently supports only the control queue")
        async with self._engine.begin() as connection:
            return await enqueue_celery_command(connection, request, created_at)

    async def get(self, command_id: str) -> ExecutionCommand | None:
        return await self._status.get(command_id)

    async def get_by_dedupe_key(self, dedupe_key: str) -> ExecutionCommand | None:
        return await self._status.get_by_dedupe_key(dedupe_key)

    async def list(
        self,
        status: CommandStatus | None = None,
        workflow_run_id: str | None = None,
    ) -> list[ExecutionCommand]:
        return await self._status.list(status=status, workflow_run_id=workflow_run_id)

    async def retry_failed(self, command_id: str, now: datetime | None = None) -> ExecutionCommand:
        retried_at = now or datetime.now(UTC)
        _require_aware(retried_at)
        async with self._engine.begin() as connection:
            row = (
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
            if row is None or row["status"] != CommandStatus.FAILED.value:
                raise ValueError("Only a failed command may be retried through Celery")
            generation = int(row["dispatch_generation"]) + 1
            execution_id = execution_id_for(command_id, generation)
            updated = (
                (
                    await connection.execute(
                        update(execution_commands)
                        .where(execution_commands.c.command_id == command_id)
                        .values(
                            status=CommandStatus.PENDING.value,
                            updated_at=retried_at,
                            available_at=retried_at,
                            max_attempts=case(
                                (
                                    execution_commands.c.max_attempts
                                    <= execution_commands.c.attempts,
                                    execution_commands.c.attempts + 1,
                                ),
                                else_=execution_commands.c.max_attempts,
                            ),
                            dispatch_generation=generation,
                            execution_id=execution_id,
                            execution_backend=ExecutionBackend.CELERY.value,
                            queue_name=CELERY_CONTROL_QUEUE,
                            completed_at=None,
                            cancelled_at=None,
                            cancel_requested_at=None,
                            lease_owner=None,
                            lease_expires_at=None,
                            last_error_code=None,
                            last_error_message=None,
                            audit_log=row["audit_log"]
                            + [f"manual_retry:{generation}:{retried_at.isoformat()}"],
                        )
                        .returning(execution_commands)
                    )
                )
                .mappings()
                .one()
            )
            command = _from_mapping(updated)
            await _insert_outbox(connection, command, retried_at)
        return command

    async def request_cancel(
        self, command_id: str, now: datetime | None = None
    ) -> ExecutionCommand:
        return await self._status.request_cancel(command_id, now=now)

    def close(self) -> None:
        """The composition root owns the shared database engine."""


async def enqueue_celery_command(
    connection: AsyncConnection,
    request: EnqueueCommand,
    created_at: datetime,
) -> tuple[ExecutionCommand, bool]:
    """Persist one command and outbox intent inside the caller's transaction."""
    _require_aware(created_at)
    if request.queue_name != CELERY_CONTROL_QUEUE:
        raise ValueError("Celery execution currently supports only the control queue")
    command_id = command_id_for(request.dedupe_key)
    dispatch_generation = 0
    execution_id = execution_id_for(command_id, dispatch_generation)
    checksum = payload_checksum(request.payload)
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
            execution_backend=ExecutionBackend.CELERY.value,
            queue_name=request.queue_name,
            dispatch_generation=dispatch_generation,
            execution_id=execution_id,
            audit_log=[f"enqueued:{created_at.isoformat()}"],
        )
        .on_conflict_do_nothing(index_elements=[execution_commands.c.dedupe_key])
        .returning(execution_commands)
    )
    row = (await connection.execute(statement)).mappings().one_or_none()
    created = row is not None
    if row is None:
        row = (
            (
                await connection.execute(
                    select(execution_commands).where(
                        execution_commands.c.dedupe_key == request.dedupe_key
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise RuntimeError("Command enqueue did not persist a record")
    command = _from_mapping(row)
    _validate_replay(command, request, checksum)
    if created:
        await _insert_outbox(connection, command, created_at)
    return command, created


async def _insert_outbox(connection, command: ExecutionCommand, now: datetime) -> None:
    await connection.execute(
        insert(execution_outbox).values(
            outbox_id=outbox_id_for(command.command_id, command.dispatch_generation),
            command_id=command.command_id,
            dispatch_generation=command.dispatch_generation,
            task_name=CELERY_EXECUTE_COMMAND_TASK,
            queue_name=command.queue_name,
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _validate_replay(
    command: ExecutionCommand,
    request: EnqueueCommand,
    checksum: str,
) -> None:
    if command.payload_checksum_sha256 != checksum or command.name != request.name:
        raise CommandPayloadDriftError(
            "Command dedupe key was reused with a different immutable payload"
        )
    if command.execution_backend != ExecutionBackend.CELERY and command.status not in {
        CommandStatus.COMPLETED,
        CommandStatus.FAILED,
        CommandStatus.CANCELLED,
    }:
        raise ValueError("Command dedupe key belongs to a different execution backend")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Scheduler timestamps must include timezone information")


__all__ = [
    "CELERY_CONTROL_QUEUE",
    "CELERY_EXECUTE_COMMAND_TASK",
    "CeleryCommandScheduler",
    "enqueue_celery_command",
]
