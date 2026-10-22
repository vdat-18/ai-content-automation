"""Ports for reusable Media Lab media assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain.assets import MediaAsset, MediaAssetKind
from ..domain.models import ImageBinary


@dataclass(frozen=True)
class PreprocessedMedia:
    media_kind: MediaAssetKind
    original_extension: str
    detected_content_type: str
    working_path: Path
    working_content_type: str
    preview_path: Path
    preview_content_type: str
    width: int | None
    height: int | None
    duration_milliseconds: int | None
    codec: str | None
    transform_metadata: tuple[tuple[str, str], ...]


class IMediaPreprocessor(Protocol):
    version: str

    def prepare(
        self,
        source: Path,
        media_kind: MediaAssetKind,
        workspace: Path,
    ) -> PreprocessedMedia: ...


class MediaAssetError(RuntimeError):
    """Expected media-asset failure that is safe to return to the browser."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "invalid_media_asset",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class IMediaAssetRepository(Protocol):
    async def save(self, asset: MediaAsset) -> None: ...

    async def get(self, asset_id: str) -> MediaAsset | None: ...

    def close(self) -> None: ...


class IMediaAssetArtifacts(Protocol):
    async def write_file(
        self,
        asset_id: str,
        name: str,
        source: Path,
        *,
        content_type: str,
        generated: bool,
    ) -> str: ...

    async def read(self, artifact_ref: str) -> bytes: ...

    def path(self, artifact_ref: str) -> Path | None: ...


class IMediaAssetResolver(Protocol):
    async def get(self, asset_id: str) -> MediaAsset: ...

    async def image_binary(self, asset_id: str) -> tuple[MediaAsset, ImageBinary]: ...

    async def read_original(self, asset_id: str) -> tuple[bytes, str]: ...


class IGeneratedMediaAssetWriter(Protocol):
    async def register_generated_image(
        self,
        content: bytes,
        *,
        source_run_id: str,
        parent_asset_ids: tuple[str, ...],
    ) -> MediaAsset: ...

    async def register_generated_video(
        self,
        content: bytes,
        *,
        source_run_id: str,
        parent_asset_ids: tuple[str, ...],
    ) -> MediaAsset: ...


__all__ = [
    "IGeneratedMediaAssetWriter",
    "IMediaAssetArtifacts",
    "IMediaAssetRepository",
    "IMediaPreprocessor",
    "IMediaAssetResolver",
    "MediaAssetError",
    "PreprocessedMedia",
]
