"""PostgreSQL catalog for immutable artifact objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import artifacts


class ArtifactKind(StrEnum):
    SOURCE = "source"
    GENERATED = "generated"
    EVALUATION = "evaluation"
    PROJECTION = "projection"
    TEMPORARY = "temporary"


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"


class RetentionClass(StrEnum):
    STANDARD = "standard"
    TEMPORARY = "temporary"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    bucket: str
    object_key: str
    source_path: str
    kind: ArtifactKind
    status: ArtifactStatus
    sha256: str
    size_bytes: int
    content_type: str
    retention_class: RetentionClass
    owner_type: str
    owner_id: str
    brand_scope: str | None
    created_at: datetime
    updated_at: datetime


class PostgresArtifactCatalog:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def reserve(self, record: ArtifactRecord) -> ArtifactRecord:
        values = _record_values(record)
        statement = (
            insert(artifacts)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[artifacts.c.object_key])
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)
            result = await connection.execute(
                select(artifacts).where(artifacts.c.object_key == record.object_key)
            )
            stored = _row_to_record(result.mappings().one())
        if (
            stored.sha256 != record.sha256
            or stored.size_bytes != record.size_bytes
            or stored.source_path != record.source_path
        ):
            raise ValueError("Artifact object key conflicts with existing catalog metadata")
        return stored

    async def mark_available(self, artifact_id: str) -> ArtifactRecord:
        return await self._set_status(artifact_id, ArtifactStatus.AVAILABLE)

    async def mark_failed(self, artifact_id: str) -> ArtifactRecord:
        return await self._set_status(artifact_id, ArtifactStatus.FAILED)

    async def _set_status(self, artifact_id: str, status: ArtifactStatus) -> ArtifactRecord:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(artifacts)
                .where(artifacts.c.artifact_id == artifact_id)
                .values(status=status.value, updated_at=datetime.now(UTC))
            )
            result = await connection.execute(
                select(artifacts).where(artifacts.c.artifact_id == artifact_id)
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("Artifact catalog record not found")
        return _row_to_record(row)

    async def get(self, artifact_id: str) -> ArtifactRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(artifacts).where(artifacts.c.artifact_id == artifact_id)
            )
        row = result.mappings().one_or_none()
        return _row_to_record(row) if row is not None else None

    async def latest_available(self, source_path: str) -> ArtifactRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(artifacts)
                .where(
                    artifacts.c.source_path == source_path,
                    artifacts.c.status == ArtifactStatus.AVAILABLE.value,
                )
                .order_by(artifacts.c.updated_at.desc(), artifacts.c.artifact_id.desc())
                .limit(1)
            )
        row = result.mappings().one_or_none()
        return _row_to_record(row) if row is not None else None


def _record_values(record: ArtifactRecord) -> dict[str, object]:
    return {
        "artifact_id": record.artifact_id,
        "bucket": record.bucket,
        "object_key": record.object_key,
        "source_path": record.source_path,
        "kind": record.kind.value,
        "status": record.status.value,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "content_type": record.content_type,
        "retention_class": record.retention_class.value,
        "owner_type": record.owner_type,
        "owner_id": record.owner_id,
        "brand_scope": record.brand_scope,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _row_to_record(row) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=row["artifact_id"],
        bucket=row["bucket"],
        object_key=row["object_key"],
        source_path=row["source_path"],
        kind=ArtifactKind(row["kind"]),
        status=ArtifactStatus(row["status"]),
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        content_type=row["content_type"],
        retention_class=RetentionClass(row["retention_class"]),
        owner_type=row["owner_type"],
        owner_id=row["owner_id"],
        brand_scope=row["brand_scope"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = [
    "ArtifactKind",
    "ArtifactRecord",
    "ArtifactStatus",
    "PostgresArtifactCatalog",
    "RetentionClass",
]
