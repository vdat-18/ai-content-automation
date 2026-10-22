"""Idempotent source synchronization application service."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from ..domain.models import (
    DataSourceDefinition,
    NormalizedRecord,
    SourceSnapshot,
    SyncRun,
    SyncStatus,
)
from ..ports.interfaces import (
    IDataSourceConnector,
    IDataSourceRepository,
    ISnapshotArtifactWriter,
    SourceReadError,
)

_SYNC_ALL_CONCURRENCY = 4
_NORMALIZATION_VERSION = "data-source-normalization@2"
_BACKUP_SCHEMA_VERSION = "shopify-products-normalized@1"
_BACKUP_IMPORT_VERSION = "normalized-backup-import@1"
_LIVE_PRODUCT_NORMALIZATION_VERSION = "shopify-live-product@1"


class DataSourceSyncService:
    def __init__(
        self,
        definitions: tuple[DataSourceDefinition, ...],
        connectors: dict[str, IDataSourceConnector],
        repository: IDataSourceRepository,
        artifacts: ISnapshotArtifactWriter,
    ) -> None:
        self.definitions = {item.source_id: item for item in definitions}
        self._connectors = connectors
        self.repository = repository
        self._artifacts = artifacts

    async def sync(self, source_id: str) -> SyncRun:
        definition = self.definitions.get(source_id)
        if definition is None:
            raise KeyError(source_id)
        started_at = datetime.now(UTC)
        try:
            connector = self._connectors[definition.provider.value]
            records, raw = await connector.fetch(definition)
            records = _scope_records(records, definition)
            canonical = json.dumps(
                {
                    "normalization_version": _NORMALIZATION_VERSION,
                    "source": {
                        "source_id": definition.source_id,
                        "provider": definition.provider.value,
                        "name": definition.name,
                        "base_url": definition.base_url,
                        "resources": definition.resources,
                        "metadata": definition.metadata,
                    },
                    "raw": raw,
                    "records": [
                        {
                            "kind": record.kind,
                            "provider_id": record.provider_id,
                            "data": record.data,
                        }
                        for record in records
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            checksum = hashlib.sha256(canonical).hexdigest()
            previous = await self.repository.latest_snapshot(source_id)
            changed = previous is None or previous.checksum_sha256 != checksum
            if changed:
                snapshot = next(
                    (
                        item
                        for item in await self.repository.list_snapshots()
                        if item.source_id == source_id and item.checksum_sha256 == checksum
                    ),
                    None,
                )
                if snapshot is None:
                    artifact_ref = await self._artifacts.publish(source_id, checksum, canonical)
                    snapshot = SourceSnapshot(
                        snapshot_id=f"dss_{uuid4().hex}",
                        source_id=source_id,
                        provider=definition.provider,
                        checksum_sha256=checksum,
                        record_count=len(records),
                        records=records,
                        artifact_ref=artifact_ref,
                        captured_at=datetime.now(UTC),
                    )
                    await self.repository.save_snapshot(snapshot)
            else:
                snapshot = previous
            assert snapshot is not None
            run = SyncRun(
                run_id=f"dsr_{uuid4().hex}",
                source_id=source_id,
                provider=definition.provider,
                status=SyncStatus.SUCCEEDED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                snapshot_id=snapshot.snapshot_id,
                changed=changed,
                record_count=snapshot.record_count,
            )
        except (SourceReadError, httpx.TimeoutException, httpx.NetworkError) as error:
            code = error.code if isinstance(error, SourceReadError) else "SOURCE_UNAVAILABLE"
            run = SyncRun(
                run_id=f"dsr_{uuid4().hex}",
                source_id=source_id,
                provider=definition.provider,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error_code=code,
                error_message=str(error),
            )
        await self.repository.save_run(run)
        return run

    async def live_product_snapshot(
        self,
        source_id: str,
        product_id: str,
    ) -> SourceSnapshot:
        """Capture immutable current truth for one Shopify product without replacing the catalog."""
        definition = self.definitions.get(source_id)
        if definition is None:
            raise KeyError(source_id)
        if definition.provider.value != "shopify":
            raise SourceReadError(
                "INVALID_CONFIGURATION", "Live product refresh requires a Shopify source"
            )
        connector = self._connectors[definition.provider.value]
        fetch_product = getattr(connector, "fetch_product", None)
        if fetch_product is None:
            raise SourceReadError(
                "INVALID_CONFIGURATION", "Shopify connector cannot refresh one product"
            )
        record, raw = await fetch_product(definition, product_id)
        records = _scope_records((record,), definition)
        canonical = json.dumps(
            {
                "normalization_version": _LIVE_PRODUCT_NORMALIZATION_VERSION,
                "source": {
                    "source_id": definition.source_id,
                    "provider": definition.provider.value,
                    "name": definition.name,
                    "base_url": definition.base_url,
                    "metadata": definition.metadata,
                },
                "requested_product_id": product_id,
                "raw": raw,
                "records": [
                    {
                        "kind": item.kind,
                        "provider_id": item.provider_id,
                        "data": item.data,
                    }
                    for item in records
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        checksum = hashlib.sha256(canonical).hexdigest()
        artifact_ref = await self._artifacts.publish(source_id, checksum, canonical)
        snapshot_key = hashlib.sha256(f"{source_id}:{checksum}".encode()).hexdigest()[:24]
        return SourceSnapshot(
            snapshot_id=f"dsl_{snapshot_key}",
            source_id=source_id,
            provider=definition.provider,
            checksum_sha256=checksum,
            record_count=1,
            records=records,
            artifact_ref=artifact_ref,
            captured_at=datetime.now(UTC),
        )

    async def import_normalized_backup(self, path: Path) -> SyncRun:
        started_at = datetime.now(UTC)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Normalized backup root must be an object")
        if payload.get("schema_version") != _BACKUP_SCHEMA_VERSION:
            raise ValueError("Normalized backup schema version is unsupported")
        source = payload.get("source")
        if not isinstance(source, dict):
            raise ValueError("Normalized backup source metadata is missing")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Normalized backup source_id is missing")
        definition = self.definitions.get(source_id)
        if definition is None:
            raise KeyError(source_id)
        if source.get("provider") != definition.provider.value:
            raise ValueError("Normalized backup provider does not match the configured source")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("Normalized backup records must be a list")
        if payload.get("record_count") != len(raw_records):
            raise ValueError("Normalized backup record count does not match its records")
        records = _scope_records(
            tuple(_normalized_backup_record(item) for item in raw_records),
            definition,
        )
        canonical = json.dumps(
            {
                "normalization_version": _NORMALIZATION_VERSION,
                "import_version": _BACKUP_IMPORT_VERSION,
                "source": {
                    "source_id": definition.source_id,
                    "provider": definition.provider.value,
                    "name": definition.name,
                    "base_url": definition.base_url,
                    "resources": definition.resources,
                    "metadata": definition.metadata,
                },
                "backup": {
                    "schema_version": payload["schema_version"],
                    "captured_at": payload.get("captured_at"),
                    "declared_checksum_sha256": payload.get("checksum_sha256"),
                    "expected_count_at_start": payload.get("expected_count_at_start"),
                },
                "records": [
                    {
                        "kind": record.kind,
                        "provider_id": record.provider_id,
                        "data": record.data,
                    }
                    for record in records
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        checksum = hashlib.sha256(canonical).hexdigest()
        previous = await self.repository.latest_snapshot(source_id)
        changed = previous is None or previous.checksum_sha256 != checksum
        snapshot = previous
        if changed:
            snapshot = next(
                (
                    item
                    for item in await self.repository.list_snapshots()
                    if item.source_id == source_id and item.checksum_sha256 == checksum
                ),
                None,
            )
            if snapshot is None:
                artifact_ref = await self._artifacts.publish(source_id, checksum, canonical)
                snapshot = SourceSnapshot(
                    snapshot_id=f"dss_{uuid4().hex}",
                    source_id=source_id,
                    provider=definition.provider,
                    checksum_sha256=checksum,
                    record_count=len(records),
                    records=records,
                    artifact_ref=artifact_ref,
                    captured_at=datetime.now(UTC),
                )
                await self.repository.save_snapshot(snapshot)
        assert snapshot is not None
        run = SyncRun(
            run_id=f"dsr_{uuid4().hex}",
            source_id=source_id,
            provider=definition.provider,
            status=SyncStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            snapshot_id=snapshot.snapshot_id,
            changed=changed,
            record_count=snapshot.record_count,
        )
        await self.repository.save_run(run)
        return run

    async def sync_all(self) -> tuple[SyncRun, ...]:
        semaphore = asyncio.Semaphore(_SYNC_ALL_CONCURRENCY)

        async def bounded_sync(source_id: str) -> SyncRun:
            async with semaphore:
                return await self.sync(source_id)

        return tuple(await asyncio.gather(*(bounded_sync(item) for item in self.definitions)))


def _normalized_backup_record(payload: object) -> NormalizedRecord:
    if not isinstance(payload, dict):
        raise ValueError("Normalized backup record must be an object")
    kind = payload.get("kind")
    provider_id = payload.get("provider_id")
    data = payload.get("data")
    if not isinstance(kind, str) or not kind:
        raise ValueError("Normalized backup record kind is missing")
    if not isinstance(provider_id, str) or not provider_id:
        raise ValueError("Normalized backup record provider_id is missing")
    if not isinstance(data, dict):
        raise ValueError("Normalized backup record data must be an object")
    return NormalizedRecord(kind=kind, provider_id=provider_id, data=data)


def _scope_records(
    records: tuple[NormalizedRecord, ...],
    definition: DataSourceDefinition,
) -> tuple[NormalizedRecord, ...]:
    brand = definition.metadata.get("brand")
    if not isinstance(brand, str) or not brand.strip():
        return records
    scoped = []
    for record in records:
        if any(str(key).casefold() in {"brand", "brand_id"} for key in record.data):
            scoped.append(record)
            continue
        scoped.append(
            type(record)(
                kind=record.kind,
                provider_id=record.provider_id,
                data={**record.data, "brand": brand.strip()},
            )
        )
    return tuple(scoped)


__all__ = ["DataSourceSyncService"]
