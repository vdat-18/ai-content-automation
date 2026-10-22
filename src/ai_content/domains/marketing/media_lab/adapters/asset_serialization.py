"""Serialization for persisted Media Lab assets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.assets import MediaAsset, MediaAssetKind, MediaAssetOrigin, MediaAssetState


def asset_to_dict(asset: MediaAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "media_kind": asset.media_kind.value,
        "state": asset.state.value,
        "origin": asset.origin.value,
        "original_artifact_ref": asset.original_artifact_ref,
        "working_artifact_ref": asset.working_artifact_ref,
        "preview_artifact_ref": asset.preview_artifact_ref,
        "checksum_sha256": asset.checksum_sha256,
        "detected_content_type": asset.detected_content_type,
        "working_content_type": asset.working_content_type,
        "preview_content_type": asset.preview_content_type,
        "size_bytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "duration_milliseconds": asset.duration_milliseconds,
        "codec": asset.codec,
        "parent_asset_ids": list(asset.parent_asset_ids),
        "source_run_id": asset.source_run_id,
        "preprocessing_version": asset.preprocessing_version,
        "transform_metadata": list(asset.transform_metadata),
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
        "error_code": asset.error_code,
    }


def asset_from_dict(payload: dict[str, Any]) -> MediaAsset:
    metadata = payload.get("transform_metadata", [])
    if not isinstance(metadata, list):
        raise ValueError("Media asset transform metadata is invalid")
    try:
        transform_metadata = tuple((str(key), str(value)) for key, value in metadata)
    except (TypeError, ValueError) as error:
        raise ValueError("Media asset transform metadata is invalid") from error
    return MediaAsset(
        asset_id=payload["asset_id"],
        media_kind=MediaAssetKind(payload["media_kind"]),
        state=MediaAssetState(payload["state"]),
        origin=MediaAssetOrigin(payload["origin"]),
        original_artifact_ref=payload.get("original_artifact_ref"),
        working_artifact_ref=payload.get("working_artifact_ref"),
        preview_artifact_ref=payload.get("preview_artifact_ref"),
        checksum_sha256=payload["checksum_sha256"],
        detected_content_type=payload.get("detected_content_type"),
        working_content_type=payload.get("working_content_type"),
        preview_content_type=payload.get("preview_content_type"),
        size_bytes=payload["size_bytes"],
        width=payload.get("width"),
        height=payload.get("height"),
        duration_milliseconds=payload.get("duration_milliseconds"),
        codec=payload.get("codec"),
        parent_asset_ids=tuple(payload.get("parent_asset_ids", [])),
        source_run_id=payload.get("source_run_id"),
        preprocessing_version=payload["preprocessing_version"],
        transform_metadata=transform_metadata,
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        error_code=payload.get("error_code"),
    )


__all__ = ["asset_from_dict", "asset_to_dict"]
