"""Read-only Marketing source status, sync and Creative context APIs."""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from ai_content.domains.marketing.data_sources.application.compile_performance import (
    CreativePerformanceCandidate,
    ProductPerformanceCandidate,
)
from ai_content.domains.marketing.data_sources.bootstrap import DataSourceRuntime
from ai_content.domains.marketing.data_sources.commands import (
    enqueue_data_source_sync,
    is_active_data_source_sync,
    sync_command_sources,
)
from ai_content.domains.marketing.data_sources.domain.models import (
    ProductCatalogRecord,
    SyncStatus,
)
from ai_content.platform.execution import (
    CommandScheduler,
    CommandStatusStore,
    ExecutionCommand,
    resolve_queue_call,
)

from .dependencies import (
    get_command_scheduler,
    get_command_status_store,
    get_data_source_runtime,
    get_runtime_settings,
)
from .schemas.data_sources import (
    CreativePerformanceCandidateResponse,
    CreativeSourceContextResponse,
    DataSourceListResponse,
    DataSourceStatusResponse,
    DataSourceSyncAcceptedResponse,
    ProductFamilyCandidateResponse,
    ProductFamilyCatalogResponse,
    ProductFamilyMediaResponse,
    ProductFamilyVariantResponse,
    ProductPerformanceCandidateResponse,
    SourcePerformanceCandidatesResponse,
)

router = APIRouter(prefix="/api/v1/data-sources", tags=["data-sources"])

_PROVIDER_TOKEN_EXPIRY: dict[str, str] = {
    "meta_ads": "meta_token_expires_at",
    "google_ads": "google_ads_token_expires_at",
    "shopify": "shopify_token_expires_at",
}


async def _active_sync_commands(
    queue: CommandStatusStore,
) -> dict[str, ExecutionCommand]:
    commands = await resolve_queue_call(queue.list())
    active: dict[str, ExecutionCommand] = {}
    for command in commands:
        if not is_active_data_source_sync(command):
            continue
        for source_id in sync_command_sources(command):
            active.setdefault(source_id, command)
    return active


async def _status(
    runtime: DataSourceRuntime,
    source_id: str,
    sync_command: ExecutionCommand | None = None,
) -> DataSourceStatusResponse:
    definition = runtime.service.definitions[source_id]
    run = await runtime.repository.latest_run(source_id)
    snapshot = await runtime.repository.latest_snapshot_summary(source_id)
    expiry_field = _PROVIDER_TOKEN_EXPIRY.get(definition.provider.value)
    credential_expires_at = getattr(get_runtime_settings(), expiry_field) if expiry_field else None
    return DataSourceStatusResponse(
        source_id=source_id,
        provider=definition.provider.value,
        name=definition.name,
        category=definition.category,
        purpose=definition.purpose,
        status="not_synced"
        if run is None
        else "healthy"
        if run.status == SyncStatus.SUCCEEDED
        else "error",
        last_sync_at=run.completed_at if run is not None else None,
        record_count=snapshot.record_count if snapshot is not None else 0,
        changed=run.changed if run is not None else None,
        snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
        artifact_ref=snapshot.artifact_ref if snapshot is not None else None,
        error_code=run.error_code if run is not None else None,
        error_message=run.error_message if run is not None else None,
        credential_expires_at=credential_expires_at,
        sync_command_id=sync_command.command_id if sync_command is not None else None,
        sync_status=sync_command.status.value if sync_command is not None else None,
    )


@router.get("", response_model=DataSourceListResponse)
async def list_data_sources(
    runtime: DataSourceRuntime = Depends(get_data_source_runtime),
    queue: CommandStatusStore = Depends(get_command_status_store),
) -> DataSourceListResponse:
    active = await _active_sync_commands(queue)
    items = [
        await _status(runtime, source_id, active.get(source_id))
        for source_id in runtime.service.definitions
    ]
    return DataSourceListResponse(items=items, total=len(items))


async def _enqueue_sync(
    source_ids: tuple[str, ...],
    queue: CommandScheduler,
) -> DataSourceSyncAcceptedResponse:
    command, created = await enqueue_data_source_sync(queue, source_ids)
    return DataSourceSyncAcceptedResponse(
        command_id=command.command_id,
        source_ids=list(sync_command_sources(command)),
        status=command.status.value,
        created=created,
    )


