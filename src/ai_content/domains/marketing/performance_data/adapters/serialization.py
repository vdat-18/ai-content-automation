"""Stable JSON serialization for GMC ingestion runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.models import (
    GmcIngestionRun,
    GmcIngestionSpec,
    GmcRunStatus,
    RunIssue,
    RunIssueSeverity,
    SourceDescriptor,
)


def run_to_dict(run: GmcIngestionRun) -> dict[str, Any]:
    """Convert one ingestion run to a versioned JSON payload."""
    return {
        "schema_version": 1,
        "run_id": run.run_id,
        "specification": {
            "source_run_id": run.specification.source_run_id,
            "brand_id": run.specification.brand_id,
            "store_id": run.specification.store_id,
            "schema_version": run.specification.schema_version,
            "mapping_version": run.specification.mapping_version,
            "required_columns": list(run.specification.required_columns),
            "allowed_availability": list(run.specification.allowed_availability),
            "chunk_size": run.specification.chunk_size,
            "source_ref": run.specification.source_ref,
        },
        "source": {
            "source_ref": run.source.source_ref,
            "checksum_sha256": run.source.checksum_sha256,
            "size_bytes": run.source.size_bytes,
            "columns": list(run.source.columns),
            "observed_at": run.source.observed_at.isoformat(),
        },
        "status": run.status.value,
        "total_rows": run.total_rows,
        "accepted_rows": run.accepted_rows,
        "rejected_rows": run.rejected_rows,
        "matched_rows": run.matched_rows,
        "gmc_only_rows": run.gmc_only_rows,
        "conflicting_rows": run.conflicting_rows,
        "duplicate_rows": run.duplicate_rows,
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "detail": issue.detail,
                "source_ref": issue.source_ref,
            }
            for issue in run.issues
        ],
        "normalized_artifact_ref": run.normalized_artifact_ref,
        "rejected_artifact_ref": run.rejected_artifact_ref,
        "normalized_checksum_sha256": run.normalized_checksum_sha256,
        "rejected_checksum_sha256": run.rejected_checksum_sha256,
        "created_at": run.created_at.isoformat(),
        "audit_log": list(run.audit_log),
    }


def run_from_dict(data: dict[str, Any]) -> GmcIngestionRun:
    """Restore one persisted ingestion run."""
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported GMC ingestion schema version")
    spec = data["specification"]
    source = data["source"]
    return GmcIngestionRun(
        run_id=data["run_id"],
        specification=GmcIngestionSpec(
            source_run_id=spec["source_run_id"],
            brand_id=spec["brand_id"],
            store_id=spec["store_id"],
            schema_version=spec["schema_version"],
            mapping_version=spec["mapping_version"],
            required_columns=tuple(spec["required_columns"]),
            allowed_availability=tuple(spec["allowed_availability"]),
            chunk_size=spec["chunk_size"],
            source_ref=spec["source_ref"],
        ),
        source=SourceDescriptor(
            source_ref=source["source_ref"],
            checksum_sha256=source["checksum_sha256"],
            size_bytes=source["size_bytes"],
            columns=tuple(source["columns"]),
            observed_at=datetime.fromisoformat(source["observed_at"]),
        ),
        status=GmcRunStatus(data["status"]),
        total_rows=data["total_rows"],
        accepted_rows=data["accepted_rows"],
        rejected_rows=data["rejected_rows"],
        matched_rows=data["matched_rows"],
        gmc_only_rows=data["gmc_only_rows"],
        conflicting_rows=data["conflicting_rows"],
        duplicate_rows=data["duplicate_rows"],
        issues=tuple(
            RunIssue(
                code=issue["code"],
                severity=RunIssueSeverity(issue["severity"]),
                detail=issue["detail"],
                source_ref=issue.get("source_ref"),
            )
            for issue in data["issues"]
        ),
        normalized_artifact_ref=data.get("normalized_artifact_ref"),
        rejected_artifact_ref=data.get("rejected_artifact_ref"),
        normalized_checksum_sha256=data.get("normalized_checksum_sha256"),
        rejected_checksum_sha256=data.get("rejected_checksum_sha256"),
        created_at=datetime.fromisoformat(data["created_at"]),
        audit_log=tuple(data.get("audit_log", ())),
    )


__all__ = ["run_from_dict", "run_to_dict"]
