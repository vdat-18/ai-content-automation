"""Artifact adapters for reusable Media Lab assets."""

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath

from ai_content.platform.artifacts import (
    ArtifactKind,
    ArtifactService,
    ArtifactStatus,
    ArtifactStore,
    ObjectStorage,
    ObjectStorageError,
    PostgresArtifactCatalog,
)
from ai_content.platform.artifacts.object_storage import iter_download

from ..ports.assets import MediaAssetError


class FilesystemMediaAssetArtifacts:
    """Media asset artifacts backed by the native development/test store."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def write_file(
        self,
        asset_id: str,
        name: str,
        source: Path,
        *,
        content_type: str,
        generated: bool,
    ) -> str:
        del content_type, generated
        path = await asyncio.to_thread(
            self._store.copy_file,
            source,
            "media-lab",
            "assets",
            asset_id,
            name,
        )
        return path.relative_to(self._store.root).as_posix()

    async def read(self, artifact_ref: str) -> bytes:
        target = self._store.path(*PurePosixPath(artifact_ref).parts)
        try:
            return await asyncio.to_thread(target.read_bytes)
        except OSError as error:
            raise MediaAssetError(
                "Media asset artifact is unavailable",
                status_code=404,
                code="asset_artifact_missing",
            ) from error

    def path(self, artifact_ref: str) -> Path | None:
        return self._store.path(*PurePosixPath(artifact_ref).parts)


class ObjectStorageMediaAssetArtifacts:
    """Production Media Asset adapter using the artifact catalog and object storage."""

    def __init__(
        self,
        service: ArtifactService,
        catalog: PostgresArtifactCatalog,
        storage: ObjectStorage,
    ) -> None:
        self._service = service
        self._catalog = catalog
        self._storage = storage

    async def write_file(
        self,
        asset_id: str,
        name: str,
        source: Path,
        *,
        content_type: str,
        generated: bool,
    ) -> str:
        del content_type
        record = await self._service.publish_file(
            source,
            f"media-lab/assets/{asset_id}/{name}",
            kind=ArtifactKind.GENERATED if generated else ArtifactKind.SOURCE,
            owner_type="media_asset",
            owner_id=asset_id,
        )
        return record.artifact_id

    async def read(self, artifact_ref: str) -> bytes:
        record = await self._catalog.get(artifact_ref)
        if record is None or record.status != ArtifactStatus.AVAILABLE:
            raise MediaAssetError(
                "Media asset artifact is unavailable",
                status_code=404,
                code="asset_artifact_missing",
            )
        try:
            return await asyncio.to_thread(_read_object, self._storage, record.object_key)
        except ObjectStorageError as error:
            raise MediaAssetError(
                "Media asset artifact is unavailable",
                status_code=404,
                code="asset_artifact_missing",
            ) from error

    def path(self, artifact_ref: str) -> Path | None:
        del artifact_ref
        return None


def _read_object(storage: ObjectStorage, object_key: str) -> bytes:
    with storage.open(object_key) as download:
        return b"".join(iter_download(download))


__all__ = ["FilesystemMediaAssetArtifacts", "ObjectStorageMediaAssetArtifacts"]
