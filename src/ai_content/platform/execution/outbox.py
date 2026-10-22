"""Transactional outbox records for reliable Celery task publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import execution_commands, execution_outbox


@dataclass(frozen=True)
class OutboxMessage:
    outbox_id: str
    command_id: str
    dispatch_generation: int
    task_name: str
    queue_name: str
    attempts: int


class PostgresExecutionOutbox:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim_batch(
        self,
        publisher_id: str,
        *,
        limit: int = 20,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> list[OutboxMessage]:
        claimed_at = now or datetime.now(UTC)
        _require_aware(claimed_at)
        if limit < 1:
            raise ValueError("Outbox batch limit must be positive")
        if lease_seconds < 1:
            raise ValueError("Outbox lease must be positive")
        lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        async with self._engine.begin() as connection:
            rows = (
                (
                    await connection.execute(
                        select(execution_outbox)
                        .where(
                            execution_outbox.c.available_at <= claimed_at,
                            or_(
                                execution_outbox.c.status == "pending",
                                and_(
                                    execution_outbox.c.status == "publishing",
                                    execution_outbox.c.lease_expires_at <= claimed_at,
                                ),
                            ),
                        )
                        .order_by(
                            execution_outbox.c.available_at,
                            execution_outbox.c.created_at,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                return []
            identifiers = [str(row["outbox_id"]) for row in rows]
            claimed = (
                (
                    await connection.execute(
                        update(execution_outbox)
                        .where(execution_outbox.c.outbox_id.in_(identifiers))
                        .values(
                            status="publishing",
                            attempts=execution_outbox.c.attempts + 1,
                            updated_at=claimed_at,
                            lease_owner=publisher_id,
                            lease_expires_at=lease_expires_at,
                        )
                        .returning(execution_outbox)
                    )
                )
                .mappings()
                .all()
            )
        return [_from_mapping(row) for row in claimed]

    async def requeue_active_commands_after_restore(
        self,
        now: datetime | None = None,
    ) -> int:
        """Recreate broker publication intent from canonical PostgreSQL state."""
        recovered_at = now or datetime.now(UTC)
        _require_aware(recovered_at)
        active_statuses = (
            "pending",
            "running",
            "retry_wait",
            "cancel_requested",
        )
        active_filter = and_(
            execution_commands.c.execution_backend == "celery",
            execution_commands.c.status.in_(active_statuses),
        )
        async with self._engine.begin() as connection:
            active_count = int(
                (
                    await connection.execute(
                        select(func.count()).select_from(execution_commands).where(active_filter)
                    )
                ).scalar_one()
            )
            result = await connection.execute(
                update(execution_outbox)
                .where(
                    execution_outbox.c.command_id == execution_commands.c.command_id,
                    execution_outbox.c.dispatch_generation
                    == execution_commands.c.dispatch_generation,
                    active_filter,
                )
                .values(
                    status="pending",
                    available_at=recovered_at,
                    updated_at=recovered_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    published_at=None,
                    last_error_message=None,
                )
            )
            recovered = int(result.rowcount or 0)
            if recovered != active_count:
                raise ValueError("Every active Celery command must have a current outbox record")
        return recovered

    async def mark_published(
        self,
        outbox_id: str,
        publisher_id: str,
        now: datetime | None = None,
    ) -> None:
        published_at = now or datetime.now(UTC)
        _require_aware(published_at)
        statement = (
            update(execution_outbox)
            .where(
                execution_outbox.c.outbox_id == outbox_id,
                execution_outbox.c.status == "publishing",
                execution_outbox.c.lease_owner == publisher_id,
            )
            .values(
                status="published",
                updated_at=published_at,
                published_at=published_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error_message=None,
            )
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        if result.rowcount != 1:
            raise ValueError("Outbox publication requires the active publisher lease")

    async def release(
        self,
        outbox_id: str,
        publisher_id: str,
        error_message: str,
        *,
        retry_delay_seconds: int,
        now: datetime | None = None,
    ) -> None:
        released_at = now or datetime.now(UTC)
        _require_aware(released_at)
        if retry_delay_seconds < 0:
            raise ValueError("Outbox retry delay must not be negative")
        statement = (
            update(execution_outbox)
            .where(
                execution_outbox.c.outbox_id == outbox_id,
                execution_outbox.c.status == "publishing",
                execution_outbox.c.lease_owner == publisher_id,
            )
            .values(
                status="pending",
                updated_at=released_at,
                available_at=released_at + timedelta(seconds=retry_delay_seconds),
                lease_owner=None,
                lease_expires_at=None,
                last_error_message=_sanitize_error(error_message),
            )
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        if result.rowcount != 1:
            raise ValueError("Outbox release requires the active publisher lease")


def _from_mapping(row) -> OutboxMessage:
    return OutboxMessage(
        outbox_id=str(row["outbox_id"]),
        command_id=str(row["command_id"]),
        dispatch_generation=int(row["dispatch_generation"]),
        task_name=str(row["task_name"]),
        queue_name=str(row["queue_name"]),
        attempts=int(row["attempts"]),
    )


def _sanitize_error(message: str) -> str:
    return " ".join(message.split())[:500]


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Outbox timestamps must include timezone information")


__all__ = ["OutboxMessage", "PostgresExecutionOutbox"]
