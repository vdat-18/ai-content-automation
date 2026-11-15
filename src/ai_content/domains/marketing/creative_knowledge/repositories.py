"""PostgreSQL adapter for Creative knowledge."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import (
    creative_knowledge,
    creative_knowledge_bootstraps,
)

from .models import AppliedKnowledgeBootstrap, CreativeKnowledge
from .serialization import knowledge_from_dict, knowledge_to_dict


class PostgresCreativeKnowledgeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, item: CreativeKnowledge) -> None:
        payload = knowledge_to_dict(item)
        values = {
            "knowledge_id": item.knowledge_id,
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
        statement = insert(creative_knowledge).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["knowledge_id"],
            set_={key: value for key, value in values.items() if key != "knowledge_id"},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, knowledge_id: str) -> CreativeKnowledge | None:
        statement = select(creative_knowledge.c.payload).where(
            creative_knowledge.c.knowledge_id == knowledge_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return knowledge_from_dict(payload) if payload else None

    async def list(self) -> list[CreativeKnowledge]:
        statement = select(creative_knowledge.c.payload).order_by(creative_knowledge.c.knowledge_id)
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
