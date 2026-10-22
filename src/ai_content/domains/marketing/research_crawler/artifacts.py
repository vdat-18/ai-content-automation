"""Raw source artifact persistence for research crawl jobs."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import PurePosixPath

from ai_content.platform.artifacts import ArtifactKind, ArtifactService, ArtifactStore


class ResearchCrawlArtifactWriter:
    def __init__(
        self,
        store: ArtifactStore,
        service: ArtifactService | None = None,
    ) -> None:
        self._store = store
        self._service = service

    async def write(self, job_id: str, content: bytes, brand_id: str) -> str:
        source_path = f"research-crawls/{job_id}/source.html"
        path = self._store.write_bytes(content, *source_path.split("/"))
        if self._service is None:
            return source_path
        record = await self._service.publish_file(
            path,
            source_path,
            kind=ArtifactKind.SOURCE,
            owner_type="research_crawl",
            owner_id=job_id,
            brand_scope=brand_id,
        )
        return record.artifact_id

    async def write_media(
        self,
        *,
        record_key: str,
        filename: str,
        content: bytes,
        brand_id: str,
    ) -> tuple[str, str]:
        source_path = f"research-media/{record_key}/{filename}"
        path = self._store.write_bytes(content, *source_path.split("/"))
        checksum = hashlib.sha256(content).hexdigest()
        if self._service is None:
            return source_path, checksum
        record = await self._service.publish_file(
            path,
            source_path,
            kind=ArtifactKind.SOURCE,
            owner_type="research_record",
            owner_id=record_key,
            brand_scope=brand_id,
        )
        return record.artifact_id, record.sha256

    async def read_media(
        self,
        artifact_ref: str,
        *,
        max_bytes: int,
    ) -> tuple[bytes, str]:
        """Read one previously captured immutable media artifact with a size bound."""
        if self._service is None:
            path = self._store.path(*PurePosixPath(artifact_ref).parts)
            if not path.is_file() or path.stat().st_size > max_bytes:
                raise ValueError("Research media artifact is unavailable or too large")
            return await asyncio.to_thread(path.read_bytes), "application/octet-stream"
        record = await self._service.catalog.get(artifact_ref)
        if record is None or record.status.value != "available" or record.size_bytes > max_bytes:
            raise ValueError("Research media artifact is unavailable or too large")

        def read_object() -> bytes:
            with self._service.storage.open(record.object_key) as download:
                return download.stream.read()

        content = await asyncio.to_thread(read_object)
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise ValueError("Research media artifact checksum does not match its catalog record")
        return content, record.content_type


__all__ = ["ResearchCrawlArtifactWriter"]
