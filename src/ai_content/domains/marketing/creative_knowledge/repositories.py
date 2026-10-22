"""SQLite and PostgreSQL adapters for Creative knowledge."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import (
    creative_knowledge_bootstraps,
    creative_knowledge_versions,
)

from .models import AppliedKnowledgeBootstrap, CreativeKnowledge
from .serialization import knowledge_from_dict, knowledge_to_dict


class SqliteCreativeKnowledgeRepository:
    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS creative_knowledge_versions (
                knowledge_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (knowledge_id, version)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS creative_knowledge_bootstraps (
                bootstrap_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                checksum TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                applied_by TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, item: CreativeKnowledge) -> None:
        self._connection.execute(
            """INSERT INTO creative_knowledge_versions (knowledge_id, version, payload)
               VALUES (?, ?, ?)
               ON CONFLICT(knowledge_id, version) DO UPDATE SET payload=excluded.payload""",
            (item.knowledge_id, item.version, json.dumps(knowledge_to_dict(item))),
        )
        self._connection.commit()

    async def get(self, knowledge_id: str, version: int) -> CreativeKnowledge | None:
        row = self._connection.execute(
            "SELECT payload FROM creative_knowledge_versions WHERE knowledge_id=? AND version=?",
            (knowledge_id, version),
        ).fetchone()
        return knowledge_from_dict(json.loads(row[0])) if row else None

    async def list(self) -> list[CreativeKnowledge]:
        rows = self._connection.execute(
            "SELECT payload FROM creative_knowledge_versions ORDER BY knowledge_id, version"
        ).fetchall()
        return [knowledge_from_dict(json.loads(row[0])) for row in rows]

    async def get_bootstrap(self, bootstrap_id: str) -> AppliedKnowledgeBootstrap | None:
        row = self._connection.execute(
            "SELECT schema_version, checksum, item_count, applied_by, applied_at "
            "FROM creative_knowledge_bootstraps WHERE bootstrap_id=?",
            (bootstrap_id,),
        ).fetchone()
        if row is None:
            return None
        return AppliedKnowledgeBootstrap(
            bootstrap_id=bootstrap_id,
            schema_version=str(row[0]),
            checksum=str(row[1]),
            item_count=int(row[2]),
            applied_by=str(row[3]),
            applied_at=datetime.fromisoformat(str(row[4])),
        )

    async def save_bootstrap(self, bootstrap: AppliedKnowledgeBootstrap) -> None:
        self._connection.execute(
            "INSERT INTO creative_knowledge_bootstraps "
            "(bootstrap_id, schema_version, checksum, item_count, applied_by, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                bootstrap.bootstrap_id,
                bootstrap.schema_version,
                bootstrap.checksum,
                bootstrap.item_count,
                bootstrap.applied_by,
                bootstrap.applied_at.isoformat(),
            ),
        )
        self._connection.commit()


class PostgresCreativeKnowledgeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, item: CreativeKnowledge) -> None:
        payload = knowledge_to_dict(item)
        values = {
            "knowledge_id": item.knowledge_id,
            "version": item.version,
            "knowledge_type": item.knowledge_type.value,
            "status": item.status.value,
            "authority": item.authority.value,
            "brand_id": item.scope.brand_id,
            "niche_id": item.scope.niche_id,
            "product_archetype": item.scope.product_archetype,
            "product_family_id": item.scope.product_family_id,
            "variant_id": item.scope.variant_id,
            "platform": item.scope.platform,
            "market": item.scope.market,
            "asset_type": item.scope.asset_type,
            "task_type": item.scope.task_type,
            "effective_from": item.effective_from,
            "valid_until": item.valid_until,
            "payload": payload,
        }
        statement = insert(creative_knowledge_versions).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["knowledge_id", "version"],
            set_={
                key: value
                for key, value in values.items()
                if key not in {"knowledge_id", "version"}
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, knowledge_id: str, version: int) -> CreativeKnowledge | None:
        statement = select(creative_knowledge_versions.c.payload).where(
            and_(
                creative_knowledge_versions.c.knowledge_id == knowledge_id,
                creative_knowledge_versions.c.version == version,
            )
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return knowledge_from_dict(payload) if payload else None

    async def list(self) -> list[CreativeKnowledge]:
        statement = select(creative_knowledge_versions.c.payload).order_by(
            creative_knowledge_versions.c.knowledge_id,
            creative_knowledge_versions.c.version,
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [knowledge_from_dict(payload) for payload in payloads]

    async def get_bootstrap(self, bootstrap_id: str) -> AppliedKnowledgeBootstrap | None:
        statement = select(creative_knowledge_bootstraps).where(
            creative_knowledge_bootstraps.c.bootstrap_id == bootstrap_id
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return AppliedKnowledgeBootstrap(
            bootstrap_id=str(row["bootstrap_id"]),
            schema_version=str(row["schema_version"]),
            checksum=str(row["checksum"]),
            item_count=int(row["item_count"]),
            applied_by=str(row["applied_by"]),
            applied_at=row["applied_at"],
        )

    async def save_bootstrap(self, bootstrap: AppliedKnowledgeBootstrap) -> None:
        statement = insert(creative_knowledge_bootstraps).values(
            bootstrap_id=bootstrap.bootstrap_id,
            schema_version=bootstrap.schema_version,
            checksum=bootstrap.checksum,
            item_count=bootstrap.item_count,
            applied_by=bootstrap.applied_by,
            applied_at=bootstrap.applied_at,
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)
