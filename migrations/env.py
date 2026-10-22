"""Alembic environment for the application PostgreSQL schemas."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from ai_content.platform.database.schema import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    """Keep the legacy DBOS-owned schema outside application autogeneration."""
    return not (type_ == "schema" and name == "dbos")


def _database_url() -> str:
    url = os.getenv("AIC_AI_DATABASE_URL")
    if not url:
        raise RuntimeError("AIC_AI_DATABASE_URL is required for database migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=_include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=_include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def _configure_event_loop() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if context.is_offline_mode():
    run_migrations_offline()
else:
    _configure_event_loop()
    asyncio.run(run_migrations_online())
