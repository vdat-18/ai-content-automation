"""Collected marketplace products: browser-extension intake, queue and export."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from ai_content.domains.marketing.products.briefing import BriefGenerationError, BriefUnavailable
from ai_content.domains.marketing.products.references import (
    ProfileGenerationError,
    ReferenceProfile,
)
from ai_content.domains.marketing.products.service import ProductCatalogService

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
        record = await service.create_brief(product_id, body.idea)
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
