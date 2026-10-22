"""Immutable source snapshot artifact writers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ai_content.platform.artifacts import ArtifactKind, ArtifactService, ArtifactStore


class FilesystemSnapshotArtifactWriter:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def publish(self, source_id: str, checksum: str, payload: bytes) -> str:
        path = self._store.write_bytes(
            payload, "data-sources", source_id, checksum, "snapshot.json"
        )
        return str(path)


class ServiceSnapshotArtifactWriter:
    def __init__(self, service: ArtifactService) -> None:
        self._service = service

    async def publish(self, source_id: str, checksum: str, payload: bytes) -> str:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.json"
            source.write_bytes(payload)
            record = await self._service.publish_file(
                source,
                f"data-sources/{source_id}/{checksum}/snapshot.json",
                kind=ArtifactKind.SOURCE,
                owner_type="data_source",
                owner_id=source_id,
            )
        return record.artifact_id


__all__ = ["FilesystemSnapshotArtifactWriter", "ServiceSnapshotArtifactWriter"]
