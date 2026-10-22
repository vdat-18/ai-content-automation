"""Atomic streaming artifact writer for normalized and rejected GMC rows."""

from __future__ import annotations

import csv
import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import ProcessedProductRow
from ..ports.interfaces import ArtifactWriteResult

_NORMALIZED_FIELDS = (
    "source_row_number",
    "gmc_product_id",
    "offer_id",
    "canonical_product_id",
    "shopify_sku",
    "title",
    "availability",
    "availability_status",
    "price",
    "price_status",
    "currency",
    "sale_price",
    "brand",
    "category",
    "link",
    "image_link",
    "custom_label_0",
    "custom_label_1",
    "custom_label_2",
    "custom_label_3",
    "custom_label_4",
    "reconciliation_status",
    "reconciliation_notes",
)
_REJECTED_FIELDS = ("source_row_number", "rejection_code", "rejection_detail")


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class CsvGmcOutputWriter:
    """Write both output streams atomically under the configured artifact root."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def write(self, source_run_id: str, rows: Iterable[ProcessedProductRow]) -> ArtifactWriteResult:
        run_dir = self._store.path("performance-data", source_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        normalized_target = run_dir / "normalized.csv"
        rejected_target = run_dir / "rejected.csv"
        pending_paths: list[Path] = []
        try:
            normalized_pending = self._temporary(run_dir)
            rejected_pending = self._temporary(run_dir)
            pending_paths.extend((normalized_pending, rejected_pending))
            with (
                normalized_pending.open("w", encoding="utf-8", newline="") as normalized_file,
                rejected_pending.open("w", encoding="utf-8", newline="") as rejected_file,
            ):
                normalized_writer = csv.DictWriter(normalized_file, fieldnames=_NORMALIZED_FIELDS)
                rejected_writer = csv.DictWriter(rejected_file, fieldnames=_REJECTED_FIELDS)
                normalized_writer.writeheader()
                rejected_writer.writeheader()
                for processed in rows:
                    if not processed.accepted or processed.row is None:
                        rejected_writer.writerow(
                            {
                                "source_row_number": processed.source_row_number,
                                "rejection_code": processed.rejection_code,
                                "rejection_detail": processed.rejection_detail,
                            }
                        )
                        continue
                    row = processed.row
                    labels = tuple(row.labels) + (None,) * (5 - len(row.labels))
                    normalized_writer.writerow(
                        {
                            "source_row_number": row.source_row_number,
                            "gmc_product_id": row.gmc_product_id,
                            "offer_id": row.offer_id,
                            "canonical_product_id": row.canonical_product_id,
                            "shopify_sku": row.shopify_sku,
                            "title": row.title,
                            "availability": row.availability,
                            "availability_status": row.availability_status.value,
                            "price": row.price,
                            "price_status": row.price_status.value,
                            "currency": row.currency,
                            "sale_price": row.sale_price,
                            "brand": row.brand,
                            "category": row.category,
                            "link": row.link,
                            "image_link": row.image_link,
                            **{f"custom_label_{index}": labels[index] for index in range(5)},
                            "reconciliation_status": row.reconciliation_status,
                            "reconciliation_notes": "; ".join(row.reconciliation_notes),
                        }
                    )
                normalized_file.flush()
                rejected_file.flush()
                os.fsync(normalized_file.fileno())
                os.fsync(rejected_file.fileno())
            os.replace(normalized_pending, normalized_target)
            pending_paths.remove(normalized_pending)
            os.replace(rejected_pending, rejected_target)
            pending_paths.remove(rejected_pending)
        finally:
            for pending in pending_paths:
                pending.unlink(missing_ok=True)
        return ArtifactWriteResult(
            normalized_ref=f"performance-data/{source_run_id}/normalized.csv",
            rejected_ref=f"performance-data/{source_run_id}/rejected.csv",
            normalized_checksum_sha256=_checksum(normalized_target),
            rejected_checksum_sha256=_checksum(rejected_target),
        )

    @staticmethod
    def _temporary(directory: Path) -> Path:
        handle, path = tempfile.mkstemp(dir=directory, suffix=".pending")
        os.close(handle)
        return Path(path)