@router.post("/sync-all", response_model=DataSourceSyncAcceptedResponse, status_code=202)
async def sync_all_data_sources(
    runtime: DataSourceRuntime = Depends(get_data_source_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> DataSourceSyncAcceptedResponse:
    return await _enqueue_sync(tuple(runtime.service.definitions), queue)


@router.post(
    "/{source_id}/sync",
    response_model=DataSourceSyncAcceptedResponse,
    status_code=202,
)
async def sync_data_source(
    source_id: str,
    runtime: DataSourceRuntime = Depends(get_data_source_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> DataSourceSyncAcceptedResponse:
    if source_id not in runtime.service.definitions:
        raise HTTPException(status_code=404, detail="Data source is not configured")
    return await _enqueue_sync((source_id,), queue)


@router.get("/product-families", response_model=ProductFamilyCatalogResponse)
async def list_product_families(
    limit: int = Query(default=100, gt=0, le=500),
    brand: str | None = Query(default=None, min_length=1),
    query: str | None = Query(default=None, min_length=1),
    runtime: DataSourceRuntime = Depends(get_data_source_runtime),
) -> ProductFamilyCatalogResponse:
    source_brands = {
        source_id: str(definition.metadata.get("brand") or "")
        for source_id, definition in runtime.service.definitions.items()
        if definition.provider.value == "shopify"
        and (brand is None or str(definition.metadata.get("brand") or "") == brand)
    }
    page = await runtime.repository.list_product_catalog(
        source_brands=source_brands,
        query=query,
        limit=limit,
    )
    return ProductFamilyCatalogResponse(
        items=[
            _product_family_response(record, source_brands[record.source_id])
            for record in page.records
        ],
        total=page.total,
    )


def _product_family_response(
    record: ProductCatalogRecord,
    source_brand: str,
) -> ProductFamilyCandidateResponse:
    data = record.data
    family_key = str(data.get("family_key") or data.get("sku") or data.get("handle") or "")
    title = str(data.get("title") or family_key)
    handle = str(data.get("handle") or record.provider_id)
    currency = str(data.get("currency") or "USD")
    variants_data = [item for item in data.get("variants", ()) if isinstance(item, dict)]
    variants = [
        ProductFamilyVariantResponse(
            variant_id=str(item.get("id") or ""),
            sku=str(item["sku"]) if item.get("sku") else None,
            title=str(item.get("title") or item.get("sku") or "Variant"),
            selected_options={
                str(option.get("name") or "Option"): str(option.get("value") or "")
                for option in item.get("selected_options", ())
                if isinstance(option, dict)
            },
            price=str(item["price"]) if item.get("price") is not None else None,
            currency=currency,
            media_ids=[str(value) for value in item.get("media_ids", ()) if value],
        )
        for item in variants_data
        if item.get("id")
    ]
    media = [item for item in data.get("media", ()) if isinstance(item, dict)]
    media_responses = [
        ProductFamilyMediaResponse(
            media_id=str(item.get("id") or ""),
            url=str(item.get("url") or item.get("src") or ""),
            position=int(item.get("position") or index),
            variant_ids=[str(value) for value in item.get("variant_ids", ()) if value],
            alt=str(item["alt"]) if item.get("alt") else None,
            width=int(item["width"]) if item.get("width") is not None else None,
            height=int(item["height"]) if item.get("height") is not None else None,
        )
        for index, item in enumerate(media, 1)
        if item.get("id") and (item.get("url") or item.get("src"))
    ]
    return ProductFamilyCandidateResponse(
        source_id=record.source_id,
        snapshot_id=record.snapshot_id,
        brand=str(data.get("brand") or source_brand),
        product_id=str(data.get("product_id") or record.provider_id),
        family_key=family_key,
        handle=handle,
        title=title,
        status=str(data["status"]) if data.get("status") else None,
        published_at=str(data["published_at"]) if data.get("published_at") else None,
        image_url=str(media[0].get("url")) if media and media[0].get("url") else None,
        variant_count=len(variants),
        variants=variants,
        media=media_responses,
    )


@router.get("/performance-candidates", response_model=SourcePerformanceCandidatesResponse)
async def list_source_performance_candidates(
    limit: int = Query(default=20, gt=0, le=100),
    brand: str | None = Query(default=None, min_length=1),
    runtime: DataSourceRuntime = Depends(get_data_source_runtime),
) -> SourcePerformanceCandidatesResponse:
    """Return current provider evidence without creating a Performance decision."""
    snapshots = await runtime.repository.list_latest_snapshots()
    report = await asyncio.to_thread(
        runtime.performance_compiler.compile, snapshots, runtime.definitions
    )
    brands = sorted(
        {item.brand for item in (*report.products, *report.creatives) if item.brand is not None}
    )
    products = tuple(item for item in report.products if brand is None or item.brand == brand)
    creatives = tuple(item for item in report.creatives if brand is None or item.brand == brand)
    return SourcePerformanceCandidatesResponse(
        brands=brands,
        product_total=len(products),
        mapped_sku_total=sum(item.sku_id is not None for item in products),
        creative_total=len(creatives),
        unlinked_creative_total=sum(
            item.creative_lineage_status == "unlinked" for item in creatives
        ),
        products=[_product_candidate_response(item) for item in products[:limit]],
        creatives=[_creative_candidate_response(item) for item in creatives[:limit]],
    )


@router.get("/creative-context", response_model=CreativeSourceContextResponse)
async def compile_creative_context(
    brand: str = Query(min_length=1),
    sku_id: str = Query(min_length=1),
    market: str = Query(default="US", min_length=1),
    width: int = Query(default=1080, gt=0, le=8192),
    height: int = Query(default=1080, gt=0, le=8192),
    runtime: DataSourceRuntime = Depends(get_data_source_runtime),
) -> CreativeSourceContextResponse:
    try:
        sku, context = runtime.compiler.compile(
            await runtime.repository.list_snapshots(),
            brand=brand,
            sku_id=sku_id,
            market=market,
            width=width,
            height=height,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CreativeSourceContextResponse(sku=asdict(sku), context=asdict(context))


def _decimal_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _product_candidate_response(
    item: ProductPerformanceCandidate,
) -> ProductPerformanceCandidateResponse:
    payload = asdict(item)
    for field in (
        "impressions",
        "clicks",
        "spend",
        "conversions",
        "conversion_value",
        "roas",
    ):
        payload[field] = _decimal_text(payload[field])
    return ProductPerformanceCandidateResponse(**payload)


def _creative_candidate_response(
    item: CreativePerformanceCandidate,
) -> CreativePerformanceCandidateResponse:
    payload = asdict(item)
    for field in (
        "impressions",
        "clicks",
        "spend",
        "purchases",
        "add_to_cart",
        "purchase_conversion_value",
        "roas",
        "cost_per_atc",
    ):
        payload[field] = _decimal_text(payload[field])
    return CreativePerformanceCandidateResponse(**payload)


__all__ = ["router"]
