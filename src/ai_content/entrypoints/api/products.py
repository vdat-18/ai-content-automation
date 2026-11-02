"""Collected marketplace products: browser-extension intake, queue and export."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ai_content.domains.marketing.products.service import ProductCatalogService

from .dependencies import get_product_catalog_service

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
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.details()


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
