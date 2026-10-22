"""Small SQLAlchemy Core helper reused by JSONB snapshot repositories."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Column, Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

T = TypeVar("T")


class PostgresJsonStore(Generic[T]):
    """Persist typed domain snapshots while querying stable columns."""

    def __init__(
        self,
        engine: AsyncEngine,
        table: Table,
        decoder: Callable[[dict[str, Any]], T],
    ) -> None:
        self._engine = engine
        self._table = table
        self._decoder = decoder

    async def upsert(
        self,
        values: Mapping[str, Any],
        update_columns: Sequence[str],
    ) -> None:
        statement = insert(self._table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[self._table.primary_key.columns.values()[0]],
            set_={name: statement.excluded[name] for name in update_columns}
            | {"updated_at": statement.excluded.updated_at},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def insert(self, values: Mapping[str, Any]) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(insert(self._table).values(**values))

    async def get(self, column: Column[Any], value: str) -> T | None:
        statement = select(self._table.c.payload).where(column == value)
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return self._decoder(payload) if payload is not None else None

    async def list(self, *, ascending: bool = False) -> list[T]:
        order = self._table.c.created_at.asc() if ascending else self._table.c.created_at.desc()
        statement = select(self._table.c.payload).order_by(order, self._primary_key().asc())
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [self._decoder(payload) for payload in payloads]

    def _primary_key(self) -> Column[Any]:
        return self._table.primary_key.columns.values()[0]

    def close(self) -> None:
        """Repositories do not own the shared process engine."""


__all__ = ["PostgresJsonStore"]
