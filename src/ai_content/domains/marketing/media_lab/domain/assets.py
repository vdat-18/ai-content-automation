"""Domain records for reusable Media Lab source and output assets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MediaAssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class MediaAssetOrigin(StrEnum):
    UPLOAD = "upload"
    MEDIA_LAB_IMAGE_OUTPUT = "media_lab_image_output"
    MEDIA_LAB_VIDEO_OUTPUT = "media_lab_video_output"


class MediaAssetState(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class MediaAssetLimits:
    """Technical ingestion limits for untrusted media at the API boundary."""

    max_image_bytes: int = 100_000_000
    max_video_bytes: int = 1_000_000_000
    max_image_pixels: int = 100_000_000
    max_video_duration_seconds: int = 600
    max_working_image_pixels: int = 16_777_216
    max_preview_image_pixels: int = 2_073_600
    processing_timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if any(
            value <= 0
            for value in (
                self.max_image_bytes,
                self.max_video_bytes,
                self.max_image_pixels,
                self.max_video_duration_seconds,
                self.max_working_image_pixels,
                self.max_preview_image_pixels,
                self.processing_timeout_seconds,
            )
        ):
            raise ValueError("Media asset limits must be positive")
        if self.max_preview_image_pixels > self.max_working_image_pixels:
            raise ValueError("Preview pixel limit cannot exceed working pixel limit")


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    media_kind: MediaAssetKind
    state: MediaAssetState
    origin: MediaAssetOrigin
    original_artifact_ref: str | None
    working_artifact_ref: str | None
    preview_artifact_ref: str | None
    checksum_sha256: str
    detected_content_type: str | None
    working_content_type: str | None
    preview_content_type: str | None
    size_bytes: int
    width: int | None
    height: int | None
    duration_milliseconds: int | None
    codec: str | None
    parent_asset_ids: tuple[str, ...]
    source_run_id: str | None
    preprocessing_version: str
    transform_metadata: tuple[tuple[str, str], ...]
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None


__all__ = [
    "MediaAsset",
    "MediaAssetKind",
    "MediaAssetLimits",
    "MediaAssetOrigin",
    "MediaAssetState",
]
