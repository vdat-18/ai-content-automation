from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DataSourceStatusResponse(BaseModel):
    source_id: str
    provider: str
    name: str
    category: str
    purpose: str
    status: str
    last_sync_at: datetime | None
    record_count: int
    changed: bool | None
    snapshot_id: str | None
    artifact_ref: str | None
    error_code: str | None
    error_message: str | None
    sync_command_id: str | None = None
    sync_status: str | None = None


class DataSourceListResponse(BaseModel):
    items: list[DataSourceStatusResponse]
    total: int


class DataSourceSyncAcceptedResponse(BaseModel):
    command_id: str
    source_ids: list[str]
    status: str
    created: bool


class CreativeSourceContextResponse(BaseModel):
    sku: dict[str, Any]
    context: dict[str, Any]


class ProductFamilyVariantResponse(BaseModel):
    variant_id: str
    sku: str | None
    title: str
    selected_options: dict[str, str]
    price: str | None
    currency: str
    media_ids: list[str]


class ProductFamilyMediaResponse(BaseModel):
    media_id: str
    url: str
    position: int
    variant_ids: list[str]
    alt: str | None
    width: int | None
    height: int | None


class ProductFamilyCandidateResponse(BaseModel):
    source_id: str
    snapshot_id: str
    brand: str
    product_id: str
    family_key: str
    handle: str
    title: str
    status: str | None
    published_at: str | None
    image_url: str | None
    variant_count: int
    variants: list[ProductFamilyVariantResponse]
    media: list[ProductFamilyMediaResponse]


class ProductFamilyCatalogResponse(BaseModel):
    items: list[ProductFamilyCandidateResponse]
    total: int


class SourceBrandsResponse(BaseModel):
    brands: list[str]


__all__ = [
    "CreativeSourceContextResponse",
    "DataSourceListResponse",
    "DataSourceSyncAcceptedResponse",
    "DataSourceStatusResponse",
    "ProductFamilyCandidateResponse",
    "ProductFamilyCatalogResponse",
    "ProductFamilyMediaResponse",
    "ProductFamilyVariantResponse",
    "SourceBrandsResponse",
]
