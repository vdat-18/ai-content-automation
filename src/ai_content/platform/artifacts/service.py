"""Durable artifact publication across PostgreSQL and object storage."""

from __future__ import annotations

import asyncio
import mimetypes
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from ai_content.platform.observability.metrics import (
    ARTIFACT_BYTES,
    ARTIFACT_DURATION,
    ARTIFACT_PUBLICATIONS,
)

from .catalog import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactStatus,
    PostgresArtifactCatalog,
    RetentionClass,
)
from .object_storage import ObjectStorage, normalize_object_key, sha256_file

_CONTENT_TYPES_BY_SUFFIX = {
    ".webp": "image/webp",
}


def _content_type_for_path(source_path: str) -> str:
    suffix = PurePosixPath(source_path).suffix.lower()
    return (
        _CONTENT_TYPES_BY_SUFFIX.get(suffix)
        or mimetypes.guess_type(source_path)[0]
        or "application/octet-stream"
    )


class ArtifactService:
    """Publish immutable objects and expose only catalogued artifacts."""

    def __init__(
        self,
        catalog: PostgresArtifactCatalog,
        storage: ObjectStorage,
        bucket: str,
    ) -> None:
        self.catalog = catalog
        self.storage = storage
        self.bucket = bucket

    async def publish_file(
        self,
        source: Path,
        source_path: str,
        *,
        kind: ArtifactKind = ArtifactKind.PROJECTION,
        retention_class: RetentionClass = RetentionClass.STANDARD,
        owner_type: str = "system",
        owner_id: str = "synthetic-pilot",
        brand_scope: str | None = None,
    ) -> ArtifactRecord:
        started = monotonic()
        normalized_source = normalize_object_key(source_path)
        checksum, size = await asyncio.to_thread(sha256_file, source)
        content_type = _content_type_for_path(normalized_source)
        source_parts = PurePosixPath(normalized_source)
        object_key = normalize_object_key(
            str(PurePosixPath(kind.value) / source_parts.parent / checksum / source_parts.name)
        )
        artifact_id = f"art_{uuid5(NAMESPACE_URL, f'{self.bucket}/{object_key}').hex}"
        now = datetime.now(UTC)
        pending = ArtifactRecord(
            artifact_id=artifact_id,
            bucket=self.bucket,
            object_key=object_key,
            source_path=normalized_source,
            kind=kind,
            status=ArtifactStatus.PENDING,
            sha256=checksum,
            size_bytes=size,
            content_type=content_type,
            retention_class=retention_class,
            owner_type=owner_type,
            owner_id=owner_id,
            brand_scope=brand_scope,
            created_at=now,
            updated_at=now,
        )
        record = await self.catalog.reserve(pending)
        if record.status == ArtifactStatus.AVAILABLE:
            ARTIFACT_PUBLICATIONS.labels(kind=kind.value, outcome="existing").inc()
            ARTIFACT_BYTES.labels(kind=kind.value).observe(record.size_bytes)
            ARTIFACT_DURATION.labels(kind=kind.value).observe(monotonic() - started)
            return record
        try:
            uploaded = await asyncio.to_thread(
                self.storage.put_file,
                object_key,
                source,
                content_type=content_type,
                sha256=checksum,
            )
            if uploaded.sha256 != checksum or uploaded.size_bytes != size:
                raise RuntimeError("Artifact object does not match reserved catalog metadata")
        except Exception:
            ARTIFACT_PUBLICATIONS.labels(kind=kind.value, outcome="failure").inc()
            ARTIFACT_DURATION.labels(kind=kind.value).observe(monotonic() - started)
            await self.catalog.mark_failed(artifact_id)
            raise
        available = await self.catalog.mark_available(artifact_id)
        ARTIFACT_PUBLICATIONS.labels(kind=kind.value, outcome="success").inc()
        ARTIFACT_BYTES.labels(kind=kind.value).observe(size)
        ARTIFACT_DURATION.labels(kind=kind.value).observe(monotonic() - started)
        return available

    async def publish_tree(
        self,
        root: Path,
        *,
        owner_type: str,
        owner_id: str,
    ) -> tuple[ArtifactRecord, ...]:
        root = root.resolve()
        records = []
        for source in sorted(path for path in root.rglob("*") if path.is_file()):
            source_path = source.resolve().relative_to(root).as_posix()
            records.append(
                await self.publish_file(
                    source,
                    source_path,
                    kind=_kind_for_source_path(source_path),
                    owner_type=owner_type,
                    owner_id=owner_id,
                )
            )
        return tuple(records)


def _kind_for_source_path(source_path: str) -> ArtifactKind:
    parts = {part.lower() for part in PurePosixPath(source_path).parts}
    if "inputs" in parts or "source" in parts:
        return ArtifactKind.SOURCE
    if "images" in parts or "versions" in parts:
        return ArtifactKind.GENERATED
    if "review" in parts or "reviews" in parts or "evaluation" in parts:
        return ArtifactKind.EVALUATION
    return ArtifactKind.PROJECTION


__all__ = ["ArtifactService"]
