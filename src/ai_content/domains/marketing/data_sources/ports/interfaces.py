"""Ports for source reads, persistence and immutable artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..domain.models import (
    DataSourceDefinition,
    NormalizedRecord,
    ProductCatalogPage,
    SourceSnapshot,
    SourceSnapshotSummary,
    SyncRun,
)


class SourceReadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IDataSourceConnector(Protocol):
    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]: ...


class IDataSourceRepository(Protocol):
    async def save_run(self, run: SyncRun) -> None: ...

    async def save_snapshot(self, snapshot: SourceSnapshot) -> None: ...

    async def latest_snapshot(self, source_id: str) -> SourceSnapshot | None: ...

    async def latest_snapshot_summary(self, source_id: str) -> SourceSnapshotSummary | None: ...

    async def latest_run(self, source_id: str) -> SyncRun | None: ...

    async def list_snapshots(self) -> list[SourceSnapshot]: ...

    async def get_snapshot(self, snapshot_id: str) -> SourceSnapshot | None: ...

    async def list_latest_snapshots(self) -> list[SourceSnapshot]: ...

    async def list_product_catalog(
        self,
        *,
        source_brands: Mapping[str, str],
        query: str | None,
        limit: int,
    ) -> ProductCatalogPage: ...

    def close(self) -> None: ...


class ISnapshotArtifactWriter(Protocol):
    async def publish(self, source_id: str, checksum: str, payload: bytes) -> str: ...


__all__ = [
    "IDataSourceConnector",
    "IDataSourceRepository",
    "ISnapshotArtifactWriter",
    "SourceReadError",
]
