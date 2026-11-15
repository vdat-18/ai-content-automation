"""PostgreSQL for the tests: the tables are created once, then emptied before each test.

The URL comes from AIC_AI_DATABASE_URL (the Docker `test` service starts a disposable database).
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from ai_content.domains.marketing.creative_knowledge.repositories import (
    PostgresCreativeKnowledgeRepository,
)
from ai_content.domains.marketing.products.repositories import PostgresProductRepository
from ai_content.entrypoints.postgres_runtime import PostgresRuntimeContainer
from ai_content.platform.ai_usage import PostgresAIUsageRepository
from ai_content.platform.database import Database
from ai_content.platform.database.schema import metadata

_state = {"tables_ready": False, "clean": False}


def database_url() -> str:
    return os.environ["AIC_AI_DATABASE_URL"]


def _empty_database() -> None:
    """Create the tables on first use, then remove every row left by an earlier test."""
    engine = create_engine(database_url())
    try:
        with engine.begin() as connection:
            if not _state["tables_ready"]:
                for schema in {table.schema for table in metadata.tables.values() if table.schema}:
                    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                metadata.create_all(connection)
                _state["tables_ready"] = True
            names = ", ".join(f'"{t.schema}"."{t.name}"' for t in metadata.sorted_tables)
            connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()
    _state["clean"] = True


def forget_rows() -> None:
    """Call before each test: the next repository empties the database first."""
    _state["clean"] = False


def _engine() -> AsyncEngine:
    """A new connection for every use, so the engine works in any event loop."""
    if not _state["clean"]:
        _empty_database()
    return create_async_engine(database_url(), poolclass=NullPool)


def product_repository() -> PostgresProductRepository:
    return PostgresProductRepository(_engine())


def knowledge_repository() -> PostgresCreativeKnowledgeRepository:
    return PostgresCreativeKnowledgeRepository(_engine())


def usage_repository() -> PostgresAIUsageRepository:
    return PostgresAIUsageRepository(_engine())


def runtime_container() -> PostgresRuntimeContainer:
    """What the API keeps for its requests, on connections that work in any event loop."""
    database = Database(database_url())
    database.engine = _engine()
    return PostgresRuntimeContainer(database)
