from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.models import (
    DataSourceProvider,
    NormalizedRecord,
    SourceSnapshot,
    SyncRun,
    SyncStatus,
)


def snapshot_to_dict(snapshot: SourceSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "source_id": snapshot.source_id,
        "provider": snapshot.provider.value,
        "checksum_sha256": snapshot.checksum_sha256,
        "record_count": snapshot.record_count,
        "records": [
            {"kind": item.kind, "provider_id": item.provider_id, "data": item.data}
            for item in snapshot.records
        ],
        "artifact_ref": snapshot.artifact_ref,
        "captured_at": snapshot.captured_at.isoformat(),
    }


def snapshot_from_dict(payload: dict[str, Any]) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id=payload["snapshot_id"],
        source_id=payload["source_id"],
        provider=DataSourceProvider(payload["provider"]),
        checksum_sha256=payload["checksum_sha256"],
        record_count=payload["record_count"],
        records=tuple(
            NormalizedRecord(item["kind"], item["provider_id"], item["data"])
            for item in payload["records"]
        ),
        artifact_ref=payload["artifact_ref"],
        captured_at=datetime.fromisoformat(payload["captured_at"]),
    )


def run_to_dict(run: SyncRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "source_id": run.source_id,
        "provider": run.provider.value,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat(),
        "snapshot_id": run.snapshot_id,
        "changed": run.changed,
        "record_count": run.record_count,
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


def run_from_dict(payload: dict[str, Any]) -> SyncRun:
    return SyncRun(
        run_id=payload["run_id"],
        source_id=payload["source_id"],
        provider=DataSourceProvider(payload["provider"]),
        status=SyncStatus(payload["status"]),
        started_at=datetime.fromisoformat(payload["started_at"]),
        completed_at=datetime.fromisoformat(payload["completed_at"]),
        snapshot_id=payload.get("snapshot_id"),
        changed=payload.get("changed"),
        record_count=payload.get("record_count", 0),
        error_code=payload.get("error_code"),
        error_message=payload.get("error_message"),
    )


__all__ = ["run_from_dict", "run_to_dict", "snapshot_from_dict", "snapshot_to_dict"]
