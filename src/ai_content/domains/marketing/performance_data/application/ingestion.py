"""Stream, normalize and reconcile one GMC feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from ..domain.models import (
    GmcIngestionRun,
    GmcIngestionSpec,
    GmcRunStatus,
    NormalizedProductRow,
    ProcessedProductRow,
    ProductFieldStatus,
    RunIssue,
    RunIssueSeverity,
    SourceDescriptor,
)
from ..ports.interfaces import (
    IGmcOutputWriter,
    IGmcRunRepository,
    IGmcSource,
    InputDriftError,
    IProductCatalogReference,
    SourceReadError,
)


@dataclass(frozen=True)
class GmcRunResult:
    run: GmcIngestionRun
    duplicate: bool = False


@dataclass
class _Counters:
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    matched: int = 0
    gmc_only: int = 0
    conflicts: int = 0
    duplicates: int = 0


class RunGmcIngestion:
    """Execute one deterministic, idempotent and memory-bounded GMC run."""

    def __init__(
        self,
        source: IGmcSource,
        catalog: IProductCatalogReference,
        writer: IGmcOutputWriter,
        repository: IGmcRunRepository,
    ) -> None:
        self._source = source
        self._catalog = catalog
        self._writer = writer
        self._repository = repository

    async def execute(self, specification: GmcIngestionSpec) -> GmcRunResult:
        descriptor = self._source.inspect(specification)
        existing = await self._repository.get_by_source_run_id(specification.source_run_id)
        if existing is not None:
            if (
                existing.source.checksum_sha256 != descriptor.checksum_sha256
                or existing.specification.schema_version != specification.schema_version
            ):
                raise InputDriftError(
                    f"source_run_id {specification.source_run_id} was reused with different input"
                )
            return GmcRunResult(existing, duplicate=True)

        issues = self._validate_schema(specification, descriptor)
        if any(issue.severity == RunIssueSeverity.BLOCKING for issue in issues):
            run = self._blocked_run(specification, descriptor, issues)
            await self._repository.save(run)
            return GmcRunResult(run)

        counters = _Counters()
        seen: set[str] = set()
        rows = self._process_rows(specification, counters, issues, seen)
        artifacts = self._writer.write(specification.source_run_id, rows)
        status = (
            GmcRunStatus.BLOCKED
            if any(issue.severity == RunIssueSeverity.BLOCKING for issue in issues)
            else GmcRunStatus.PARTIAL
            if issues or counters.rejected
            else GmcRunStatus.READY
        )
        run = GmcIngestionRun(
            run_id=f"gmc-run-{uuid4().hex}",
            specification=specification,
            source=descriptor,
            status=status,
            total_rows=counters.total,
            accepted_rows=counters.accepted,
            rejected_rows=counters.rejected,
            matched_rows=counters.matched,
            gmc_only_rows=counters.gmc_only,
            conflicting_rows=counters.conflicts,
            duplicate_rows=counters.duplicates,
            issues=tuple(issues),
            normalized_artifact_ref=artifacts.normalized_ref,
            rejected_artifact_ref=artifacts.rejected_ref,
            normalized_checksum_sha256=artifacts.normalized_checksum_sha256,
            rejected_checksum_sha256=artifacts.rejected_checksum_sha256,
            created_at=datetime.now(UTC),
            audit_log=(
                "source_inspected",
                "rows_streamed",
                "schema_validated",
                "catalog_reconciled",
            ),
        )
        await self._repository.save(run)
        return GmcRunResult(run)

    @staticmethod
    def _validate_schema(
        specification: GmcIngestionSpec, descriptor: SourceDescriptor
    ) -> list[RunIssue]:
        missing = [
            column for column in specification.required_columns if column not in descriptor.columns
        ]
        if missing:
            return [
                RunIssue(
                    code="missing_required_columns",
                    severity=RunIssueSeverity.BLOCKING,
                    detail=f"Missing required GMC columns: {', '.join(missing)}",
                    source_ref=descriptor.source_ref,
                )
            ]
        return []

    def _process_rows(
        self,
        specification: GmcIngestionSpec,
        counters: _Counters,
        issues: list[RunIssue],
        seen: set[str],
    ):
        try:
            iterator = self._source.iter_rows(specification.chunk_size)
            for row_number, raw in iterator:
                counters.total += 1
                processed = self._normalize_row(
                    specification, row_number, raw, seen, counters, issues
                )
                if processed.accepted:
                    counters.accepted += 1
                else:
                    counters.rejected += 1
                yield processed
        except SourceReadError as exc:
            issues.append(
                RunIssue(
                    "source_stream_failed",
                    RunIssueSeverity.BLOCKING,
                    str(exc),
                    specification.source_ref,
                )
            )

    def _normalize_row(
        self,
        specification: GmcIngestionSpec,
        row_number: int,
        raw: dict[str, str],
        seen: set[str],
        counters: _Counters,
        issues: list[RunIssue],
    ) -> ProcessedProductRow:
        product_id = raw.get("product_id", "").strip()
        if not product_id:
            return self._reject(row_number, "missing_product_id", "product_id is empty")
        if product_id in seen:
            counters.duplicates += 1
            return self._reject(
                row_number, "duplicate_product_id", f"Duplicate product_id {product_id}"
            )
        seen.add(product_id)
        title = raw.get("title", "").strip()
        if not title:
            return self._reject(row_number, "missing_title", "title is empty")
        availability = raw.get("availability", "").strip() or None
        availability_status = ProductFieldStatus.KNOWN
        if availability is None:
            availability_status = ProductFieldStatus.UNKNOWN
        elif availability not in specification.allowed_availability:
            issues.append(
                RunIssue(
                    "unknown_availability",
                    RunIssueSeverity.WARNING,
                    f"Row {row_number} has unrecognized availability {availability}",
                    product_id,
                )
            )
            availability_status = ProductFieldStatus.UNKNOWN
        price, price_status, price_error = self._decimal_field(raw.get("price", ""), "price")
        if price_error:
            issues.append(
                RunIssue(
                    "invalid_price",
                    RunIssueSeverity.WARNING,
                    f"Row {row_number}: {price_error}",
                    product_id,
                )
            )
        sale_price, _, sale_error = self._decimal_field(raw.get("sale_price", ""), "sale_price")
        if sale_error:
            issues.append(
                RunIssue(
                    "invalid_sale_price",
                    RunIssueSeverity.WARNING,
                    f"Row {row_number}: {sale_error}",
                    product_id,
                )
            )
        matches = self._catalog.find(product_id)
        if len(matches) > 1:
            return self._reject(
                row_number,
                "ambiguous_catalog_mapping",
                f"Multiple catalog mappings for {product_id}",
            )
        catalog = matches[0] if matches else None
        notes: list[str] = []
        reconciliation_status = "gmc_only"
        if catalog is None:
            counters.gmc_only += 1
            issues.append(
                RunIssue(
                    "catalog_unmatched",
                    RunIssueSeverity.WARNING,
                    f"No explicit Shopify mapping for {product_id}",
                    product_id,
                )
            )
        else:
            counters.matched += 1
            reconciliation_status = "matched"
            if price is not None and catalog.price is not None and price != catalog.price:
                counters.conflicts += 1
                reconciliation_status = "conflict"
                notes.append(f"price {price} != catalog {catalog.price}")
                issues.append(
                    RunIssue(
                        "catalog_price_conflict",
                        RunIssueSeverity.WARNING,
                        f"Row {row_number}: {notes[-1]}",
                        product_id,
                    )
                )
            if availability and catalog.availability and availability != catalog.availability:
                counters.conflicts += 1
                reconciliation_status = "conflict"
                notes.append(f"availability {availability} != catalog {catalog.availability}")
                issues.append(
                    RunIssue(
                        "catalog_availability_conflict",
                        RunIssueSeverity.WARNING,
                        f"Row {row_number}: {notes[-1]}",
                        product_id,
                    )
                )
        row = NormalizedProductRow(
            source_row_number=row_number,
            gmc_product_id=product_id,
            offer_id=raw.get("offer_id", "").strip() or None,
            canonical_product_id=catalog.canonical_product_id if catalog else None,
            shopify_sku=catalog.shopify_sku if catalog else None,
            title=title,
            description=raw.get("description", "").strip() or None,
            link=raw.get("link", "").strip() or None,
            image_link=raw.get("image_link", "").strip() or None,
            brand=raw.get("brand", "").strip() or None,
            category=raw.get("google_product_category", "").strip() or None,
            availability=availability,
            availability_status=availability_status,
            price=price,
            price_status=price_status,
            currency=raw.get("currency", "").strip() or None,
            sale_price=sale_price,
            labels=tuple(
                raw.get(f"custom_label_{index}", "").strip() or None for index in range(5)
            ),
            reconciliation_status=reconciliation_status,
            reconciliation_notes=tuple(notes),
        )
        return ProcessedProductRow(row_number, True, row)

    @staticmethod
    def _decimal_field(value: str, name: str):
        if not value.strip():
            return None, ProductFieldStatus.UNKNOWN, None
        try:
            return Decimal(value.strip()), ProductFieldStatus.KNOWN, None
        except InvalidOperation:
            return None, ProductFieldStatus.UNKNOWN, f"invalid {name} value"

    @staticmethod
    def _reject(row_number: int, code: str, detail: str) -> ProcessedProductRow:
        return ProcessedProductRow(row_number, False, None, code, detail)

    @staticmethod
    def _blocked_run(
        specification: GmcIngestionSpec, source: SourceDescriptor, issues: list[RunIssue]
    ) -> GmcIngestionRun:
        return GmcIngestionRun(
            run_id=f"gmc-run-{uuid4().hex}",
            specification=specification,
            source=source,
            status=GmcRunStatus.BLOCKED,
            total_rows=0,
            accepted_rows=0,
            rejected_rows=0,
            matched_rows=0,
            gmc_only_rows=0,
            conflicting_rows=0,
            duplicate_rows=0,
            issues=tuple(issues),
            normalized_artifact_ref=None,
            rejected_artifact_ref=None,
            normalized_checksum_sha256=None,
            rejected_checksum_sha256=None,
            created_at=datetime.now(UTC),
            audit_log=("source_inspected", "schema_validation_blocked"),
        )


__all__ = ["GmcRunResult", "RunGmcIngestion"]
