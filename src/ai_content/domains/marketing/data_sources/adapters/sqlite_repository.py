"""SQLite metadata persistence for sandbox source snapshots."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ..domain.models import (
    DataSourceProvider,
    ProductCatalogPage,
    ProductCatalogRecord,
    SourceSnapshot,
    SourceSnapshotSummary,
    SyncRun,
)
from .serialization import run_from_dict, run_to_dict, snapshot_from_dict, snapshot_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(source_id, checksum_sha256)
);
CREATE TABLE IF NOT EXISTS data_source_sync_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_data_source_snapshots_source ON data_source_snapshots(source_id);
CREATE INDEX IF NOT EXISTS ix_data_source_sync_runs_source ON data_source_sync_runs(source_id);
"""


class SqliteDataSourceRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save_run(self, run: SyncRun) -> None:
        self._connection.execute(
            "INSERT INTO data_source_sync_runs (run_id, source_id, status, payload) VALUES (?, ?, ?, ?)",
            (
                run.run_id,
                run.source_id,
                run.status.value,
                json.dumps(run_to_dict(run), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def save_snapshot(self, snapshot: SourceSnapshot) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO data_source_snapshots "
            "(snapshot_id, source_id, checksum_sha256, payload) VALUES (?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.source_id,
                snapshot.checksum_sha256,
                json.dumps(snapshot_to_dict(snapshot), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def latest_snapshot(self, source_id: str) -> SourceSnapshot | None:
        row = self._connection.execute(
            "SELECT payload FROM data_source_snapshots WHERE source_id = ? ORDER BY rowid DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        return snapshot_from_dict(json.loads(row["payload"])) if row else None

    async def latest_snapshot_summary(self, source_id: str) -> SourceSnapshotSummary | None:
        snapshot = await self.latest_snapshot(source_id)
        if snapshot is None:
            return None
        return SourceSnapshotSummary(
            snapshot_id=snapshot.snapshot_id,
            source_id=snapshot.source_id,
            provider=snapshot.provider,
            record_count=snapshot.record_count,
            artifact_ref=snapshot.artifact_ref,
            captured_at=snapshot.captured_at,
        )

    async def latest_run(self, source_id: str) -> SyncRun | None:
        row = self._connection.execute(
            "SELECT payload FROM data_source_sync_runs WHERE source_id = ? ORDER BY rowid DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        return run_from_dict(json.loads(row["payload"])) if row else None

    async def list_snapshots(self) -> list[SourceSnapshot]:
        rows = self._connection.execute(
            "SELECT payload FROM data_source_snapshots ORDER BY rowid DESC"
        ).fetchall()
        return [snapshot_from_dict(json.loads(row["payload"])) for row in rows]

    async def get_snapshot(self, snapshot_id: str) -> SourceSnapshot | None:
        row = self._connection.execute(
            "SELECT payload FROM data_source_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return snapshot_from_dict(json.loads(row["payload"])) if row else None

    async def list_latest_snapshots(self) -> list[SourceSnapshot]:
        rows = self._connection.execute(
            """
            SELECT current.payload
            FROM data_source_snapshots AS current
            WHERE current.rowid = (
                SELECT candidate.rowid
                FROM data_source_snapshots AS candidate
                WHERE candidate.source_id = current.source_id
                ORDER BY candidate.rowid DESC
                LIMIT 1
            )
            ORDER BY current.source_id
            """
        ).fetchall()
        return [snapshot_from_dict(json.loads(row["payload"])) for row in rows]

    async def list_product_catalog(
        self,
        *,
        source_brands: Mapping[str, str],
        query: str | None,
        limit: int,
    ) -> ProductCatalogPage:
        needle = (query or "").strip().casefold()
        records: list[ProductCatalogRecord] = []
        for snapshot in await self.list_latest_snapshots():
            if (
                snapshot.provider != DataSourceProvider.SHOPIFY
                or snapshot.source_id not in source_brands
            ):
                continue
            for record in snapshot.records:
                if record.kind != "product":
                    continue
                data = record.data
                variants = [item for item in data.get("variants", ()) if isinstance(item, dict)]
                search_values = [
                    data.get("family_key"),
                    data.get("title"),
                    data.get("handle"),
                    *data.get("variant_skus", ()),
                    *(value for item in variants for value in (item.get("sku"), item.get("title"))),
                ]
                if (
                    needle
                    and needle
                    not in " ".join(str(value) for value in search_values if value).casefold()
                ):
                    continue
                records.append(
                    ProductCatalogRecord(
                        snapshot_id=snapshot.snapshot_id,
                        source_id=snapshot.source_id,
                        provider_id=record.provider_id,
                        data=data,
                    )
                )
        records.sort(
            key=lambda record: (
                str(record.data.get("brand") or source_brands[record.source_id]),
                str(record.data.get("title") or "").casefold(),
                record.provider_id,
            )
        )
        return ProductCatalogPage(records=tuple(records[:limit]), total=len(records))


__all__ = ["SqliteDataSourceRepository"]
