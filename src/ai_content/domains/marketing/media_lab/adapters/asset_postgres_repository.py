"""PostgreSQL persistence for reusable Media Lab asset metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import media_lab_assets

from ..domain.assets import MediaAsset
from .asset_serialization import asset_from_dict, asset_to_dict


class PostgresMediaAssetRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save(self, asset: MediaAsset) -> None:
        statement = insert(media_lab_assets).values(
            asset_id=asset.asset_id,
            media_kind=asset.media_kind.value,
            state=asset.state.value,
            origin=asset.origin.value,
            checksum_sha256=asset.checksum_sha256,
            source_run_id=asset.source_run_id,
            payload=asset_to_dict(asset),
            created_at=asset.created_at,
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[media_lab_assets.c.asset_id],
            set_={
                "state": statement.excluded.state,
                "origin": statement.excluded.origin,
                "source_run_id": statement.excluded.source_run_id,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, asset_id: str) -> MediaAsset | None:
        statement = select(media_lab_assets.c.payload).where(
            media_lab_assets.c.asset_id == asset_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return asset_from_dict(payload) if payload is not None else None


__all__ = ["PostgresMediaAssetRepository"]
