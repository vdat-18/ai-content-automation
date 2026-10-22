"""Business records for bounded, read-only GMC feed ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _require_identifier(value: str, field_name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")


class GmcRunStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class ProductFieldStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class RunIssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class GmcIngestionSpec:
    source_run_id: str
    brand_id: str
    store_id: str
    schema_version: str
    mapping_version: str
    required_columns: tuple[str, ...]
    allowed_availability: tuple[str, ...]
    chunk_size: int
    source_ref: str

    def __post_init__(self) -> None:
        for name in ("source_run_id", "brand_id", "store_id"):
            _require_identifier(getattr(self, name), name)
        if not self.schema_version.strip() or not self.mapping_version.strip():
            raise ValueError("Schema and mapping versions are required")
        if not self.required_columns or len(set(self.required_columns)) != len(
            self.required_columns
        ):
            raise ValueError("Required columns must be a non-empty unique tuple")
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if not self.source_ref.strip():
            raise ValueError("source_ref is required")


@dataclass(frozen=True)
class SourceDescriptor:
    source_ref: str
    checksum_sha256: str
    size_bytes: int
    columns: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if len(self.checksum_sha256) != 64:
            raise ValueError("Source checksum must be SHA-256")
        if self.size_bytes < 0:
            raise ValueError("Source size cannot be negative")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class CatalogProduct:
    gmc_product_id: str
    canonical_product_id: str
    shopify_sku: str
    price: Decimal | None
    currency: str | None
    availability: str | None

    def __post_init__(self) -> None:
        _require_identifier(self.canonical_product_id, "canonical_product_id")
        if not self.gmc_product_id.strip() or not self.shopify_sku.strip():
            raise ValueError("GMC product ID and Shopify SKU are required")


@dataclass(frozen=True)
class NormalizedProductRow:
    source_row_number: int
    gmc_product_id: str
    offer_id: str | None
    canonical_product_id: str | None
    shopify_sku: str | None
    title: str
    description: str | None
    link: str | None
    image_link: str | None
    brand: str | None
    category: str | None
    availability: str | None
    availability_status: ProductFieldStatus
    price: Decimal | None
    price_status: ProductFieldStatus
    currency: str | None
    sale_price: Decimal | None
    labels: tuple[str | None, ...]
    reconciliation_status: str
    reconciliation_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessedProductRow:
    source_row_number: int
    accepted: bool
    row: NormalizedProductRow | None
    rejection_code: str | None = None
    rejection_detail: str | None = None


@dataclass(frozen=True)
class RunIssue:
    code: str
    severity: RunIssueSeverity
    detail: str
    source_ref: str | None = None


@dataclass(frozen=True)
class GmcIngestionRun:
    run_id: str
    specification: GmcIngestionSpec
    source: SourceDescriptor
    status: GmcRunStatus
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    matched_rows: int
    gmc_only_rows: int
    conflicting_rows: int
    duplicate_rows: int
    issues: tuple[RunIssue, ...]
    normalized_artifact_ref: str | None
    rejected_artifact_ref: str | None
    normalized_checksum_sha256: str | None
    rejected_checksum_sha256: str | None
    created_at: datetime
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_identifier(self.run_id, "run_id")
        _require_aware(self.created_at, "created_at")
        counts = (
            self.total_rows,
            self.accepted_rows,
            self.rejected_rows,
            self.matched_rows,
            self.gmc_only_rows,
            self.conflicting_rows,
            self.duplicate_rows,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Run counts cannot be negative")
        if self.accepted_rows + self.rejected_rows != self.total_rows:
            raise ValueError("Accepted and rejected counts must equal total rows")
