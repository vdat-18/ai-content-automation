"""PostgreSQL metadata persistence for sandbox source snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import (
    data_source_product_catalog,
    data_source_snapshots,
    data_source_sync_runs,
)

from ..domain.models import (
    DataSourceProvider,
    ProductCatalogPage,
    ProductCatalogRecord,
    SourceSnapshot,
    SourceSnapshotSummary,
    SyncRun,
)
from .serialization import run_from_dict, run_to_dict, snapshot_from_dict, snapshot_to_dict

_INDEX_PRODUCT_SNAPSHOT = text(
    """
    INSERT INTO marketing.data_source_product_catalog (
        snapshot_id,
        source_id,
        provider_id,
        brand,
        title,
        search_text,
        data
    )
    SELECT
        snapshot.snapshot_id,
        snapshot.source_id,
        record.item ->> 'provider_id',
        COALESCE(record.item -> 'data' ->> 'brand', ''),
        COALESCE(
            record.item -> 'data' ->> 'title',
            record.item -> 'data' ->> 'family_key',
            record.item -> 'data' ->> 'sku',
            record.item -> 'data' ->> 'handle',
            record.item ->> 'provider_id'
        ),
        lower(concat_ws(
            ' ',
            record.item -> 'data' ->> 'family_key',
            record.item -> 'data' ->> 'title',
            record.item -> 'data' ->> 'handle',
            variant_skus.value,
            variants.value
        )),
        record.item -> 'data'
    FROM marketing.data_source_snapshots AS snapshot
    CROSS JOIN LATERAL jsonb_array_elements(snapshot.payload -> 'records') AS record(item)
    LEFT JOIN LATERAL (
        SELECT string_agg(sku.value, ' ') AS value
        FROM jsonb_array_elements_text(
            COALESCE(record.item -> 'data' -> 'variant_skus', '[]'::jsonb)
        ) AS sku(value)
    ) AS variant_skus ON true
    LEFT JOIN LATERAL (
        SELECT string_agg(
            concat_ws(' ', variant.item ->> 'sku', variant.item ->> 'title'),
            ' '
        ) AS value
        FROM jsonb_array_elements(
            COALESCE(record.item -> 'data' -> 'variants', '[]'::jsonb)
        ) AS variant(item)
    ) AS variants ON true
    WHERE snapshot.snapshot_id = :snapshot_id
      AND snapshot.provider = 'shopify'
      AND record.item ->> 'kind' = 'product'
    ON CONFLICT DO NOTHING
    """
)


class PostgresDataSourceRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass

    async def save_run(self, run: SyncRun) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(data_source_sync_runs).values(
                    run_id=run.run_id,
                    source_id=run.source_id,
                    provider=run.provider.value,
                    status=run.status.value,
                    payload=run_to_dict(run),
                    created_at=run.completed_at,
                    updated_at=run.completed_at,
                )
            )

    async def save_snapshot(self, snapshot: SourceSnapshot) -> None:
        statement = (
            insert(data_source_snapshots)
            .values(
                snapshot_id=snapshot.snapshot_id,
                source_id=snapshot.source_id,
                provider=snapshot.provider.value,
                checksum_sha256=snapshot.checksum_sha256,
                record_count=snapshot.record_count,
                artifact_ref=snapshot.artifact_ref,
                payload=snapshot_to_dict(snapshot),
                created_at=snapshot.captured_at,
                updated_at=snapshot.captured_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    data_source_snapshots.c.source_id,
                    data_source_snapshots.c.checksum_sha256,
                ]
            )
            .returning(data_source_snapshots.c.snapshot_id)
        )
        async with self._engine.begin() as connection:
            inserted_snapshot_id = (await connection.execute(statement)).scalar_one_or_none()
            if inserted_snapshot_id is not None:
                await connection.execute(
                    _INDEX_PRODUCT_SNAPSHOT,
                    {"snapshot_id": inserted_snapshot_id},
                )

    async def latest_snapshot(self, source_id: str) -> SourceSnapshot | None:
        statement = (
            select(data_source_snapshots.c.payload)
            .where(data_source_snapshots.c.source_id == source_id)
            .order_by(
                data_source_snapshots.c.created_at.desc(),
                data_source_snapshots.c.snapshot_id.desc(),
            )
            .limit(1)
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return snapshot_from_dict(payload) if payload is not None else None

    async def latest_snapshot_summary(self, source_id: str) -> SourceSnapshotSummary | None:
        statement = (
            select(
                data_source_snapshots.c.snapshot_id,
                data_source_snapshots.c.source_id,
                data_source_snapshots.c.provider,
                data_source_snapshots.c.record_count,
                data_source_snapshots.c.artifact_ref,
                data_source_snapshots.c.created_at,
            )
            .where(data_source_snapshots.c.source_id == source_id)
            .order_by(
                data_source_snapshots.c.created_at.desc(),
                data_source_snapshots.c.snapshot_id.desc(),
            )
            .limit(1)
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return SourceSnapshotSummary(
            snapshot_id=row["snapshot_id"],
            source_id=row["source_id"],
            provider=DataSourceProvider(row["provider"]),
            record_count=row["record_count"],
            artifact_ref=row["artifact_ref"],
            captured_at=row["created_at"],
        )

    async def latest_run(self, source_id: str) -> SyncRun | None:
        statement = (
            select(data_source_sync_runs.c.payload)
            .where(data_source_sync_runs.c.source_id == source_id)
            .order_by(
                data_source_sync_runs.c.created_at.desc(), data_source_sync_runs.c.run_id.desc()
            )
            .limit(1)
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return run_from_dict(payload) if payload is not None else None

    async def list_snapshots(self) -> list[SourceSnapshot]:
        statement = select(data_source_snapshots.c.payload).order_by(
            data_source_snapshots.c.created_at.desc(), data_source_snapshots.c.snapshot_id.desc()
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [snapshot_from_dict(payload) for payload in payloads]

    async def get_snapshot(self, snapshot_id: str) -> SourceSnapshot | None:
        statement = select(data_source_snapshots.c.payload).where(
            data_source_snapshots.c.snapshot_id == snapshot_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return snapshot_from_dict(payload) if payload is not None else None

    async def list_latest_snapshots(self) -> list[SourceSnapshot]:
        statement = (
            select(data_source_snapshots.c.payload)
            .distinct(data_source_snapshots.c.source_id)
            .order_by(
                data_source_snapshots.c.source_id,
                data_source_snapshots.c.created_at.desc(),
                data_source_snapshots.c.snapshot_id.desc(),
            )
        )
        async with self._engine.connect() as connection:
            payloads = (await connection.execute(statement)).scalars().all()
        return [snapshot_from_dict(payload) for payload in payloads]

    async def list_product_catalog(
        self,
        *,
        source_brands: Mapping[str, str],
        query: str | None,
        limit: int,
    ) -> ProductCatalogPage:
        if not source_brands:
            return ProductCatalogPage(records=(), total=0)

        latest_snapshots = (
            select(
                data_source_snapshots.c.snapshot_id,
                data_source_snapshots.c.source_id,
            )
            .where(
                data_source_snapshots.c.provider == DataSourceProvider.SHOPIFY.value,
                data_source_snapshots.c.source_id.in_(tuple(source_brands)),
            )
            .distinct(data_source_snapshots.c.source_id)
            .order_by(
                data_source_snapshots.c.source_id,
                data_source_snapshots.c.created_at.desc(),
                data_source_snapshots.c.snapshot_id.desc(),
            )
            .cte("latest_product_snapshots")
        )
        catalog = data_source_product_catalog
        catalog_join = catalog.join(
            latest_snapshots,
            (catalog.c.snapshot_id == latest_snapshots.c.snapshot_id)
            & (catalog.c.source_id == latest_snapshots.c.source_id),
        )
        criteria = []
        needle = (query or "").strip().casefold()
        if needle:
            criteria.append(func.strpos(catalog.c.search_text, needle) > 0)
        source_brand = case(source_brands, value=catalog.c.source_id, else_="")
        effective_brand = func.coalesce(func.nullif(catalog.c.brand, ""), source_brand)
        count_statement = select(func.count()).select_from(catalog_join).where(*criteria)
        records_statement = (
            select(
                catalog.c.snapshot_id,
                catalog.c.source_id,
                catalog.c.provider_id,
                catalog.c.data,
            )
            .select_from(catalog_join)
            .where(*criteria)
            .order_by(
                effective_brand,
                func.lower(catalog.c.title),
                catalog.c.provider_id,
            )
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            total = int((await connection.execute(count_statement)).scalar_one())
            rows = (await connection.execute(records_statement)).mappings().all()
        return ProductCatalogPage(
            records=tuple(
                ProductCatalogRecord(
                    snapshot_id=row["snapshot_id"],
                    source_id=row["source_id"],
                    provider_id=row["provider_id"],
                    data=dict(row["data"]),
                )
                for row in rows
            ),
            total=total,
        )


__all__ = ["PostgresDataSourceRepository"]
