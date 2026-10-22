"""Reusable Media Lab asset ingestion, normalization and retrieval."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ai_content.platform.artifacts.object_storage import sha256_file

from ..domain.assets import (
    MediaAsset,
    MediaAssetKind,
    MediaAssetLimits,
    MediaAssetOrigin,
    MediaAssetState,
)
from ..domain.models import ImageBinary
from ..ports.assets import (
    IMediaAssetArtifacts,
    IMediaAssetRepository,
    IMediaPreprocessor,
    MediaAssetError,
)


class MediaAssetService:
    """Persist immutable originals with normalized working and preview derivatives."""

    def __init__(
        self,
        repository: IMediaAssetRepository,
        artifacts: IMediaAssetArtifacts,
        limits: MediaAssetLimits,
        preprocessor: IMediaPreprocessor,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._limits = limits
        self._preprocessor = preprocessor

    def close(self) -> None:
        self._repository.close()

    def maximum_bytes(self, media_kind: MediaAssetKind) -> int:
        return (
            self._limits.max_image_bytes
            if media_kind == MediaAssetKind.IMAGE
            else self._limits.max_video_bytes
        )

    async def ingest_file(
        self,
        source: Path,
        *,
        media_kind: MediaAssetKind,
        origin: MediaAssetOrigin = MediaAssetOrigin.UPLOAD,
        source_run_id: str | None = None,
        parent_asset_ids: tuple[str, ...] = (),
    ) -> MediaAsset:
        if not source.is_file():
            raise MediaAssetError("Media upload is unavailable", code="upload_missing")
        checksum, size_bytes = await asyncio.to_thread(sha256_file, source)
        _validate_size(media_kind, size_bytes, self._limits)
        now = datetime.now(UTC)
        processing = MediaAsset(
            asset_id=uuid4().hex,
            media_kind=media_kind,
            state=MediaAssetState.PROCESSING,
            origin=origin,
            original_artifact_ref=None,
            working_artifact_ref=None,
            preview_artifact_ref=None,
            checksum_sha256=checksum,
            detected_content_type=None,
            working_content_type=None,
            preview_content_type=None,
            size_bytes=size_bytes,
            width=None,
            height=None,
            duration_milliseconds=None,
            codec=None,
            parent_asset_ids=tuple(dict.fromkeys(parent_asset_ids)),
            source_run_id=source_run_id,
            preprocessing_version=self._preprocessor.version,
            transform_metadata=(),
            created_at=now,
            updated_at=now,
        )
        await self._repository.save(processing)
        try:
            with tempfile.TemporaryDirectory(prefix="media-asset-") as temporary_directory:
                result = await asyncio.to_thread(
                    self._preprocessor.prepare,
                    source,
                    media_kind,
                    Path(temporary_directory),
                )
                original_ref = await self._artifacts.write_file(
                    processing.asset_id,
                    f"original{result.original_extension}",
                    source,
                    content_type=result.detected_content_type,
                    generated=origin != MediaAssetOrigin.UPLOAD,
                )
                working_ref = await self._artifacts.write_file(
                    processing.asset_id,
                    result.working_path.name,
                    result.working_path,
                    content_type=result.working_content_type,
                    generated=origin != MediaAssetOrigin.UPLOAD,
                )
                preview_ref = await self._artifacts.write_file(
                    processing.asset_id,
                    result.preview_path.name,
                    result.preview_path,
                    content_type=result.preview_content_type,
                    generated=origin != MediaAssetOrigin.UPLOAD,
                )
        except MediaAssetError as error:
            failed = replace(
                processing,
                state=MediaAssetState.FAILED,
                updated_at=datetime.now(UTC),
                error_code=error.code,
            )
            await self._repository.save(failed)
            raise
        ready = MediaAsset(
            asset_id=processing.asset_id,
            media_kind=result.media_kind,
            state=MediaAssetState.READY,
            origin=origin,
            original_artifact_ref=original_ref,
            working_artifact_ref=working_ref,
            preview_artifact_ref=preview_ref,
            checksum_sha256=checksum,
            detected_content_type=result.detected_content_type,
            working_content_type=result.working_content_type,
            preview_content_type=result.preview_content_type,
            size_bytes=size_bytes,
            width=result.width,
            height=result.height,
            duration_milliseconds=result.duration_milliseconds,
            codec=result.codec,
            parent_asset_ids=processing.parent_asset_ids,
            source_run_id=source_run_id,
            preprocessing_version=self._preprocessor.version,
            transform_metadata=result.transform_metadata,
            created_at=processing.created_at,
            updated_at=datetime.now(UTC),
        )
        await self._repository.save(ready)
        return ready

    async def register_generated_image(
        self,
        content: bytes,
        *,
        source_run_id: str,
        parent_asset_ids: tuple[str, ...],
    ) -> MediaAsset:
        return await self._ingest_generated_bytes(
            content,
            media_kind=MediaAssetKind.IMAGE,
            origin=MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT,
            source_run_id=source_run_id,
            parent_asset_ids=parent_asset_ids,
        )

    async def register_generated_video(
        self,
        content: bytes,
        *,
        source_run_id: str,
        parent_asset_ids: tuple[str, ...],
    ) -> MediaAsset:
        return await self._ingest_generated_bytes(
            content,
            media_kind=MediaAssetKind.VIDEO,
            origin=MediaAssetOrigin.MEDIA_LAB_VIDEO_OUTPUT,
            source_run_id=source_run_id,
            parent_asset_ids=parent_asset_ids,
        )

    async def get(self, asset_id: str) -> MediaAsset:
        asset = await self._repository.get(asset_id)
        if asset is None:
            raise MediaAssetError(
                "Media asset was not found", status_code=404, code="asset_not_found"
            )
        if asset.state != MediaAssetState.READY:
            raise MediaAssetError(
                "Media asset is not ready", status_code=409, code="asset_not_ready"
            )
        return asset

    async def image_binary(self, asset_id: str) -> tuple[MediaAsset, ImageBinary]:
        asset = await self.get(asset_id)
        if asset.media_kind != MediaAssetKind.IMAGE or asset.working_artifact_ref is None:
            raise MediaAssetError("Media asset is not an image", code="invalid_image_asset")
        if asset.working_content_type not in {"image/jpeg", "image/png"}:
            raise MediaAssetError(
                "Media asset working image is invalid", code="invalid_image_asset"
            )
        content = await self._artifacts.read(asset.working_artifact_ref)
        extension = ".png" if asset.working_content_type == "image/png" else ".jpg"
        return asset, ImageBinary(content, extension, asset.working_content_type)

    async def read_original(self, asset_id: str) -> tuple[bytes, str]:
        asset = await self.get(asset_id)
        if asset.original_artifact_ref is None or asset.detected_content_type is None:
            raise MediaAssetError(
                "Media asset original is unavailable", code="asset_artifact_missing"
            )
        return await self._artifacts.read(asset.original_artifact_ref), asset.detected_content_type

    async def read_preview(self, asset_id: str) -> tuple[bytes, str]:
        asset = await self.get(asset_id)
        if asset.preview_artifact_ref is None or asset.preview_content_type is None:
            raise MediaAssetError(
                "Media asset preview is unavailable", code="asset_artifact_missing"
            )
        return await self._artifacts.read(asset.preview_artifact_ref), asset.preview_content_type

    async def content_path(
        self,
        asset_id: str,
        *,
        representation: str,
    ) -> tuple[MediaAsset, Path | None, str]:
        asset = await self.get(asset_id)
        if representation == "original":
            artifact_ref = asset.original_artifact_ref
            content_type = asset.detected_content_type
        elif representation == "preview":
            artifact_ref = asset.preview_artifact_ref
            content_type = asset.preview_content_type
        else:
            raise MediaAssetError("Media representation is invalid", code="invalid_representation")
        if artifact_ref is None or content_type is None:
            raise MediaAssetError(
                "Media asset artifact is unavailable", code="asset_artifact_missing"
            )
        return asset, self._artifacts.path(artifact_ref), content_type

    async def _ingest_generated_bytes(
        self,
        content: bytes,
        *,
        media_kind: MediaAssetKind,
        origin: MediaAssetOrigin,
        source_run_id: str,
        parent_asset_ids: tuple[str, ...],
    ) -> MediaAsset:
        suffix = ".png" if media_kind == MediaAssetKind.IMAGE else ".mp4"
        with tempfile.NamedTemporaryFile(
            prefix="media-asset-output-", suffix=suffix, delete=False
        ) as output:
            temporary_path = Path(output.name)
            output.write(content)
        try:
            return await self.ingest_file(
                temporary_path,
                media_kind=media_kind,
                origin=origin,
                source_run_id=source_run_id,
                parent_asset_ids=parent_asset_ids,
            )
        finally:
            temporary_path.unlink(missing_ok=True)


def _validate_size(media_kind: MediaAssetKind, size_bytes: int, limits: MediaAssetLimits) -> None:
    maximum = (
        limits.max_image_bytes if media_kind == MediaAssetKind.IMAGE else limits.max_video_bytes
    )
    if size_bytes > maximum:
        label = "Image" if media_kind == MediaAssetKind.IMAGE else "Video"
        raise MediaAssetError(
            f"{label} upload exceeds the configured byte limit",
            status_code=413,
            code="media_too_large",
        )


__all__ = ["MediaAssetService"]
