"""Durable team-scoped notification records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import notifications


@dataclass(frozen=True)
class Notification:
    notification_id: str
    scope_type: str
    scope_id: str
    kind: str
    title: str
    detail: str
    created_at: datetime
    updated_at: datetime
    action_path: str | None = None
    read_at: datetime | None = None
    payload: dict[str, object] | None = None


class NotificationRepository(Protocol):
    async def save(self, notification: Notification) -> None: ...
    async def list(
        self, *, scope_type: str | None = None, scope_id: str | None = None
    ) -> list[Notification]: ...
    async def mark_read(self, notification_id: str, read_at: datetime) -> Notification: ...


_ADAPTER = TypeAdapter(Notification)


class SqliteNotificationRepository:
    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS notifications (notification_id TEXT PRIMARY KEY, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self._connection.commit()

    async def save(self, notification: Notification) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO notifications(notification_id, scope_type, scope_id, read_at, created_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    notification.notification_id,
                    notification.scope_type,
                    notification.scope_id,
                    notification.read_at.isoformat() if notification.read_at else None,
                    notification.created_at.isoformat(),
                    _ADAPTER.dump_json(notification).decode(),
                ),
            )

    async def list(self, *, scope_type=None, scope_id=None):
        clauses = []
        params = []
        if scope_type is not None:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            params.append(scope_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT payload FROM notifications{where} ORDER BY created_at DESC", params
        ).fetchall()
        return [_ADAPTER.validate_json(row["payload"]) for row in rows]

    async def mark_read(self, notification_id: str, read_at: datetime) -> Notification:
        row = self._connection.execute(
            "SELECT payload FROM notifications WHERE notification_id = ?", (notification_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Notification not found")
        notification = replace(
            _ADAPTER.validate_json(row["payload"]),
            read_at=read_at,
            updated_at=read_at,
        )
        with self._connection:
            self._connection.execute(
                "UPDATE notifications SET read_at = ?, payload = ? WHERE notification_id = ?",
                (read_at.isoformat(), _ADAPTER.dump_json(notification).decode(), notification_id),
            )
        return notification

    def close(self) -> None:
        self._connection.close()


class PostgresNotificationRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, notification: Notification) -> None:
        payload = json.loads(_ADAPTER.dump_json(notification))
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(notifications)
                .values(
                    notification_id=notification.notification_id,
                    scope_type=notification.scope_type,
                    scope_id=notification.scope_id,
                    kind=notification.kind,
                    title=notification.title,
                    detail=notification.detail,
                    action_path=notification.action_path,
                    read_at=notification.read_at,
                    payload=payload,
                    created_at=notification.created_at,
                    updated_at=notification.updated_at,
                )
                .on_conflict_do_nothing(index_elements=[notifications.c.notification_id])
            )

    async def list(self, *, scope_type=None, scope_id=None):
        statement = select(notifications.c.payload)
        if scope_type is not None:
            statement = statement.where(notifications.c.scope_type == scope_type)
        if scope_id is not None:
            statement = statement.where(notifications.c.scope_id == scope_id)
        statement = statement.order_by(notifications.c.created_at.desc())
        async with self._engine.connect() as connection:
            rows = await connection.execute(statement)
        return [_ADAPTER.validate_python(row.payload) for row in rows]

    async def mark_read(self, notification_id: str, read_at: datetime) -> Notification:
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(notifications.c.payload).where(
                        notifications.c.notification_id == notification_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise ValueError("Notification not found")
            notification = replace(
                _ADAPTER.validate_python(row), read_at=read_at, updated_at=read_at
            )
            payload = json.loads(_ADAPTER.dump_json(notification))
            await connection.execute(
                update(notifications)
                .where(notifications.c.notification_id == notification_id)
                .values(read_at=read_at, updated_at=read_at, payload=payload)
            )
        return notification


__all__ = [
    "Notification",
    "NotificationRepository",
    "PostgresNotificationRepository",
    "SqliteNotificationRepository",
]
