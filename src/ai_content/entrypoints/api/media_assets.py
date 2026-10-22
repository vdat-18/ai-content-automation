"""Multipart ingestion and retrieval for reusable Media Lab assets."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from ai_content.domains.marketing.media_lab.application.assets import MediaAssetService
from ai_content.domains.marketing.media_lab.domain.assets import (
    MediaAsset,
    MediaAssetKind,
)
from ai_content.domains.marketing.media_lab.ports.assets import MediaAssetError

from .dependencies import get_runtime_settings

router = APIRouter(prefix="/api/v1/media-assets", tags=["media-assets"])
_UPLOAD_CHUNK_BYTES = 1024 * 1024


class MediaAssetResponse(BaseModel):
    asset_id: str
    media_kind: MediaAssetKind
    state: str
    origin: str
    checksum_sha256: str
    size_bytes: int
    detected_content_type: str | None
    working_content_type: str | None
    preview_content_type: str | None
    width: int | None
    height: int | None
    duration_milliseconds: int | None
    codec: str | None
    source_run_id: str | None
    parent_asset_ids: list[str]
    preprocessing_version: str
    transform_metadata: dict[str, str]
    error_code: str | None
    preview_url: str
    original_url: str


def get_media_asset_service(request: Request) -> MediaAssetService:
    service = getattr(request.app.state, "media_asset_service", None)
    if not isinstance(service, MediaAssetService):
        raise HTTPException(status_code=503, detail="Media asset storage is unavailable")
    return service


@router.post("", response_model=MediaAssetResponse, status_code=201)
async def upload_media_asset(
    media_kind: Annotated[MediaAssetKind, Form()],
    upload: Annotated[UploadFile, File()],
    service: MediaAssetService = Depends(get_media_asset_service),
) -> MediaAssetResponse:
    maximum_bytes = service.maximum_bytes(media_kind)
    settings = get_runtime_settings()
    settings.artifacts_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="media-upload-",
        suffix=".upload",
        dir=settings.artifacts_root,
    )
    temporary_path = Path(temporary_name)
    total_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > maximum_bytes:
                    raise MediaAssetError(
                        "Media upload exceeds the configured byte limit",
                        status_code=413,
                        code="media_too_large",
                    )
                destination.write(chunk)
        asset = await service.ingest_file(temporary_path, media_kind=media_kind)
    except MediaAssetError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    finally:
        await upload.close()
        temporary_path.unlink(missing_ok=True)
    return _response(asset)


@router.get("/{asset_id}", response_model=MediaAssetResponse)
async def get_media_asset(
    asset_id: str,
    service: MediaAssetService = Depends(get_media_asset_service),
) -> MediaAssetResponse:
    try:
        return _response(await service.get(asset_id))
    except MediaAssetError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/{asset_id}/preview", response_model=None)
async def get_media_asset_preview(
    asset_id: str,
    request: Request,
    service: MediaAssetService = Depends(get_media_asset_service),
) -> FileResponse | RedirectResponse:
    return await _content_response(asset_id, "preview", request, service)


@router.get("/{asset_id}/original", response_model=None)
async def get_media_asset_original(
    asset_id: str,
    request: Request,
    service: MediaAssetService = Depends(get_media_asset_service),
) -> FileResponse | RedirectResponse:
    return await _content_response(asset_id, "original", request, service)


async def _content_response(
    asset_id: str,
    representation: str,
    request: Request,
    service: MediaAssetService,
) -> FileResponse | RedirectResponse:
    try:
        asset, path, content_type = await service.content_path(
            asset_id,
            representation=representation,
        )
    except MediaAssetError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if path is not None:
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Media asset artifact is unavailable")
        return FileResponse(path, media_type=content_type)
    container = getattr(request.app.state, "postgres_runtime", None)
    if container is None or container.artifact_service is None:
        raise HTTPException(status_code=503, detail="Media asset object storage is unavailable")
    artifact_ref = (
        asset.preview_artifact_ref if representation == "preview" else asset.original_artifact_ref
    )
    if artifact_ref is None:
        raise HTTPException(status_code=404, detail="Media asset artifact is unavailable")
    return RedirectResponse(
        f"/api/v1/artifacts/{quote(artifact_ref, safe='')}/content",
        status_code=307,
    )


def _response(asset: MediaAsset) -> MediaAssetResponse:
    return MediaAssetResponse(
        asset_id=asset.asset_id,
        media_kind=asset.media_kind,
        state=asset.state.value,
        origin=asset.origin.value,
        checksum_sha256=asset.checksum_sha256,
        size_bytes=asset.size_bytes,
        detected_content_type=asset.detected_content_type,
        working_content_type=asset.working_content_type,
        preview_content_type=asset.preview_content_type,
        width=asset.width,
        height=asset.height,
        duration_milliseconds=asset.duration_milliseconds,
        codec=asset.codec,
        source_run_id=asset.source_run_id,
        parent_asset_ids=list(asset.parent_asset_ids),
        preprocessing_version=asset.preprocessing_version,
        transform_metadata=dict(asset.transform_metadata),
        error_code=asset.error_code,
        preview_url=f"/api/v1/media-assets/{asset.asset_id}/preview",
        original_url=f"/api/v1/media-assets/{asset.asset_id}/original",
    )


__all__ = ["MediaAssetResponse", "get_media_asset_service", "router"]
