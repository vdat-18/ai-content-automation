"""Async PostgreSQL engine lifecycle."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Database:
    """Own one process-wide SQLAlchemy async engine."""

    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": 5},
        )

    async def check(self) -> None:
        """Fail if PostgreSQL or the migrated application schema is unavailable."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SET LOCAL statement_timeout = '3s'"))
            result = await connection.execute(
                text(
                    "SELECT to_regclass('platform.execution_commands'), "
                    "to_regclass('platform.artifacts'), "
                    "to_regclass('platform.ai_usage_events'), "
                    "to_regclass('marketing.data_source_snapshots'), "
                    "to_regclass('marketing.data_source_sync_runs')"
                )
            )
            required_tables = result.one()
            if any(table is None for table in required_tables):
                raise RuntimeError("PostgreSQL application schema is not migrated")

    async def close(self) -> None:
        await self.engine.dispose()


__all__ = ["Database", "AsyncEngine"]
