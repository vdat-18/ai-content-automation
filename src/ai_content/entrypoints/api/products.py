"""Collected marketplace products: browser-extension intake, queue and export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ai_content.domains.marketing.products.briefing import BriefGenerationError, BriefUnavailable
from ai_content.domains.marketing.products.clips import StitchUnavailable
from ai_content.domains.marketing.products.references import (
    ProfileGenerationError,
    ReferenceProfile,
)
from ai_content.domains.marketing.products.service import KeyframeUnavailable, ProductCatalogService

from .dependencies import get_product_catalog_service, get_runtime_settings

router = APIRouter(prefix="/api/v1/products", tags=["products"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/ingest")
async def ingest_capture(
    payload: dict[str, Any],
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    return await service.ingest(payload)


@router.get("/queue")
async def capture_queue(
    limit: int = Query(20, ge=1, le=200),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[str]:
    return await service.queue(limit)


@router.get("")
async def list_products(
    include_junk: bool = False,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.details(include_junk)


@router.post("/media/download")
async def download_media(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    """Save images and videos of captured products under <data root>/media."""
    root = get_runtime_settings().db_path.parent / "media"
    return (await service.download_media(root)).as_dict()


class ProfileUpdate(BaseModel):
    keywords: list[str]
    status: str = "draft"


@router.get("/selections")
async def list_selections(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str | None]:
    return await service.selections()


@router.get("/reference-profiles")
async def list_reference_profiles(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return [profile.as_dict() for profile in await service.profiles()]


@router.put("/reference-profiles/{product_type}")
async def update_reference_profile(
    product_type: str,
    body: ProfileUpdate,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    profile = ReferenceProfile(product_type, body.keywords, body.status)
    if not await service.update_profile(profile):
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile.as_dict()


@router.get("/reference-queue")
async def reference_queue(
    limit: int = Query(20, ge=1, le=200),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, str]]:
    return await service.reference_queue(limit)


@router.get("/reference-images")
async def list_reference_images(
    status: str | None = None,
    product_type: str | None = None,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.reference_images(status, product_type)


@router.post("/reference-images/screen")
async def screen_reference_images(
    limit: int = Query(30, ge=1, le=200),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    try:
        return await service.screen_images(limit)
    except ProfileGenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/reference-images/backfill-fingerprints")
async def backfill_fingerprints(
    limit: int = Query(500, ge=1, le=2000),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    """Embed images stored before duplicate detection existed (also warms the model)."""
    try:
        return {"fingerprinted": await service.backfill_fingerprints(limit)}
    except ProfileGenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.delete("/reference-images/{image_id}")
async def remove_reference_image(
    image_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    """Remove an image from the corpus; it stays recorded so a crawl never adds it back."""
    if not await service.set_image_status(image_id, "removed"):
        raise HTTPException(status_code=404, detail="Reference image not found")
    return {"image_id": image_id, "status": "removed"}


class BriefRequest(BaseModel):
    idea: str = ""
    video_seconds: Literal[15, 30, 45, 60] = 15


class BriefUpdate(BaseModel):
    brief: dict[str, Any]
    status: Literal["draft", "approved"] = "draft"


@router.get("/briefs")
async def list_briefs(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.list_briefs()


@router.post("/{product_id}/brief")
async def create_brief(
    product_id: str,
    body: BriefRequest,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    try:
        record = await service.create_brief(product_id, body.idea, body.video_seconds)
    except BriefUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (BriefGenerationError, ProfileGenerationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="Product not captured")
    return record


@router.get("/{product_id}/brief")
async def get_brief(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    record = await service.get_brief(product_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return record


@router.put("/{product_id}/brief")
async def update_brief(
    product_id: str,
    body: BriefUpdate,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    record = await service.update_brief(product_id, body.brief, body.status)
    if record is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return record


@router.post("/{product_id}/select")
async def select_product(
    product_id: str,
    regenerate: bool = False,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    result = await service.select(product_id, regenerate)
    if result is None:
        raise HTTPException(status_code=404, detail="Product not captured")
    return result


@router.get("/export")
async def export_products(
    format: str = Query("json", pattern="^(json|xlsx)$"),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> Response:
    if format == "xlsx":
        return Response(
            await service.export_workbook(),
            media_type=XLSX,
            headers={"Content-Disposition": 'attachment; filename="products.xlsx"'},
        )
    return Response(
        _json(await service.details()),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="products.json"'},
    )


@router.get("/{product_id}")
async def get_product(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    detail = await service.detail(product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Product not captured")
    return detail


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class KeyframeRequest(BaseModel):
    shot_index: int | None = None


class KeyframeReview(BaseModel):
    status: str


def _media_root() -> Path:
    return get_runtime_settings().db_path.parent / "media"


@router.get("/{product_id}/keyframes")
async def list_keyframes(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.list_keyframes(product_id)


@router.post("/{product_id}/keyframes")
async def generate_keyframes(
    product_id: str,
    body: KeyframeRequest,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """Run the next keyframe step; the master must be approved before the other shots."""
    try:
        keyframes = await service.generate_keyframes(product_id, _media_root(), body.shot_index)
    except KeyframeUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if keyframes is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return keyframes


@router.put("/{product_id}/keyframes/{shot_index}")
async def review_keyframe(
    product_id: str,
    shot_index: int,
    body: KeyframeReview,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    try:
        found = await service.set_keyframe_status(product_id, shot_index, body.status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not found:
        raise HTTPException(status_code=404, detail="No such keyframe")
    return {"status": body.status}


@router.get("/{product_id}/keyframes/{shot_index}/image")
async def keyframe_image(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    for keyframe in await service.list_keyframes(product_id):
        if keyframe["shot_index"] == shot_index and keyframe["image_path"]:
            path = _media_root() / keyframe["image_path"]
            if path.is_file():
                return FileResponse(path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="No image for this keyframe")


class ClipRequest(BaseModel):
    shot_index: int | None = None


@router.get("/{product_id}/clips")
async def list_clips(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.clips(product_id, _media_root())


@router.post("/{product_id}/clips")
async def generate_clips(
    product_id: str,
    body: ClipRequest,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """Start video jobs for approved keyframes; poll GET clips until they are ready."""
    try:
        clips = await service.generate_clips(product_id, _media_root(), body.shot_index)
    except KeyframeUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if clips is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return clips


@router.get("/{product_id}/clips/{shot_index}/video")
async def clip_video(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    for clip in await service.clips(product_id, _media_root()):
        if clip["shot_index"] == shot_index and clip["video_path"]:
            path = _media_root() / clip["video_path"]
            if path.is_file():
                return FileResponse(path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="No video for this clip")


@router.post("/{product_id}/video")
async def build_video(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    """Stitch the ready clips into one video."""
    try:
        path = await service.build_video(product_id, _media_root())
    except StitchUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if path is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return {"video": f"/api/v1/products/{product_id}/video"}


@router.get("/{product_id}/video")
async def final_video(product_id: str) -> FileResponse:
    path = _media_root() / "videos" / product_id / "video.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No stitched video yet")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})
