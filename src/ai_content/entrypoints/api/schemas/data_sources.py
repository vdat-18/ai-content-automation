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
    credential_expires_at: datetime | None = None
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


class ProductPerformanceCandidateResponse(BaseModel):
    source_id: str
    snapshot_id: str
    brand: str | None
    product_item_id: str
    sku_id: str | None
    sku_mapping_status: str
    window_start: str | None
    window_end: str | None
    currency: str | None
    record_count: int
    impressions: str | None
    clicks: str | None
    spend: str | None
    conversions: str | None
    conversion_value: str | None
    roas: str | None


class CreativePerformanceCandidateResponse(BaseModel):
    source_id: str
    snapshot_id: str
    brand: str | None
    ad_id: str
    ad_name: str | None
    creative_lineage_status: str
    window_label: str
    currency: str | None
    impressions: str | None
    clicks: str | None
    spend: str | None
    purchases: str | None
    add_to_cart: str | None
    purchase_conversion_value: str | None
    roas: str | None
    cost_per_atc: str | None


class SourcePerformanceCandidatesResponse(BaseModel):
    brands: list[str]
    product_total: int
    mapped_sku_total: int
    creative_total: int
    unlinked_creative_total: int
    products: list[ProductPerformanceCandidateResponse]
    creatives: list[CreativePerformanceCandidateResponse]


__all__ = [
    "CreativePerformanceCandidateResponse",
    "CreativeSourceContextResponse",
    "DataSourceListResponse",
    "DataSourceSyncAcceptedResponse",
    "DataSourceStatusResponse",
    "ProductPerformanceCandidateResponse",
    "ProductFamilyCandidateResponse",
    "ProductFamilyCatalogResponse",
    "ProductFamilyMediaResponse",
    "ProductFamilyVariantResponse",
    "SourcePerformanceCandidatesResponse",
]
