"""Provider-neutral records for read-only source synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class DataSourceProvider(StrEnum):
    SHOPIFY = "shopify"
    LARK = "lark"
    GOOGLE = "google"
    META_ADS = "meta_ads"
    GOOGLE_ADS = "google_ads"
    PINTEREST_ADS = "pinterest_ads"
    GOOGLE_MERCHANT = "google_merchant"
    KLAVIYO = "klaviyo"


class SyncStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class DataSourceDefinition:
    source_id: str
    provider: DataSourceProvider
    name: str
    category: str
    purpose: str
    base_url: str
    resources: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class NormalizedRecord:
    kind: str
    provider_id: str
    data: dict[str, Any]


@dataclass(frozen=True)
class SourceSnapshot:
    snapshot_id: str
    source_id: str
    provider: DataSourceProvider
    checksum_sha256: str
    record_count: int
    records: tuple[NormalizedRecord, ...]
    artifact_ref: str
    captured_at: datetime


@dataclass(frozen=True)
class SourceSnapshotSummary:
    snapshot_id: str
    source_id: str
    provider: DataSourceProvider
    record_count: int
    artifact_ref: str
    captured_at: datetime


@dataclass(frozen=True)
class ProductCatalogRecord:
    snapshot_id: str
    source_id: str
    provider_id: str
    data: dict[str, Any]


@dataclass(frozen=True)
class ProductCatalogPage:
    records: tuple[ProductCatalogRecord, ...]
    total: int


@dataclass(frozen=True)
class SyncRun:
    run_id: str
    source_id: str
    provider: DataSourceProvider
    status: SyncStatus
    started_at: datetime
    completed_at: datetime
    snapshot_id: str | None = None
    changed: bool | None = None
    record_count: int = 0
    error_code: str | None = None
    error_message: str | None = None


__all__ = [
    "DataSourceDefinition",
    "DataSourceProvider",
    "NormalizedRecord",
    "ProductCatalogPage",
    "ProductCatalogRecord",
    "SourceSnapshot",
    "SourceSnapshotSummary",
    "SyncRun",
    "SyncStatus",
]
