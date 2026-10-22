"""Marketing-friendly entrypoint for selected-SKU Creative automation."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from loguru import logger
from opentelemetry import trace

from ai_content.domains.marketing.creative.adapters.automation_artifacts import (
    package_artifact_ref,
)
from ai_content.domains.marketing.creative.adapters.automation_commands import (
    CreativeAutomationCommandService,
    process_sku_command,
)
from ai_content.domains.marketing.creative.adapters.automation_job_repositories import (
    PostgresCreativeAutomationJobRepository,
)
from ai_content.domains.marketing.creative.adapters.automation_storage import (
    MarketingCreativeAutomationStorage,
)
from ai_content.domains.marketing.creative.adapters.baml_orchestration import (
    BamlCreativeAutomationOrchestrator,
)
from ai_content.domains.marketing.creative.adapters.baml_preparation import (
    BamlPreparationModel,
)
from ai_content.domains.marketing.creative.adapters.fake_orchestration import (
    FakeCreativeAutomationOrchestrator,
)
from ai_content.domains.marketing.creative.application.ads_activation import (
    AdsActivationService,
)
from ai_content.domains.marketing.creative.application.ads_drafts import (
    build_ads_draft,
)
from ai_content.domains.marketing.creative.application.ads_provider_registry import (
    AdsActivationProviderRegistry,
)
from ai_content.domains.marketing.creative.application.automation_production import (
    MarketingCreativeAutomationProducer,
)
from ai_content.domains.marketing.creative.application.automation_workflow import (
    activate_automation_ads,
    approve_automation_ads_draft,
    attach_ads_draft,
    decide_final_review,
    initialize_automation_state,
    record_production_outcome,
    request_generation_again,
    request_manual_takeover,
)
from ai_content.domains.marketing.creative.application.provider_registry import (
    ManagedMediaProviderRegistry,
)
from ai_content.domains.marketing.creative.application.routing import (
    decide_production_route,
)
from ai_content.domains.marketing.creative.config.orchestration import (
    load_orchestration_config,
)
from ai_content.domains.marketing.creative.config.preparation import (
    load_preparation_config,
)
from ai_content.domains.marketing.creative.ports.ads_activation import (
    AdsActivationDisabledError,
    ExactCreativeAsset,
)
from ai_content.domains.marketing.creative.ports.automation_jobs import (
    CreativeAutomationBatchSnapshot,
    CreativeAutomationEvent,
    CreativeAutomationJobIssue,
    CreativeAutomationJobSnapshot,
    ICreativeAutomationJobRepository,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    IMarketingCreativeAutomationStateRepository,
    MarketingCreativeAutomationState,
    MarketingCreativeAutomationStatus,
    ProducedCreativeAssetRecord,
    resolve_state_repository_call,
)
from ai_content.domains.marketing.creative.ports.contracts import (
    CreativeAutomationExecutionMode,
    CreativeOutputProfile,
    CreativeOutputSelection,
    CreativeReferenceAssignment,
    CreativeReferenceCandidate,
    CreativeReferenceSelectionMode,
    CreativeSetStrategy,
    MarketingCreativeAutomationRequest,
    ProductFamilyRef,
    ProductionRoute,
    ProductMediaSelectionMode,
    ProductSelectionScope,
    SkuProductionTier,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    IFrozenProductMediaResolver,
)
from ai_content.domains.marketing.creative.ports.orchestration import (
    ApprovedCreativeMemory,
    ICreativeAutomationOrchestrator,
    OrchestrationReadiness,
)
from ai_content.domains.marketing.creative.ports.preparation import SourceDocument
from ai_content.domains.marketing.creative.ports.preparation_store import (
    CreativeKnowledgeAssignment,
    ProductionReadyCreativePackage,
)
from ai_content.domains.marketing.creative_feedback.bootstrap import CreativeFeedbackRuntime
from ai_content.domains.marketing.creative_intake.bootstrap import CreativeIntakeRuntime
from ai_content.domains.marketing.creative_knowledge.models import (
    CreativeKnowledge,
    KnowledgeScope,
    KnowledgeStage,
)
from ai_content.domains.marketing.creative_knowledge.scope import (
    product_archetype,
    product_niche,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.data_sources.application.compile_automation import (
    MarketingCreativeAutomationCompiler,
    freeze_compilation_product_media,
    register_context_sources,
    resolve_missing_persona,
)
from ai_content.domains.marketing.data_sources.application.compile_context import (
    CreativeContextUnavailableError,
    CreativeSourceContextCompiler,
)
from ai_content.domains.marketing.data_sources.bootstrap import DataSourceRuntime
from ai_content.domains.marketing.data_sources.ports.interfaces import SourceReadError
from ai_content.domains.marketing.media_lab.application.assets import MediaAssetService
from ai_content.domains.marketing.media_lab.domain.assets import (
    MediaAssetKind,
    MediaAssetOrigin,
    MediaAssetState,
)
from ai_content.domains.marketing.media_lab.ports.assets import MediaAssetError
from ai_content.domains.marketing.research_crawler.models import ResearchRecordQuery
from ai_content.domains.marketing.research_crawler.repository import ResearchCrawlRepository
from ai_content.platform.ai_usage import AIUsageRepository, AIUsageTracker
from ai_content.platform.execution import (
    CeleryCommandScheduler,
    CommandScheduler,
    resolve_queue_call,
)
from ai_content.platform.llm_routing import (
    AGENT_REASONING_LEVELS,
    APPROVED_AGENT_MODELS,
    DEFAULT_AGENT_MODEL,
    DEFAULT_AGENT_REASONING_LEVEL,
    route_approved_agent_model,
)
from ai_content.platform.notifications import Notification, NotificationRepository
from ai_content.platform.observability.metrics import (
    CREATIVE_AUTOMATION_STEP_DURATION,
    CREATIVE_AUTOMATION_TOTAL_DURATION,
)

from .dependencies import (
    get_ads_activation_provider_registry,
    get_ai_usage_repository,
    get_command_scheduler,
    get_creative_automation_job_repository,
    get_creative_automation_producer,
    get_creative_automation_state_repository,
    get_creative_automation_storage,
    get_creative_feedback_runtime,
    get_creative_intake_runtime,
    get_creative_intake_write_runtime,
    get_creative_knowledge_service,
    get_data_source_runtime,
    get_managed_media_provider_registry,
    get_notification_repository,
    get_product_media_source_resolver,
    get_research_crawl_repository,
    get_runtime_settings,
)
from .media_assets import get_media_asset_service
from .schemas.creative_automation import (
    MarketingCreativeAdsActivationRequest,
    MarketingCreativeAdsActivationResponse,
    MarketingCreativeAdsApprovalRequest,
    MarketingCreativeAdsDraftCreateRequest,
    MarketingCreativeAdsDraftResponse,
    MarketingCreativeAssetResponse,
    MarketingCreativeAutomationBatchResponse,
    MarketingCreativeAutomationCapabilitiesResponse,
    MarketingCreativeAutomationCreateRequest,
    MarketingCreativeAutomationDetailResponse,
    MarketingCreativeAutomationEventResponse,
    MarketingCreativeAutomationIssueResponse,
    MarketingCreativeAutomationItemResponse,
    MarketingCreativeAutomationLatencyResponse,
    MarketingCreativeAutomationLatencyStepResponse,
    MarketingCreativeAutomationListResponse,
    MarketingCreativeAutomationPlanResponse,
    MarketingCreativeAutomationTraceResponse,
    MarketingCreativeFinalReviewResponse,
    MarketingCreativeGenerateAgainRequest,
    MarketingCreativeGenerationRequestResponse,
    MarketingCreativeImageModelCapabilityResponse,
    MarketingCreativeIntermediateArtifactResponse,
    MarketingCreativeManualTakeoverRequest,
    MarketingCreativeManualTakeoverResponse,
    MarketingCreativeMediaCapabilityResponse,
    MarketingCreativeOutputProfileResponse,
    MarketingCreativeProductionVersionResponse,
    MarketingCreativeReviewDecisionRequest,
    MarketingCreativeReviewDecisionResponse,
    MarketingCreativeVideoModelCapabilityResponse,
)

router = APIRouter(prefix="/api/v1/marketing/creative-automations")
_LATENCY_TRACER = trace.get_tracer(__name__)


@asynccontextmanager
async def measure_automation_step(
    repository: ICreativeAutomationJobRepository,
    request_id: str,
    step: str,
) -> AsyncIterator[None]:
    """Persist one bounded business-step duration without changing job state."""
    started_at = datetime.now(UTC)
    started = perf_counter()
    outcome = "succeeded"
    with _LATENCY_TRACER.start_as_current_span(
        f"aic.creative_automation.{step}",
        attributes={"creative.request_id": request_id, "creative.step": step},
    ):
        try:
            yield
        except BaseException:
            outcome = "failed"
            raise
        finally:
            completed_at = datetime.now(UTC)
            duration_seconds = max(perf_counter() - started, 0)
            try:
                await record_automation_step_latency(
                    repository,
                    request_id,
                    step=step,
                    outcome=outcome,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=duration_seconds,
                )
            except Exception:
                logger.exception(
                    "Could not persist Creative automation latency event request_id={} step={}",
                    request_id,
                    step,
                )


async def record_automation_step_latency(
    repository: ICreativeAutomationJobRepository,
    request_id: str,
    *,
    step: str,
    outcome: str,
    started_at: datetime,
    completed_at: datetime,
    duration_seconds: float | None = None,
) -> None:
    """Persist and export a measured Creative automation step."""
    elapsed = (
        max(duration_seconds, 0)
        if duration_seconds is not None
        else max((completed_at - started_at).total_seconds(), 0)
    )
    CREATIVE_AUTOMATION_STEP_DURATION.labels(step=step, outcome=outcome).observe(elapsed)
    await repository.add_event(
        CreativeAutomationEvent(
            event_id=_workflow_entity_id(
                "automation-latency", request_id, f"{step}:{started_at.isoformat()}"
            ),
            job_id=request_id,
            event_type=f"latency:{step}",
            payload={
                "step": step,
                "outcome": outcome,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": round(elapsed * 1000, 3),
            },
            created_at=completed_at,
        )
    )


async def record_automation_total_latency(
    repository: ICreativeAutomationJobRepository,
    request_id: str,
    *,
    outcome: str,
    completed_at: datetime | None = None,
) -> None:
    """Record request-created to initial pipeline-result latency."""
    job = await repository.get_job(request_id)
    if job is None:
        return
    finished_at = completed_at or datetime.now(UTC)
    duration_seconds = max((finished_at - job.created_at).total_seconds(), 0)
    CREATIVE_AUTOMATION_TOTAL_DURATION.labels(route=job.route, outcome=outcome).observe(
        duration_seconds
    )
    await repository.add_event(
        CreativeAutomationEvent(
            event_id=_workflow_entity_id(
                "automation-latency", request_id, f"total:{outcome}:{finished_at.isoformat()}"
            ),
            job_id=request_id,
            event_type="latency:total",
            payload={
                "step": "total",
                "outcome": outcome,
                "started_at": job.created_at.isoformat(),
                "completed_at": finished_at.isoformat(),
                "duration_ms": round(duration_seconds * 1000, 3),
            },
            created_at=finished_at,
        )
    )


@router.get(
    "/capabilities",
    response_model=MarketingCreativeAutomationCapabilitiesResponse,
)
async def get_marketing_creative_automation_capabilities(
    providers: ManagedMediaProviderRegistry = Depends(get_managed_media_provider_registry),
) -> MarketingCreativeAutomationCapabilitiesResponse:
    """Expose only Marketing-safe media choices supported by configured models."""

    def capability(kind: str) -> MarketingCreativeMediaCapabilityResponse:
        descriptor = (
            providers.image_descriptor() if kind == "image" else providers.video_descriptor()
        )
        image_descriptors = tuple(
            item
            for item in providers.image_descriptors()
            if item.approved and item.selected_sku_enabled
        )
        status_value = providers.image_status() if kind == "image" else providers.video_status()
        return MarketingCreativeMediaCapabilityResponse(
            status=status_value,
            provider_id=descriptor.provider_id if descriptor is not None else None,
            configuration_version=(
                descriptor.configuration_version if descriptor is not None else None
            ),
            fidelity_mode=(descriptor.fidelity_mode if descriptor is not None else None),
            supported_aspect_ratios=(
                list(descriptor.supported_aspect_ratios) if descriptor is not None else []
            ),
            supported_formats=(
                list(descriptor.supported_image_formats)
                if descriptor is not None and kind == "image"
                else (["mp4"] if descriptor is not None else [])
            ),
            max_reference_images=(
                descriptor.max_reference_images if descriptor is not None else None
            ),
            supported_generation_durations_seconds=(
                list(descriptor.supported_generation_durations_seconds)
                if descriptor is not None and kind == "video"
                else []
            ),
            supports_native_voice=(
                descriptor.supports_native_voice if descriptor is not None else False
            ),
            supports_native_music=(
                descriptor.supports_native_music if descriptor is not None else False
            ),
            max_final_duration_seconds=30 if kind == "video" else None,
            models=(
                [
                    MarketingCreativeVideoModelCapabilityResponse(
                        model_id=item.model_id,
                        display_name=item.display_name,
                        fidelity_mode=item.fidelity_mode,
                        supported_aspect_ratios=list(item.supported_aspect_ratios),
                        supported_resolutions=list(item.supported_resolutions),
                        supported_generation_durations_seconds=list(
                            item.supported_generation_durations_seconds
                        ),
                        max_reference_images=item.max_reference_images,
                        max_product_images=item.max_product_images,
                        reference_to_video_resolutions=list(
                            item.reference_to_video_resolutions
                        ),
                        supports_native_voice=item.supports_native_voice,
                        supports_native_music=item.supports_native_music,
                    )
                    for item in descriptor.video_models
                ]
                if descriptor is not None and kind == "video"
                else []
            ),
            image_models=(
                [
                    MarketingCreativeImageModelCapabilityResponse(
                        provider_id=image_descriptor.provider_id,
                        model_id=item.model_id,
                        display_name=item.display_name,
                        fidelity_mode=item.fidelity_mode,
                        supported_modes=list(item.supported_modes),
                        supported_aspect_ratios=list(item.supported_aspect_ratios),
                        supported_resolutions=list(item.supported_resolutions),
                        supported_qualities=list(item.supported_qualities),
                        supported_formats=list(item.supported_formats),
                        supported_image_sizes=list(item.supported_image_sizes),
                        supported_backgrounds=list(item.supported_backgrounds),
                        supported_moderation=list(item.supported_moderation),
                        supported_input_fidelities=list(item.supported_input_fidelities),
                        supports_output_compression=item.supports_output_compression,
                        max_reference_images=item.max_reference_images,
                        supports_text_rendering=item.supports_text_rendering,
                        supports_logo_input=item.supports_logo_input,
                        cost_per_output_by_setting={
                            key: str(value) for key, value in item.cost_per_output_by_setting
                        },
                        input_image_cost=str(item.input_image_cost),
                    )
                    for image_descriptor in image_descriptors
                    for item in image_descriptor.image_models
                ]
                if kind == "image"
                else []
            ),
        )

    return MarketingCreativeAutomationCapabilitiesResponse(
        image=capability("image"),
        video=capability("video"),
        agent_models=list(APPROVED_AGENT_MODELS),
        default_agent_model_id=DEFAULT_AGENT_MODEL,
        agent_reasoning_levels={
            model: list(levels) for model, levels in AGENT_REASONING_LEVELS.items()
        },
        default_agent_reasoning_level=DEFAULT_AGENT_REASONING_LEVEL,
    )


@router.get("", response_model=MarketingCreativeAutomationListResponse)
async def list_marketing_creative_automations(
    intake: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
    providers: ManagedMediaProviderRegistry = Depends(get_managed_media_provider_registry),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    storage: MarketingCreativeAutomationStorage = Depends(get_creative_automation_storage),
) -> MarketingCreativeAutomationListResponse:
    """List persisted Lead Marketing requests without exposing workflow internals."""
    persisted_jobs = await jobs.list_jobs()
    if persisted_jobs:
        items = [_job_item_response(job) for job in persisted_jobs]
        return MarketingCreativeAutomationListResponse(items=items, total=len(items))
    runs = await intake.repository.list()
    items = [
        await _persisted_item(run, providers, states, storage)
        for run in runs
        if run.trigger.source.value == "marketing_request"
    ]
    return MarketingCreativeAutomationListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=MarketingCreativeAutomationBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_marketing_creative_automation(
    payload: MarketingCreativeAutomationCreateRequest,
    response: Response,
    data_sources: DataSourceRuntime = Depends(get_data_source_runtime),
    intake: CreativeIntakeRuntime = Depends(get_creative_intake_write_runtime),
    providers: ManagedMediaProviderRegistry = Depends(get_managed_media_provider_registry),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    feedback: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
    knowledge: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
    notifications: NotificationRepository = Depends(get_notification_repository),
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    storage: MarketingCreativeAutomationStorage = Depends(get_creative_automation_storage),
    scheduler: CommandScheduler = Depends(get_command_scheduler),
    usage_repository: AIUsageRepository = Depends(get_ai_usage_repository),
    producer: MarketingCreativeAutomationProducer | None = Depends(
        get_creative_automation_producer
    ),
    source_resolver: IFrozenProductMediaResolver | None = Depends(
        get_product_media_source_resolver
    ),
    research_repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
) -> MarketingCreativeAutomationBatchResponse:
    """Create one independent durable Creative intake for every selected SKU."""
    snapshots = await data_sources.repository.list_latest_snapshots()
    batch_id = _batch_id(payload.idempotency_key)
    settings = get_runtime_settings()
    if settings.execution_backend == "celery" and not storage.shared_across_processes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery Creative automation requires shared object storage",
        )
    _apply_provider_defaults(payload, providers)
    _validate_provider_profiles(payload, providers)
    has_image_outputs = payload.image_count > 0 or any(
        profile.media_kind == "image" and profile.count > 0 for profile in payload.output_profiles
    )
    has_video_outputs = payload.video_count > 0 or any(
        profile.media_kind == "video" and profile.count > 0 for profile in payload.output_profiles
    )
    reference_assignments = _creative_reference_assignments(payload)
    selected_reference_ids = tuple(payload.selected_reference_ids)
    reference_candidates = (
        await _creative_reference_candidates(
            research_repository,
            payload.brand,
            selected_reference_ids,
            media_assets,
        )
        if payload.use_research_references and (has_image_outputs or has_video_outputs)
        else ()
    )
    logo_artifact_ref = None
    logo_checksum_sha256 = None
    if payload.include_logo and payload.logo_asset_id is not None:
        logo = await media_assets.get(payload.logo_asset_id)
        if logo.media_kind.value != "image" or logo.original_artifact_ref is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Logo asset must be a ready image",
            )
        logo_artifact_ref = logo.original_artifact_ref
        logo_checksum_sha256 = logo.checksum_sha256
    compiler = MarketingCreativeAutomationCompiler(data_sources.compiler)
    selections = payload.product_selections or payload.sku_ids
    refresh_products = getattr(data_sources, "refresh_shopify_products", None)
    if payload.product_selections and refresh_products is not None:
        try:
            snapshots = await refresh_products(
                snapshots,
                tuple((item.source_id, item.product_id) for item in payload.product_selections),
            )
        except (KeyError, SourceReadError) as error:
            detail = str(error) if isinstance(error, SourceReadError) else "Unknown data source"
            can_use_cached_snapshot = (
                settings.creative_automation_allow_cached_shopify_fallback
                and isinstance(error, SourceReadError)
                and error.code in {"AUTH_FAILED", "RATE_LIMITED", "SOURCE_HTTP_ERROR"}
            )
            if can_use_cached_snapshot:
                logger.warning(
                    "Live Shopify product refresh failed; using pinned cached snapshots "
                    "for Creative launch error_code={} selected_products={}",
                    error.code,
                    len(payload.product_selections),
                )
            else:
                response_status = (
                    status.HTTP_409_CONFLICT
                    if isinstance(error, SourceReadError) and error.code == "RESOURCE_NOT_FOUND"
                    else status.HTTP_503_SERVICE_UNAVAILABLE
                )
                raise HTTPException(
                    status_code=response_status,
                    detail=f"Live Shopify product refresh failed: {detail}",
                ) from error
    snapshot_ids = tuple(item.snapshot_id for item in snapshots)
    requests = _requests(
        payload,
        batch_id,
        selections,
        settings,
        snapshots,
        data_sources.compiler,
        reference_candidates,
        reference_assignments,
        logo_artifact_ref,
        logo_checksum_sha256,
        _video_scene_duration_max_seconds(payload, providers, settings),
        image_supports_multi_edit=_image_supports_multi_edit(payload, providers),
    )
    _validate_request_source_limits(requests, providers)
    semaphore = asyncio.Semaphore(settings.creative_automation_max_concurrency)

    async def freeze_request_sources(request: MarketingCreativeAutomationRequest) -> None:
        if source_resolver is None or request.product_family is None:
            return
        async with semaphore:
            compilation = compiler.compile(snapshots, request)
            frozen = await freeze_compilation_product_media(compilation, source_resolver)
            await storage.write_package(frozen.package)

    try:
        await asyncio.gather(*(freeze_request_sources(request) for request in requests))
    except SourceReadError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Shopify product media freeze failed: {error}",
        ) from error
    created_at = datetime.now(UTC)
    initial_jobs = tuple(
        CreativeAutomationJobSnapshot(
            job_id=request.request_id,
            batch_id=batch_id,
            request=request,
            route=decide_production_route(request).route.value,
            routing_reasons=decide_production_route(request).reasons,
            status="queued",
            provider_status=_provider_status(request.output, providers),
            created_at=created_at,
            updated_at=created_at,
        )
        for request in requests
    )
    batch = CreativeAutomationBatchSnapshot(
        batch_id=batch_id,
        brand_id=payload.brand,
        requested_by=payload.requested_by,
        job_ids=tuple(job.job_id for job in initial_jobs),
        idempotency_key=payload.idempotency_key,
        created_at=created_at,
    )
    if settings.execution_backend == "celery":
        if isinstance(jobs, PostgresCreativeAutomationJobRepository) and isinstance(
            scheduler, CeleryCommandScheduler
        ):
            queued_jobs = await jobs.create_batch_with_commands(
                batch,
                initial_jobs,
                tuple(
                    process_sku_command(batch_id, job.request, snapshot_ids) for job in initial_jobs
                ),
            )
        else:
            await jobs.create_batch(batch, initial_jobs)
            command_service = CreativeAutomationCommandService(scheduler)

            async def enqueue_job(
                job: CreativeAutomationJobSnapshot,
            ) -> CreativeAutomationJobSnapshot:
                command, _ = await resolve_queue_call(
                    command_service.enqueue_process_sku(batch_id, job.request, snapshot_ids)
                )
                queued = replace(
                    job,
                    command_id=command.command_id,
                    status=command.status.value,
                    updated_at=command.updated_at,
                )
                await jobs.save_job(
                    queued,
                    CreativeAutomationEvent(
                        event_id=_workflow_entity_id(
                            "automation-event", job.job_id, command.command_id
                        ),
                        job_id=job.job_id,
                        event_type="command:enqueued",
                        payload={
                            "command_id": command.command_id,
                            "status": command.status.value,
                        },
                        created_at=command.created_at,
                    ),
                )
                return queued

            queued_jobs = await asyncio.gather(*(enqueue_job(job) for job in initial_jobs))
        response.status_code = status.HTTP_202_ACCEPTED
        items = [_job_item_response(job) for job in queued_jobs]
        return MarketingCreativeAutomationBatchResponse(
            batch_id=batch_id,
            items=items,
            total=len(items),
        )

    await jobs.create_batch(batch, initial_jobs)

    orchestration_config = load_orchestration_config(settings.orchestration_config_path)
    orchestrator = (
        FakeCreativeAutomationOrchestrator(orchestration_config)
        if orchestration_config.backend == "fake"
        else BamlCreativeAutomationOrchestrator(
            orchestration_config,
            api_key=_configured_model_api_key(
                settings,
                orchestration_config.api_key_env,
            ),
            usage_tracker=AIUsageTracker(usage_repository),
            image_provider_descriptor=providers.image_descriptor(payload.image_provider_id),
            video_provider_descriptor=providers.video_descriptor(),
            image_reader=source_resolver.read_frozen_source,
        )
    )

    async def process(
        request: MarketingCreativeAutomationRequest,
    ) -> MarketingCreativeAutomationItemResponse:
        async with semaphore:
            try:
                return await _process_automation_request(
                    request=request,
                    batch_id=batch_id,
                    snapshots=snapshots,
                    compiler=compiler,
                    orchestrator=orchestrator,
                    intake=intake,
                    providers=providers,
                    jobs=jobs,
                    feedback=feedback,
                    knowledge=knowledge,
                    notifications=notifications,
                    states=states,
                    storage=storage,
                    settings=settings,
                    producer=producer,
                    source_resolver=source_resolver,
                    usage_tracker=AIUsageTracker(usage_repository),
                )
            except Exception as error:
                return await _record_inline_job_failure(
                    jobs, notifications, batch_id, request, error
                )

    items = list(await asyncio.gather(*(process(request) for request in requests)))
    await _notify_batch_completed(notifications, batch_id, payload.brand, items)
    return MarketingCreativeAutomationBatchResponse(
        batch_id=batch_id,
        items=items,
        total=len(items),
    )


async def _process_automation_request(
    *,
    request: MarketingCreativeAutomationRequest,
    batch_id: str,
    snapshots,
    compiler: MarketingCreativeAutomationCompiler,
    orchestrator: ICreativeAutomationOrchestrator,
    intake: CreativeIntakeRuntime,
    providers: ManagedMediaProviderRegistry,
    jobs: ICreativeAutomationJobRepository,
    feedback: CreativeFeedbackRuntime,
    knowledge: CreativeKnowledgeService,
    notifications: NotificationRepository,
    states: IMarketingCreativeAutomationStateRepository,
    storage: MarketingCreativeAutomationStorage,
    settings,
    producer: MarketingCreativeAutomationProducer | None = None,
    source_resolver: IFrozenProductMediaResolver | None = None,
    usage_tracker: AIUsageTracker | None = None,
) -> MarketingCreativeAutomationItemResponse:
    routing = decide_production_route(request)
    stored_package = await storage.read_package(request.request_id)
    existing = await intake.repository.get_by_source_run_id(
        _intake_source_run_id(request.request_id)
    )
    if existing is not None:
        conflict = _existing_conflict(existing, request, stored_package)
        resume_orchestration = conflict is None and (
            stored_package is None or stored_package.automation_plan is None
        )
        if resume_orchestration and stored_package is not None:
            request = stored_package.request
        if not resume_orchestration:
            issues = (
                [
                    MarketingCreativeAutomationIssueResponse(
                        code="idempotency_conflict",
                        detail=conflict,
                    )
                ]
                if conflict
                else [
                    MarketingCreativeAutomationIssueResponse(
                        code=issue.code,
                        detail=issue.detail,
                        component=issue.component.value if issue.component else None,
                    )
                    for issue in existing.issues
                ]
            )
            job_id = existing.release.downstream_job_id if existing.release else None
            recorded_route = ProductionRoute(existing.context.production_route)
            package_ref = await storage.package_ref(request.request_id)
            workflow_state, workflow_ref = await _existing_or_initialize_state(
                states,
                request,
                existing.context.production_route,
                _status(
                    recorded_route,
                    existing.state.value,
                    job_id,
                    CreativeAutomationExecutionMode(existing.context.execution_mode),
                ),
                package_ref,
            )
            if workflow_state.status == MarketingCreativeAutomationStatus.PRODUCING:
                workflow_state = record_production_outcome(
                    workflow_state,
                    (),
                    error_code="CREATIVE_PRODUCTION_WORKER_INTERRUPTED",
                    error_detail=(
                        "Production stopped after provider execution began. Review usage and "
                        "request Generate Again explicitly to avoid duplicate paid output."
                    ),
                )
                await resolve_state_repository_call(states.save(workflow_state))
                issues.append(
                    MarketingCreativeAutomationIssueResponse(
                        code="CREATIVE_PRODUCTION_WORKER_INTERRUPTED",
                        detail=(
                            "Production was interrupted before a reviewable output set was saved."
                        ),
                        component="production",
                    )
                )
            item = _item_response(
                request,
                existing.context.production_route,
                list(existing.context.routing_reasons),
                "conflict" if conflict else workflow_state.status.value,
                existing.run_id,
                job_id,
                package_ref,
                workflow_ref,
                workflow_state,
                issues,
                _provider_status(request.output, providers),
                batch_id=batch_id,
            )
            await _persist_job_result(
                jobs,
                batch_id,
                request,
                item,
                stored_package.automation_plan if stored_package is not None else None,
            )
            await _notify_job_result(notifications, item)
            return item

    assigned_reference_ids = {
        reference_id
        for assignment in request.reference_assignments
        for reference_id in assignment.reference_ids
    }
    if source_resolver is not None and assigned_reference_ids:
        resolve_reference = getattr(source_resolver, "resolve_reference_asset", None)
        if resolve_reference is None:
            raise ValueError("Configured media resolver cannot materialize research references")
        async with measure_automation_step(jobs, request.request_id, "research_references"):
            await asyncio.gather(
                *(
                    resolve_reference(
                        reference_id=item.reference_id,
                        artifact_ref=item.artifact_ref,
                        checksum_sha256=item.checksum_sha256,
                    )
                    for item in request.reference_candidates
                    if item.reference_id in assigned_reference_ids
                )
            )
    async with measure_automation_step(jobs, request.request_id, "context_compilation"):
        compilation = compiler.compile(snapshots, request)
    if source_resolver is not None:
        async with measure_automation_step(jobs, request.request_id, "product_media_freeze"):
            compilation = await freeze_compilation_product_media(
                compilation,
                source_resolver,
                existing_package=stored_package,
            )
    async with measure_automation_step(jobs, request.request_id, "approved_memory"):
        approved_runs = await feedback.repository.list_approved_memory(
            brand_id=request.brand,
            sku_id=request.sku_id,
        )
    approved_memory = tuple(
        ApprovedCreativeMemory(
            memory_id=run.lesson.lesson_id,
            summary=run.lesson.summary,
            supported_facts=run.lesson.supported_facts,
            non_conclusions=run.lesson.non_conclusions,
            evidence_refs=run.lesson.evidence_refs,
        )
        for run in approved_runs
        if run.lesson is not None
    )
    family = compilation.package.sku.product_family
    knowledge_scope = KnowledgeScope(
        niche_id=(
            product_niche(product_type=family.product_type, title=family.title)
            if family is not None
            else None
        ),
        brand_id=request.brand,
        product_archetype=(
            product_archetype(product_type=family.product_type, title=family.title)
            if family is not None
            else None
        ),
        product_family_id=(
            request.product_family.product_id if request.product_family is not None else None
        ),
        variant_id=request.selected_variant_id,
        platform=request.platform,
        market=request.market,
        task_type="sku_to_output",
    )
    async with measure_automation_step(jobs, request.request_id, "creative_knowledge"):
        generation_stages = (
            KnowledgeStage.PERSONA,
            KnowledgeStage.PREPARATION,
            KnowledgeStage.ORCHESTRATION,
        )
        runtime_stages = (*generation_stages, KnowledgeStage.REVIEW)
        if stored_package is not None and stored_package.knowledge_assignments:
            knowledge_by_stage = {
                KnowledgeStage(assignment.stage): await _load_creative_knowledge_versions(
                    knowledge,
                    assignment.version_refs,
                )
                for assignment in stored_package.knowledge_assignments
                if KnowledgeStage(assignment.stage) in runtime_stages
            }
        elif stored_package is not None and stored_package.knowledge_refs:
            legacy_knowledge = await _load_creative_knowledge_versions(
                knowledge, stored_package.knowledge_refs
            )
            knowledge_by_stage = dict.fromkeys(generation_stages, legacy_knowledge)
        else:
            knowledge_by_stage = {
                stage: await _resolve_creative_knowledge(
                    knowledge,
                    knowledge_scope,
                    stage=stage,
                    include_image=request.output.image_output_count > 0,
                    include_video=request.output.video_output_count > 0,
                )
                for stage in runtime_stages
            }
        knowledge_by_stage = {
            stage: knowledge_by_stage.get(stage, ()) for stage in runtime_stages
        }
    approved_knowledge = tuple(
        {
            item.version_ref: item
            for stage in generation_stages
            for item in knowledge_by_stage[stage]
        }.values()
    )
    knowledge_assignments = tuple(
        CreativeKnowledgeAssignment(
            stage=stage.value,
            version_refs=tuple(item.version_ref for item in knowledge_by_stage.get(stage, ())),
        )
        for stage in runtime_stages
    )
    review_checklist = tuple(
        f"{item.title}: {item.content}"
        for item in knowledge_by_stage[KnowledgeStage.REVIEW]
    )
    compilation = replace(
        compilation,
        package=replace(
            compilation.package,
            knowledge_refs=tuple(item.version_ref for item in approved_knowledge),
            knowledge_assignments=knowledge_assignments,
            review_checklist=review_checklist,
        ),
    )
    base_compilation = register_context_sources(
        compilation,
        _memory_sources(approved_memory),
    )
    persona_compilation = register_context_sources(
        base_compilation,
        _memory_sources(
            _creative_knowledge_memory(knowledge_by_stage[KnowledgeStage.PERSONA])
        ),
    )
    preparation_config = load_preparation_config(
        settings.preparation_config_path or settings.config_dir / "preparation/synthetic.json"
    )
    if preparation_config.backend == "baml":
        preparation_config = preparation_config.model_copy(
            update={
                "model": (
                    route_approved_agent_model(
                        request.agent_model_id,
                        configured_model=preparation_config.model,
                    )
                    if request.agent_model_id
                    else preparation_config.model
                ),
                "reasoning_effort": (
                    None
                    if request.agent_reasoning_effort in {None, "auto"}
                    else request.agent_reasoning_effort
                ),
            }
        )
    persona_resolver = None
    if preparation_config.backend == "baml":
        persona_resolver = BamlPreparationModel(
            preparation_config,
            api_key=_configured_model_api_key(
                settings,
                preparation_config.api_key_env,
            ),
            usage_tracker=usage_tracker,
            image_reader=(
                source_resolver.read_frozen_source if source_resolver is not None else None
            ),
        )
    if (
        not persona_compilation.intake.cases[0].context_template.personas
        and persona_resolver is not None
    ):
        async with measure_automation_step(jobs, request.request_id, "persona_resolution"):
            persona_compilation = await resolve_missing_persona(
                persona_compilation,
                persona_resolver,
                pinned=(stored_package.persona_resolution if stored_package is not None else None),
            )
    preparation_knowledge = knowledge_by_stage[KnowledgeStage.PREPARATION]
    if persona_compilation.package.persona_resolution is not None:
        cited_refs = set(persona_compilation.package.persona_resolution.persona.evidence_refs)
        preparation_knowledge = tuple(
            {
                item.version_ref: item
                for item in (
                    *preparation_knowledge,
                    *knowledge_by_stage[KnowledgeStage.PERSONA],
                )
                if item.version_ref in cited_refs
                or item in knowledge_by_stage[KnowledgeStage.PREPARATION]
            }.values()
        )
    compilation = register_context_sources(
        base_compilation,
        _memory_sources(_creative_knowledge_memory(preparation_knowledge)),
    )
    if persona_compilation.package.persona_resolution is not None and persona_resolver is not None:
        compilation = await resolve_missing_persona(
            compilation,
            persona_resolver,
            pinned=persona_compilation.package.persona_resolution,
        )
    async with measure_automation_step(jobs, request.request_id, "initial_package_persistence"):
        package_ref = await storage.write_package(compilation.package)
    async with measure_automation_step(jobs, request.request_id, "brief_preparation"):
        outcome = await intake.run(
            compilation.intake,
            dispatch_m1=True,
            preparation_config=preparation_config,
            config_dir=settings.config_dir,
            image_reader=(
                source_resolver.read_frozen_source if source_resolver is not None else None
            ),
        )
    prepared = outcome.prepared_briefs[0]
    plan = None
    if prepared is not None:
        async with measure_automation_step(jobs, request.request_id, "orchestration_planning"):
            orchestration_memory = (
                *approved_memory,
                *_creative_knowledge_memory(
                    knowledge_by_stage[KnowledgeStage.ORCHESTRATION]
                ),
            )
            plan = await orchestrator.plan(
                request,
                prepared.context,
                prepared,
                orchestration_memory,
            )
        async with measure_automation_step(jobs, request.request_id, "planned_package_persistence"):
            package_ref = await storage.write_package(
                replace(
                    compilation.package,
                    selected_idea=prepared.selected_idea,
                    brief=prepared.brief,
                    strategy=prepared.strategy,
                    automation_plan=plan,
                    knowledge_refs=tuple(item.version_ref for item in approved_knowledge),
                    knowledge_assignments=knowledge_assignments,
                    review_checklist=review_checklist,
                )
            )
    run = outcome.runs[0]
    issues = [
        MarketingCreativeAutomationIssueResponse(
            code=issue.code,
            detail=issue.detail,
            component=issue.component.value if issue.component else None,
        )
        for issue in run.issues
    ]
    if plan is not None and plan.readiness == OrchestrationReadiness.NEEDS_INPUT:
        issues.extend(
            MarketingCreativeAutomationIssueResponse(
                code="orchestration-context-missing",
                detail=detail,
                component="orchestration",
            )
            for detail in plan.missing_context
        )
    job_id = run.release.downstream_job_id if run.release else None
    item_status = _status(
        routing.route,
        run.state.value,
        job_id,
        request.execution_mode,
    )
    if prepared is None and run.release is not None:
        item_status = "needs_input"
        issues.append(
            MarketingCreativeAutomationIssueResponse(
                code=run.release.handoff_error or "brief_preparation_failed",
                detail=(
                    "Creative brief preparation did not complete. No paid media request was sent; "
                    "review the preparation trace and correct the cited context before retrying."
                ),
                component="preparation",
            )
        )
    if plan is not None and plan.readiness == OrchestrationReadiness.NEEDS_INPUT:
        item_status = "needs_input"
    workflow_state, workflow_ref = await _existing_or_initialize_state(
        states,
        request,
        routing.route.value,
        item_status,
        package_ref,
    )
    if producer is not None and workflow_state.status.value == "awaiting_generation_provider":
        production_package = await storage.read_package(request.request_id, package_ref)
        if production_package is None:
            raise RuntimeError("Production-ready Creative package artifact is missing")
        try:
            async with measure_automation_step(jobs, request.request_id, "media_production"):
                workflow_state = await producer.produce(production_package)
        except Exception:
            persisted_state = await resolve_state_repository_call(states.get(request.request_id))
            if (
                persisted_state is None
                or persisted_state.status.value != "production_needs_attention"
            ):
                raise
            workflow_state = persisted_state
            issues.append(
                MarketingCreativeAutomationIssueResponse(
                    code=(workflow_state.production_error_code or "paid_media_production_failed"),
                    detail=(
                        workflow_state.production_error_detail
                        or "Paid media production requires Marketing attention."
                    ),
                    component="production",
                )
            )
        item_status = workflow_state.status.value
    item = _item_response(
        request,
        routing.route.value,
        list(routing.reasons),
        workflow_state.status.value,
        run.run_id,
        job_id,
        package_ref,
        workflow_ref,
        workflow_state,
        issues,
        _provider_status(request.output, providers),
        batch_id=batch_id,
    )
    await _persist_job_result(jobs, batch_id, request, item, plan)
    await record_automation_total_latency(
        jobs,
        request.request_id,
        outcome=(
            "failed" if item.status in {"failed", "production_needs_attention"} else "succeeded"
        ),
    )
    await _notify_job_result(notifications, item)
    return item


@router.get(
    "/{request_id}",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def get_marketing_creative_automation(
    request_id: str,
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    storage: MarketingCreativeAutomationStorage = Depends(get_creative_automation_storage),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    job = await jobs.get_job(request_id)
    if state is None and job is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    if state is None:
        state = _job_backed_state(job)
    events = await jobs.list_events(request_id) if job is not None else []
    package = await storage.read_package(request_id, state.package_ref)
    return _state_response(
        state,
        ads_providers,
        issues=(
            [
                MarketingCreativeAutomationIssueResponse(
                    code=issue.code,
                    detail=issue.detail,
                    component=issue.component,
                )
                for issue in job.issues
            ]
            if job is not None
            else None
        ),
        trace=_trace_response(state, job, events, package),
    )


def _job_backed_state(
    job: CreativeAutomationJobSnapshot,
) -> MarketingCreativeAutomationState:
    """Expose durable job progress even before a workflow state exists."""
    return initialize_automation_state(
        request_id=job.request.request_id,
        package_id=f"creative-package:{job.request.request_id}",
        package_ref=job.package_ref or package_artifact_ref(job.request.request_id),
        route=job.route,
        status=job.status,
        now=job.created_at,
    )


@router.post(
    "/{request_id}/review-decision",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def decide_marketing_creative_review(
    request_id: str,
    payload: MarketingCreativeReviewDecisionRequest,
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    storage: MarketingCreativeAutomationStorage = Depends(get_creative_automation_storage),
    knowledge: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    notifications: NotificationRepository = Depends(get_notification_repository),
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    package = await storage.read_package(request_id, state.package_ref)
    if package is None:
        raise HTTPException(status_code=409, detail="Creative package is unavailable")
    decision_id = _workflow_entity_id("creative-decision", request_id, payload.idempotency_key)
    existing = state.review_decision
    if existing is not None:
        if (
            existing.decision_id == decision_id
            and existing.review_id == payload.review_id
            and existing.asset_version_ids == tuple(payload.asset_version_ids)
            and existing.asset_checksums == tuple(payload.asset_checksums)
            and existing.decision == payload.decision
            and existing.reviewer_alias == payload.reviewer_alias
            and existing.reason == payload.reason
            and existing.key_visual_asset_version_id == payload.key_visual_asset_version_id
        ):
            await _record_human_feedback(
                knowledge,
                package,
                state,
                feedback_id=f"human-feedback:{decision_id}",
                title=f"Human review for {package.request.sku_id}",
                content=payload.reason,
                reviewer=payload.reviewer_alias,
                asset_version_ids=tuple(payload.asset_version_ids),
                source_refs=tuple(
                    f"creative-output:{value}" for value in payload.asset_version_ids
                ),
                acceptance=payload.decision == "approve",
            )
            await _persist_state_job_projection(jobs, notifications, state)
            return _state_response(state, ads_providers)
        raise HTTPException(status_code=409, detail="Creative review was already decided")
    try:
        updated = decide_final_review(
            state,
            decision_id=decision_id,
            review_id=payload.review_id,
            asset_version_ids=tuple(payload.asset_version_ids),
            asset_checksums=tuple(payload.asset_checksums),
            decision=payload.decision,
            reviewer_alias=payload.reviewer_alias,
            reason=payload.reason,
            key_visual_asset_version_id=payload.key_visual_asset_version_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await resolve_state_repository_call(states.save(updated))
    await _record_human_feedback(
        knowledge,
        package,
        updated,
        feedback_id=f"human-feedback:{decision_id}",
        title=f"Human review for {package.request.sku_id}",
        content=payload.reason,
        reviewer=payload.reviewer_alias,
        asset_version_ids=tuple(payload.asset_version_ids),
        source_refs=tuple(f"creative-output:{value}" for value in payload.asset_version_ids),
        acceptance=payload.decision == "approve",
    )
    await _persist_state_job_projection(jobs, notifications, updated)
    return _state_response(updated, ads_providers)


@router.post(
    "/{request_id}/generate-again",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def generate_marketing_creative_again(
    request_id: str,
    payload: MarketingCreativeGenerateAgainRequest,
    response: Response,
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    storage: MarketingCreativeAutomationStorage = Depends(get_creative_automation_storage),
    knowledge: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    notifications: NotificationRepository = Depends(get_notification_repository),
    scheduler: CommandScheduler = Depends(get_command_scheduler),
    producer: MarketingCreativeAutomationProducer | None = Depends(
        get_creative_automation_producer
    ),
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    package = await storage.read_package(request_id, state.package_ref)
    if package is None:
        raise HTTPException(status_code=409, detail="Creative package is unavailable")
    generation_request_id = _workflow_entity_id(
        "generation-request", request_id, payload.idempotency_key
    )
    existing_request = next(
        (
            item
            for item in state.generation_requests
            if item.generation_request_id == generation_request_id
        ),
        None,
    )
    settings = get_runtime_settings()
    if existing_request is not None:
        if (
            existing_request.requested_by != payload.requested_by
            or existing_request.reason != payload.reason
            or existing_request.target_asset_version_ids != tuple(payload.target_asset_version_ids)
        ):
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used for another generation request",
            )
        await _record_human_feedback(
            knowledge,
            package,
            state,
            feedback_id=f"human-feedback:{generation_request_id}",
            title=f"Revision feedback for {package.request.sku_id}",
            content=payload.reason,
            reviewer=payload.requested_by,
            asset_version_ids=tuple(payload.target_asset_version_ids),
            source_refs=(f"generation-request:{generation_request_id}",),
            acceptance=False,
        )
        if settings.execution_backend == "celery":
            await resolve_queue_call(
                CreativeAutomationCommandService(scheduler).enqueue_generate_again(
                    request_id,
                    generation_request_id,
                )
            )
            response.status_code = status.HTTP_202_ACCEPTED
        await _persist_state_job_projection(jobs, notifications, state)
        return _state_response(state, ads_providers)
    if settings.execution_backend != "celery" and producer is None:
        raise HTTPException(
            status_code=409,
            detail="An approved media provider and immutable source resolver are not configured",
        )
    if _targets_are_exact_source_transforms(state, tuple(payload.target_asset_version_ids)):
        raise HTTPException(
            status_code=409,
            detail=(
                "Exact Shopify source transforms are deterministic. Start a new request with "
                "another source or format, or take over manually for a different creative."
            ),
        )
    feedback_id = f"human-feedback:{generation_request_id}"
    revision_media_kind = _single_media_kind(state, tuple(payload.target_asset_version_ids))
    revision_knowledge = tuple(
        item
        for item in await _resolve_creative_knowledge(
            knowledge,
            _knowledge_scope_for_package(package),
            stage=KnowledgeStage.REVISION,
            include_image=(revision_media_kind in {None, "image"}),
            include_video=(revision_media_kind in {None, "video"}),
        )
        if item.knowledge_type.value != "feedback"
    )
    revision_guidance = tuple(
        f"[{item.knowledge_type.value}] {item.title}: {item.content}"
        + (
            f" Limits: {'; '.join(item.non_conclusions)}"
            if item.non_conclusions
            else ""
        )
        for item in revision_knowledge
    )
    try:
        updated = request_generation_again(
            state,
            generation_request_id=generation_request_id,
            requested_by=payload.requested_by,
            reason=payload.reason,
            target_asset_version_ids=tuple(payload.target_asset_version_ids),
            knowledge_refs=tuple(item.version_ref for item in revision_knowledge),
            revision_guidance=revision_guidance,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await resolve_state_repository_call(states.save(updated))
    await _record_human_feedback(
        knowledge,
        package,
        updated,
        feedback_id=feedback_id,
        title=f"Revision feedback for {package.request.sku_id}",
        content=payload.reason,
        reviewer=payload.requested_by,
        asset_version_ids=tuple(payload.target_asset_version_ids),
        source_refs=(f"generation-request:{generation_request_id}",),
        acceptance=False,
    )
    if settings.execution_backend == "celery":
        await resolve_queue_call(
            CreativeAutomationCommandService(scheduler).enqueue_generate_again(
                request_id,
                generation_request_id,
            )
        )
        await _persist_state_job_projection(jobs, notifications, updated)
        response.status_code = status.HTTP_202_ACCEPTED
        return _state_response(updated, ads_providers)
    assert producer is not None
    try:
        produced = await producer.produce(package)
    except Exception as error:
        current = await resolve_state_repository_call(states.get(request_id))
        if current is not None:
            await _persist_state_job_projection(jobs, notifications, current)
        raise HTTPException(
            status_code=502,
            detail="Paid media production failed before a reviewable output set was ready",
        ) from error
    await _persist_state_job_projection(jobs, notifications, produced)
    return _state_response(produced, ads_providers)


@router.post(
    "/{request_id}/manual-takeover",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def take_over_marketing_creative_manually(
    request_id: str,
    payload: MarketingCreativeManualTakeoverRequest,
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    notifications: NotificationRepository = Depends(get_notification_repository),
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    takeover_id = _workflow_entity_id("manual-takeover", request_id, payload.idempotency_key)
    existing = state.manual_takeover
    if existing is not None:
        if (
            existing.takeover_id == takeover_id
            and existing.requested_by == payload.requested_by
            and existing.reason == payload.reason
        ):
            await _persist_state_job_projection(jobs, notifications, state)
            return _state_response(state, ads_providers)
        raise HTTPException(status_code=409, detail="Creative automation was already taken over")
    try:
        updated = request_manual_takeover(
            state,
            takeover_id=takeover_id,
            requested_by=payload.requested_by,
            reason=payload.reason,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await resolve_state_repository_call(states.save(updated))
    await _persist_state_job_projection(jobs, notifications, updated)
    return _state_response(updated, ads_providers)


@router.post(
    "/{request_id}/ads-draft",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def create_marketing_creative_ads_draft(
    request_id: str,
    payload: MarketingCreativeAdsDraftCreateRequest,
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    notifications: NotificationRepository = Depends(get_notification_repository),
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    draft_id = _workflow_entity_id("ads-draft", request_id, payload.idempotency_key)
    if state.ads_draft is not None:
        existing = state.ads_draft
        if existing.draft_id != draft_id:
            raise HTTPException(status_code=409, detail="An Ads Draft already exists")
        if (
            existing.destination_ref != payload.destination_ref
            or existing.daily_budget != payload.daily_budget
            or existing.currency != payload.currency.upper()
        ):
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used with a different Ads Draft",
            )
        await _persist_state_job_projection(jobs, notifications, state)
        return _state_response(state, ads_providers)
    if state.final_review is None:
        raise HTTPException(status_code=409, detail="Final Creative review is unavailable")
    decision = state.review_decision
    if decision is None or decision.decision != "approve":
        raise HTTPException(status_code=409, detail="Final Creative approval is unavailable")
    approved_ids = set(decision.asset_version_ids)
    assets_by_id = {
        asset.asset_version_id: ExactCreativeAsset(
            asset.asset_version_id,
            asset.artifact_ref,
            asset.checksum_sha256,
            asset.media_kind,
        )
        for asset in state.final_review.assets
        if asset.asset_version_id in approved_ids
    }
    assets = tuple(assets_by_id[asset_id] for asset_id in decision.asset_version_ids)
    draft = build_ads_draft(
        draft_id=draft_id,
        request_id=state.request_id,
        brand_id=state.final_review.brand_id,
        sku_id=state.final_review.sku_id,
        platform=state.final_review.platform,
        objective=state.final_review.objective,
        destination_ref=payload.destination_ref,
        daily_budget=payload.daily_budget,
        currency=payload.currency.upper(),
        assets=assets,
    )
    try:
        updated = attach_ads_draft(state, draft)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await resolve_state_repository_call(states.save(updated))
    await _persist_state_job_projection(jobs, notifications, updated)
    return _state_response(updated, ads_providers)


@router.post(
    "/{request_id}/ads-draft/approval",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def approve_marketing_creative_ads_draft(
    request_id: str,
    payload: MarketingCreativeAdsApprovalRequest,
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    notifications: NotificationRepository = Depends(get_notification_repository),
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    draft = state.ads_draft
    if draft is None:
        raise HTTPException(status_code=409, detail="Ads Draft is unavailable")
    current_ids = tuple(asset.asset_version_id for asset in draft.assets)
    current_checksums = tuple(asset.checksum_sha256 for asset in draft.assets)
    if (
        payload.draft_id != draft.draft_id
        or payload.draft_fingerprint != draft.draft_fingerprint
        or tuple(payload.asset_version_ids) != current_ids
        or tuple(payload.asset_checksums) != current_checksums
    ):
        raise HTTPException(status_code=409, detail="Ads Draft changed before approval")
    approval_id = _workflow_entity_id("ads-approval", request_id, payload.idempotency_key)
    existing = state.ads_approval
    if existing is not None:
        if (
            existing.approval_id == approval_id
            and existing.draft_id == payload.draft_id
            and existing.draft_fingerprint == payload.draft_fingerprint
            and existing.asset_version_ids == current_ids
            and existing.asset_checksums == current_checksums
            and existing.reviewer_alias == payload.reviewer_alias
            and existing.reason == payload.reason
        ):
            await _persist_state_job_projection(jobs, notifications, state)
            return _state_response(state, ads_providers)
        raise HTTPException(status_code=409, detail="Ads Draft was already approved")
    try:
        updated, _ = approve_automation_ads_draft(
            state,
            approval_id=approval_id,
            reviewer_alias=payload.reviewer_alias,
            reason=payload.reason,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await resolve_state_repository_call(states.save(updated))
    await _persist_state_job_projection(jobs, notifications, updated)
    return _state_response(updated, ads_providers)


@router.post(
    "/{request_id}/ads-draft/activate",
    response_model=MarketingCreativeAutomationDetailResponse,
)
async def activate_marketing_creative_ads_draft(
    request_id: str,
    payload: MarketingCreativeAdsActivationRequest,
    states: IMarketingCreativeAutomationStateRepository = Depends(
        get_creative_automation_state_repository
    ),
    jobs: ICreativeAutomationJobRepository = Depends(get_creative_automation_job_repository),
    notifications: NotificationRepository = Depends(get_notification_repository),
    ads_providers: AdsActivationProviderRegistry = Depends(get_ads_activation_provider_registry),
) -> MarketingCreativeAutomationDetailResponse:
    state = await resolve_state_repository_call(states.get(request_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Creative automation request not found")
    draft = state.ads_draft
    if draft is None:
        raise HTTPException(status_code=409, detail="Ads Draft is unavailable")
    if (
        payload.draft_id != draft.draft_id
        or payload.draft_fingerprint != draft.draft_fingerprint
        or tuple(payload.asset_version_ids)
        != tuple(asset.asset_version_id for asset in draft.assets)
        or tuple(payload.asset_checksums) != tuple(asset.checksum_sha256 for asset in draft.assets)
    ):
        raise HTTPException(status_code=409, detail="Ads Draft changed before activation")
    if state.ads_receipt is not None:
        await _persist_state_job_projection(jobs, notifications, state)
        return _state_response(state, ads_providers)
    try:
        updated, _ = await activate_automation_ads(
            state,
            AdsActivationService(ads_providers),
        )
    except AdsActivationDisabledError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await resolve_state_repository_call(states.save(updated))
    await _persist_state_job_projection(jobs, notifications, updated)
    return _state_response(updated, ads_providers)


async def _persist_state_job_projection(
    jobs: ICreativeAutomationJobRepository,
    notifications: NotificationRepository,
    state: MarketingCreativeAutomationState,
) -> None:
    job = await jobs.get_job(state.request_id)
    if job is None:
        return
    updated = replace(
        job,
        status=state.status.value,
        review_id=state.final_review.review_id if state.final_review is not None else None,
        asset_count=_successful_output_count(state),
        ads_draft_id=state.ads_draft.draft_id if state.ads_draft is not None else None,
        total_cost=sum(
            (asset.total_cost for asset in state.production_assets),
            start=Decimal("0"),
        ),
        issues=_state_projection_issues(job, state),
        updated_at=state.updated_at,
    )
    await jobs.save_job(
        updated,
        CreativeAutomationEvent(
            event_id=_workflow_entity_id(
                "automation-event", state.request_id, f"{state.status.value}:{state.revision}"
            ),
            job_id=state.request_id,
            event_type=f"status:{state.status.value}",
            payload={
                "status": state.status.value,
                "review_id": updated.review_id or "",
                "asset_count": updated.asset_count,
            },
            created_at=state.updated_at,
        ),
    )
    await _notify_job_result(notifications, _job_item_response(updated))


def _successful_output_count(state: MarketingCreativeAutomationState) -> int:
    latest: dict[str, ProducedCreativeAssetRecord] = {}
    for asset in state.production_assets:
        marker = asset.asset_version_id.rsplit(":v", 1)[0].split(":")
        if len(marker) >= 2 and marker[-2] in {"image", "video"} and marker[-1].isdigit():
            slot = f"{marker[-2]}:{int(marker[-1])}"
        elif any(asset.asset_version_id.startswith(f"{kind}-v") for kind in ("image", "video")):
            slot = f"{asset.media_kind}:1"
        else:
            slot = asset.asset_version_id
        latest[slot] = asset
    return sum(1 for asset in latest.values() if asset.success)


def _state_projection_issues(
    job: CreativeAutomationJobSnapshot,
    state: MarketingCreativeAutomationState,
) -> tuple[CreativeAutomationJobIssue, ...]:
    retained = tuple(issue for issue in job.issues if issue.component != "production")
    if state.status.value != "production_needs_attention":
        return retained
    failed_asset = next(
        (asset for asset in reversed(state.production_assets) if not asset.success),
        None,
    )
    code = (
        state.production_error_code
        or (failed_asset.outcome if failed_asset is not None else None)
        or "paid_media_production_failed"
    )
    detail = state.production_error_detail
    if detail is None and failed_asset is not None and failed_asset.attempts:
        detail = failed_asset.attempts[-1].evaluation.summary
    return (
        *retained,
        CreativeAutomationJobIssue(
            code=code,
            detail=detail or "Paid media production requires Marketing attention.",
            component="production",
        ),
    )


async def _record_inline_job_failure(
    jobs: ICreativeAutomationJobRepository,
    notifications: NotificationRepository,
    batch_id: str,
    request: MarketingCreativeAutomationRequest,
    error: Exception,
) -> MarketingCreativeAutomationItemResponse:
    existing = await jobs.get_job(request.request_id)
    timestamp = datetime.now(UTC)
    error_code = type(error).__name__
    detail = "Creative automation could not complete this SKU job."
    failed = replace(
        existing
        or CreativeAutomationJobSnapshot(
            job_id=request.request_id,
            batch_id=batch_id,
            request=request,
            route=decide_production_route(request).route.value,
            routing_reasons=decide_production_route(request).reasons,
            status="failed",
            provider_status="not_configured",
            created_at=request.requested_at,
            updated_at=timestamp,
        ),
        status="failed",
        issues=(
            *(existing.issues if existing is not None else ()),
            CreativeAutomationJobIssue(error_code, detail),
        ),
        updated_at=timestamp,
    )
    await jobs.save_job(
        failed,
        CreativeAutomationEvent(
            event_id=_workflow_entity_id(
                "automation-event", request.request_id, f"failed:{error_code}"
            ),
            job_id=request.request_id,
            event_type="status:failed",
            payload={"status": "failed", "error_code": error_code},
            created_at=timestamp,
        ),
    )
    await record_automation_total_latency(
        jobs,
        request.request_id,
        outcome="failed",
        completed_at=timestamp,
    )
    item = _job_item_response(failed)
    await _notify_job_result(notifications, item)
    return item


async def _notify_job_result(
    repository: NotificationRepository,
    item: MarketingCreativeAutomationItemResponse,
) -> None:
    notification_copy = {
        "needs_input": (
            "needs_input",
            f"{item.sku_id} needs input",
            "Add the missing product or brand context before this Creative job can continue.",
        ),
        "brief_ready": (
            "brief_ready",
            f"{item.sku_id} brief is ready",
            "Open the production-ready brief and continue with human production.",
        ),
        "manual_handoff_ready": (
            "handoff_ready",
            f"{item.sku_id} is ready for manual production",
            "The Creative package is ready for the Marketing team to produce.",
        ),
        "assisted_handoff_ready": (
            "handoff_ready",
            f"{item.sku_id} is ready for assisted production",
            "The Creative package is ready for a human-assisted production pass.",
        ),
        "ready_for_review": (
            "ready_for_review",
            f"{item.sku_id} is ready for review",
            "Review the generated Creative assets and approve or take over manually.",
        ),
        "production_needs_attention": (
            "needs_attention",
            f"{item.sku_id} needs attention",
            "The Creative job stopped and requires a Marketing decision.",
        ),
        "creative_approved": (
            "creative_approved",
            f"{item.sku_id} Creative is approved",
            "The exact Creative versions are approved and an Ads Draft can be prepared.",
        ),
        "ads_draft_ready": (
            "ads_approval_required",
            f"{item.sku_id} Ads Draft needs approval",
            "Review the destination, budget and exact Creative versions before activation.",
        ),
        "ads_approved": (
            "ads_approved",
            f"{item.sku_id} Ads Draft is approved",
            "Activation remains locked until an approved Ads adapter is available.",
        ),
        "activated": (
            "activated",
            f"{item.sku_id} Ads are active",
            "The approved Ads Draft was activated and its receipt was recorded.",
        ),
        "failed": (
            "failed",
            f"{item.sku_id} failed",
            "The Creative job failed and requires attention before it can continue.",
        ),
    }.get(item.status)
    if notification_copy is None:
        return
    kind, title, detail = notification_copy
    identity = (
        item.review_id
        or item.ads_draft_id
        or (item.issues[0].code if item.issues else None)
        or item.status
    )
    timestamp = datetime.now(UTC)
    await repository.save(
        Notification(
            notification_id=_workflow_entity_id(
                "notification", item.request_id, f"{item.status}:{identity}"
            ),
            scope_type="creative_automation_job",
            scope_id=item.request_id,
            kind=kind,
            title=title,
            detail=detail,
            action_path=f"/creative-production/{item.request_id}",
            created_at=timestamp,
            updated_at=timestamp,
            payload={"sku_id": item.sku_id, "status": item.status},
        )
    )


async def _notify_batch_completed(
    repository: NotificationRepository,
    batch_id: str,
    brand_id: str,
    items: list[MarketingCreativeAutomationItemResponse],
) -> None:
    timestamp = datetime.now(UTC)
    attention_count = sum(
        item.status in {"needs_input", "production_needs_attention", "failed"} for item in items
    )
    detail = f"{len(items)} SKU jobs finished initial preparation."
    if attention_count:
        detail += f" {attention_count} require attention."
    await repository.save(
        Notification(
            notification_id=_workflow_entity_id(
                "notification", batch_id, "initial-preparation-completed"
            ),
            scope_type="creative_automation_batch",
            scope_id=batch_id,
            kind="batch_completed",
            title="Creative Production batch completed",
            detail=detail,
            action_path="/creative-production",
            created_at=timestamp,
            updated_at=timestamp,
            payload={
                "brand_id": brand_id,
                "job_count": len(items),
                "attention_count": attention_count,
            },
        )
    )


async def _persist_job_result(
    repository: ICreativeAutomationJobRepository,
    batch_id: str,
    request: MarketingCreativeAutomationRequest,
    item: MarketingCreativeAutomationItemResponse,
    plan,
) -> None:
    existing = await repository.get_job(request.request_id)
    created_at = existing.created_at if existing is not None else request.requested_at
    timestamp = datetime.now(UTC)
    snapshot = CreativeAutomationJobSnapshot(
        job_id=request.request_id,
        batch_id=batch_id,
        request=request,
        route=item.route,
        routing_reasons=tuple(item.routing_reasons),
        status=item.status,
        provider_status=item.provider_status,
        created_at=created_at,
        updated_at=timestamp,
        command_id=existing.command_id if existing is not None else None,
        intake_run_id=item.intake_run_id,
        creative_job_id=item.creative_job_id,
        package_ref=item.package_ref,
        workflow_ref=item.workflow_ref,
        review_id=item.review_id,
        asset_count=item.asset_count,
        ads_draft_id=item.ads_draft_id,
        issues=tuple(
            CreativeAutomationJobIssue(issue.code, issue.detail, issue.component)
            for issue in item.issues
        ),
        input_tokens=(
            plan.input_tokens
            if plan is not None
            else existing.input_tokens
            if existing is not None
            else None
        ),
        output_tokens=(
            plan.output_tokens
            if plan is not None
            else existing.output_tokens
            if existing is not None
            else None
        ),
        total_cost=existing.total_cost if existing is not None else Decimal("0"),
    )
    event_id = _workflow_entity_id("automation-event", request.request_id, item.status)
    await repository.save_job(
        snapshot,
        CreativeAutomationEvent(
            event_id=event_id,
            job_id=request.request_id,
            event_type=f"status:{item.status}",
            payload={"status": item.status, "issue_count": len(item.issues)},
            created_at=timestamp,
        ),
    )


def _job_item_response(
    job: CreativeAutomationJobSnapshot,
) -> MarketingCreativeAutomationItemResponse:
    request = job.request
    return MarketingCreativeAutomationItemResponse(
        request_id=request.request_id,
        batch_id=job.batch_id,
        sku_id=request.sku_id,
        source_id=request.product_family.source_id if request.product_family else None,
        product_id=request.product_family.product_id if request.product_family else None,
        family_key=request.product_family.family_key if request.product_family else None,
        selection_scope=request.selection_scope.value,
        selected_variant_id=request.selected_variant_id,
        product_media_selection_mode=request.product_media_selection_mode.value,
        selected_product_media_ids=list(request.selected_product_media_ids),
        route=job.route,
        routing_reasons=list(job.routing_reasons),
        status=job.status,
        intake_run_id=job.intake_run_id,
        creative_job_id=job.creative_job_id,
        package_ref=job.package_ref,
        workflow_ref=job.workflow_ref,
        review_id=job.review_id,
        asset_count=job.asset_count,
        ads_draft_id=job.ads_draft_id,
        issues=[
            MarketingCreativeAutomationIssueResponse(
                code=issue.code,
                detail=issue.detail,
                component=issue.component,
            )
            for issue in job.issues
        ],
        image_count=request.output.image_output_count,
        video_count=request.output.video_output_count,
        image_provider_id=request.image_provider_id,
        image_model_id=request.image_model_id,
        image_resolution=request.image_resolution,
        image_quality=request.image_quality,
        image_generation_mode=request.image_generation_mode,
        video_duration_seconds=request.output.video_duration_seconds,
        video_model_id=request.video_model_id,
        video_resolution=request.video_resolution,
        video_generate_audio=request.video_generate_audio,
        video_duration_min_seconds=request.output.video_duration_min_seconds,
        video_duration_max_seconds=request.output.video_duration_max_seconds,
        video_scene_duration_max_seconds=request.output.video_scene_duration_max_seconds,
        audio_selected_by_agent=(
            request.output.video_output_count > 0
            and request.video_generate_audio is None
        ),
        execution_mode=request.execution_mode.value,
        provider_status=job.provider_status,
        output_profiles=[
            MarketingCreativeOutputProfileResponse(
                profile_id=profile.profile_id,
                media_kind=profile.media_kind,
                aspect_ratio=profile.aspect_ratio,
                file_format=profile.file_format,
                count=profile.count,
                image_size=profile.image_size,
            )
            for profile in request.output.output_profiles
        ],
    )


async def _persisted_item(
    run,
    providers: ManagedMediaProviderRegistry,
    states: IMarketingCreativeAutomationStateRepository,
    storage: MarketingCreativeAutomationStorage,
) -> MarketingCreativeAutomationItemResponse:
    context = run.context
    job_id = run.release.downstream_job_id if run.release else None
    route = ProductionRoute(context.production_route)
    stored_package = await storage.read_package(run.trigger.source_preview_id)
    if stored_package is not None:
        request = stored_package.request
    else:
        request = MarketingCreativeAutomationRequest(
            request_id=run.trigger.source_preview_id,
            brand=context.brand_id,
            sku_id=context.sku_id,
            market=context.market,
            platform=context.channel,
            objective=context.objective,
            output=CreativeOutputSelection(
                image_count=context.requested_image_count,
                video_count=context.requested_video_count,
                video_duration_seconds=context.requested_video_duration_seconds,
                video_duration_min_seconds=context.requested_video_duration_min_seconds,
                video_duration_max_seconds=context.requested_video_duration_max_seconds,
                video_scene_duration_max_seconds=context.requested_video_scene_duration_max_seconds,
                include_background_music=context.include_background_music,
                aspect_ratio=_aspect_ratio(context.output_width, context.output_height),
            ),
            sku_tier=SkuProductionTier.OVERFLOW,
            requested_by="recorded-request",
            execution_mode=CreativeAutomationExecutionMode(context.execution_mode),
            requested_at=run.trigger.requested_at,
        )
    package_ref = await storage.package_ref(request.request_id)
    workflow_state = await resolve_state_repository_call(states.get(request.request_id))
    return _item_response(
        request,
        context.production_route,
        list(context.routing_reasons),
        workflow_state.status.value
        if workflow_state is not None
        else _status(
            route,
            run.state.value,
            job_id,
            CreativeAutomationExecutionMode(context.execution_mode),
        ),
        run.run_id,
        job_id,
        package_ref,
        (states.reference(request.request_id) if workflow_state is not None else None),
        workflow_state,
        [
            MarketingCreativeAutomationIssueResponse(
                code=issue.code,
                detail=issue.detail,
                component=issue.component.value if issue.component else None,
            )
            for issue in run.issues
        ],
        _provider_status(request.output, providers),
    )


def _aspect_ratio(width: int, height: int) -> str:
    return {
        (1080, 1080): "1:1",
        (1080, 1350): "4:5",
        (1080, 1920): "9:16",
        (1920, 1080): "16:9",
        (1440, 1080): "4:3",
        (1080, 1440): "3:4",
        (1620, 1080): "3:2",
        (1080, 1620): "2:3",
    }.get((width, height), "9:16")


def _batch_id(idempotency_key: str | None) -> str:
    seed = idempotency_key or uuid4().hex
    return f"mca-batch-{hashlib.sha256(seed.encode()).hexdigest()[:20]}"


def _requests(
    payload: MarketingCreativeAutomationCreateRequest,
    batch_id: str,
    selections,
    settings,
    snapshots,
    context_compiler: CreativeSourceContextCompiler,
    reference_candidates: tuple[CreativeReferenceCandidate, ...] = (),
    reference_assignments: tuple[CreativeReferenceAssignment, ...] = (),
    logo_artifact_ref: str | None = None,
    logo_checksum_sha256: str | None = None,
    video_scene_duration_max_seconds: int | None = None,
    *,
    image_supports_multi_edit: bool = False,
) -> tuple[MarketingCreativeAutomationRequest, ...]:
    requests: list[MarketingCreativeAutomationRequest] = []
    for selection in selections:
        if isinstance(selection, str):
            requests.append(
                _request(
                    payload,
                    batch_id,
                    selection,
                    settings,
                    reference_candidates,
                    reference_assignments,
                    logo_artifact_ref,
                    logo_checksum_sha256,
                    video_scene_duration_max_seconds,
                    image_supports_multi_edit=image_supports_multi_edit,
                )
            )
            continue
        family_ref = ProductFamilyRef(
            source_id=selection.source_id,
            product_id=selection.product_id,
            family_key=selection.family_key,
        )
        try:
            family = context_compiler.product_family(
                snapshots,
                brand=payload.brand,
                product_family_ref=family_ref,
            )
        except CreativeContextUnavailableError:
            requests.append(
                _request(
                    payload,
                    batch_id,
                    selection,
                    settings,
                    reference_candidates,
                    reference_assignments,
                    logo_artifact_ref,
                    logo_checksum_sha256,
                    video_scene_duration_max_seconds,
                    image_supports_multi_edit=image_supports_multi_edit,
                )
            )
            continue
        if selection.selection_scope == "variant":
            selected_media_ids = _selected_product_media_ids(
                selection,
                family.media,
                variant_id=selection.variant_id,
            )
            requests.append(
                _request(
                    payload,
                    batch_id,
                    selection.model_copy(update={"selected_media_ids": selected_media_ids}),
                    settings,
                    reference_candidates,
                    reference_assignments,
                    logo_artifact_ref,
                    logo_checksum_sha256,
                    video_scene_duration_max_seconds,
                    image_supports_multi_edit=image_supports_multi_edit,
                )
            )
            continue
        if not family.variants:
            selected_media_ids = _selected_product_media_ids(selection, family.media)
            requests.append(
                _request(
                    payload,
                    batch_id,
                    selection.model_copy(update={"selected_media_ids": selected_media_ids}),
                    settings,
                    reference_candidates,
                    reference_assignments,
                    logo_artifact_ref,
                    logo_checksum_sha256,
                    video_scene_duration_max_seconds,
                    image_supports_multi_edit=image_supports_multi_edit,
                )
            )
            continue
        if selection.media_selection_mode == "manual":
            family_media_ids = {item.media_id for item in family.media}
            if not set(selection.selected_media_ids).issubset(family_media_ids):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Selected product images are not valid for this Product Family",
                )
        for variant in family.variants:
            variant_media_ids = _selected_product_media_ids(
                selection,
                family.media,
                variant_id=variant.variant_id,
                reject_ineligible_manual_media=False,
            )
            requests.append(
                _request(
                    payload,
                    batch_id,
                    selection.model_copy(
                        update={
                            "selection_scope": "variant",
                            "variant_id": variant.variant_id,
                            "selected_media_ids": variant_media_ids,
                        }
                    ),
                    settings,
                    reference_candidates,
                    reference_assignments,
                    logo_artifact_ref,
                    logo_checksum_sha256,
                    video_scene_duration_max_seconds,
                    image_supports_multi_edit=image_supports_multi_edit,
                )
            )
    request_ids = [request.request_id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Product Family and Variant selections overlap after Variant expansion",
        )
    if payload.variant_reference_assignments:
        requested_variants = {
            (item.source_id, item.product_id, item.variant_id)
            for item in payload.variant_reference_assignments
        }
        resolved_variants = {
            (
                request.product_family.source_id,
                request.product_family.product_id,
                request.selected_variant_id,
            )
            for request in requests
            if request.product_family is not None and request.selected_variant_id is not None
        }
        if requested_variants != resolved_variants:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide one explicit Research reference decision for every selected Variant",
            )
    return tuple(requests)


def _selected_product_media_ids(
    selection,
    media,
    *,
    variant_id: str | None = None,
    reject_ineligible_manual_media: bool = True,
) -> list[str]:
    eligible = [
        item
        for item in media
        if variant_id is None or not item.variant_ids or variant_id in item.variant_ids
    ]
    if selection.media_selection_mode == "manual":
        requested = set(selection.selected_media_ids)
        unknown = requested.difference(item.media_id for item in eligible)
        if unknown and reject_ineligible_manual_media:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selected product images are not valid for this Product variant",
            )
        eligible = [item for item in eligible if item.media_id in requested]
    elif selection.media_selection_mode == "featured" and eligible:
        eligible = [
            min(
                eligible,
                key=lambda item: (
                    0 if variant_id is not None and variant_id in item.variant_ids else 1,
                    item.position,
                    item.media_id,
                ),
            )
        ]
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Every selected Product variant requires at least one product image",
        )
    return [item.media_id for item in eligible]


def _request(
    payload: MarketingCreativeAutomationCreateRequest,
    batch_id: str,
    selection,
    settings,
    reference_candidates: tuple[CreativeReferenceCandidate, ...] = (),
    reference_assignments: tuple[CreativeReferenceAssignment, ...] = (),
    logo_artifact_ref: str | None = None,
    logo_checksum_sha256: str | None = None,
    video_scene_duration_max_seconds: int | None = None,
    *,
    image_supports_multi_edit: bool = False,
) -> MarketingCreativeAutomationRequest:
    if isinstance(selection, str):
        sku_id = selection
        product_family = None
        selection_scope = ProductSelectionScope.PRODUCT_FAMILY
        selected_variant_id = None
        identity = sku_id
    else:
        sku_id = selection.family_key
        product_family = ProductFamilyRef(
            source_id=selection.source_id,
            product_id=selection.product_id,
            family_key=selection.family_key,
        )
        selection_scope = ProductSelectionScope(selection.selection_scope)
        selected_variant_id = selection.variant_id
        identity = ":".join(
            (
                selection.source_id,
                selection.product_id,
                selection.selection_scope,
                selection.variant_id or "family",
            )
        )
    reference_selection_mode = CreativeReferenceSelectionMode(payload.reference_selection_mode)
    if payload.variant_reference_assignments:
        if isinstance(selection, str) or selected_variant_id is None or product_family is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Variant Research references require a resolved Shopify Variant",
            )
        variant_assignment = next(
            (
                item
                for item in payload.variant_reference_assignments
                if item.source_id == product_family.source_id
                and item.product_id == product_family.product_id
                and item.variant_id == selected_variant_id
            ),
            None,
        )
        if variant_assignment is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Every selected Variant requires an explicit Research reference decision",
            )
        variant_reference_ids = tuple(variant_assignment.reference_ids)
        reference_assignments = _creative_reference_assignments(
            payload,
            reference_ids=variant_reference_ids,
        )
        selected = set(variant_reference_ids)
        reference_candidates = tuple(
            item for item in reference_candidates if item.reference_id in selected
        )
        reference_selection_mode = (
            CreativeReferenceSelectionMode.HUMAN
            if variant_reference_ids
            else CreativeReferenceSelectionMode.NONE
        )
    request_key = hashlib.sha256(f"{batch_id}:{identity}".encode()).hexdigest()[:20]
    return MarketingCreativeAutomationRequest(
        request_id=f"mca-{request_key}",
        brand=payload.brand,
        sku_id=sku_id,
        market=settings.creative_automation_default_market,
        platform=payload.platform,
        objective=payload.objective,
        output=CreativeOutputSelection(
            image_count=payload.image_count,
            video_count=payload.video_count,
            video_duration_seconds=payload.video_duration_seconds,
            video_duration_min_seconds=(
                payload.video_duration_seconds
                or settings.creative_automation_video_duration_min_seconds
            ),
            video_duration_max_seconds=(
                payload.video_duration_seconds
                or settings.creative_automation_video_duration_max_seconds
            ),
            video_scene_duration_max_seconds=(
                video_scene_duration_max_seconds
                or settings.creative_automation_video_source_duration_max_seconds
            ),
            include_background_music=False,
            aspect_ratio=payload.aspect_ratio,
            profiles=tuple(
                CreativeOutputProfile(
                    profile_id=item.profile_id,
                    media_kind=item.media_kind,
                    aspect_ratio=item.aspect_ratio,
                    file_format=item.file_format,
                    count=item.count,
                    image_size=item.image_size,
                )
                for item in payload.output_profiles
            ),
        ),
        sku_tier=SkuProductionTier(payload.sku_tier),
        requested_by=payload.requested_by,
        execution_mode=CreativeAutomationExecutionMode(payload.execution_mode),
        agent_model_id=payload.agent_model_id,
        agent_reasoning_effort=payload.agent_reasoning_effort,
        image_provider_id=payload.image_provider_id,
        image_model_id=payload.image_model_id,
        image_resolution=payload.image_resolution,
        image_quality=payload.image_quality,
        image_background=payload.image_background,
        image_moderation=payload.image_moderation,
        image_output_compression=payload.image_output_compression,
        image_input_fidelity=payload.image_input_fidelity,
        image_generation_mode=(
            "multi_image_edit"
            if (
                image_supports_multi_edit
                and (
                    len(selection.selected_media_ids)
                    if not isinstance(selection, str)
                    else 1
                )
                + max(
                    (
                        len(item.reference_ids)
                        for item in reference_assignments
                        if item.output_key.startswith("image:")
                    ),
                    default=0,
                )
                + int(payload.include_logo)
                > 1
            )
            else "single_image_edit"
        ),
        video_model_id=payload.video_model_id,
        video_resolution=payload.video_resolution,
        video_generate_audio=payload.video_generate_audio,
        notes=payload.notes,
        high_brand_risk=payload.high_brand_risk,
        automation_override=payload.automation_override,
        requested_at=datetime.now(UTC),
        product_family=product_family,
        selection_scope=selection_scope,
        selected_variant_id=selected_variant_id,
        product_media_selection_mode=(
            ProductMediaSelectionMode(selection.media_selection_mode)
            if not isinstance(selection, str)
            else ProductMediaSelectionMode.AGENT
        ),
        selected_product_media_ids=(
            tuple(selection.selected_media_ids) if not isinstance(selection, str) else ()
        ),
        reference_candidates=reference_candidates,
        reference_assignments=reference_assignments,
        reference_selection_mode=reference_selection_mode,
        creative_set_strategy=CreativeSetStrategy(payload.creative_set_strategy),
        include_text=payload.include_text,
        headline=payload.headline,
        subtext=payload.subtext,
        cta_text=payload.cta_text,
        brand_instructions=payload.brand_instructions,
        include_logo=payload.include_logo,
        logo_asset_id=payload.logo_asset_id,
        logo_artifact_ref=logo_artifact_ref,
        logo_checksum_sha256=logo_checksum_sha256,
        human_persona=payload.human_persona,
        human_angle=payload.human_angle,
        human_hooks=tuple(payload.human_hooks),
        human_offer=payload.human_offer,
        human_claims=tuple(payload.human_claims),
    )


def _creative_reference_assignments(
    payload: MarketingCreativeAutomationCreateRequest,
    *,
    reference_ids: tuple[str, ...] | None = None,
) -> tuple[CreativeReferenceAssignment, ...]:
    if not payload.use_research_references:
        return ()
    if payload.output_reference_assignments:
        return tuple(
            CreativeReferenceAssignment(
                output_key=item.output_key,
                reference_ids=tuple(item.reference_ids),
            )
            for item in payload.output_reference_assignments
        )

    image_count = payload.image_count
    video_count = payload.video_count
    if payload.output_profiles:
        image_count = sum(
            item.count for item in payload.output_profiles if item.media_kind == "image"
        )
        video_count = sum(
            item.count for item in payload.output_profiles if item.media_kind == "video"
        )
    reference_ids = (
        reference_ids if reference_ids is not None else tuple(payload.selected_reference_ids)
    )
    if not reference_ids:
        return ()
    return tuple(
        CreativeReferenceAssignment(output_key=output_key, reference_ids=reference_ids)
        for output_key in (
            *(f"image:{index}" for index in range(1, image_count + 1)),
            *(f"video:{index}" for index in range(1, video_count + 1)),
        )
    )


def _research_reference_description(record) -> tuple[str, tuple[tuple[str, str], ...]]:
    profile = record.screening.profile if record.screening is not None else None
    if profile is None:
        fallback = " ".join(
            value.strip()
            for value in (record.title or "", record.advertiser or "", record.text[:1200])
            if value.strip()
        )
        return fallback or "Marketing-approved research reference image", ()

    sections = [
        profile.summary,
        f"Primary subject: {profile.primary_subject}" if profile.primary_subject else "",
        f"Content goal: {profile.content_goal}" if profile.content_goal else "",
        f"Project relevance: {profile.relevance_to_project}",
        f"Creative takeaways: {'; '.join(profile.creative_takeaways)}"
        if profile.creative_takeaways
        else "",
        f"Do not copy literally: {'; '.join(profile.do_not_copy)}" if profile.do_not_copy else "",
        f"Observed: {'; '.join(profile.observed_facts)}" if profile.observed_facts else "",
        f"Inferred: {'; '.join(profile.inferences)}" if profile.inferences else "",
        f"Composition: {'; '.join(profile.composition)}" if profile.composition else "",
        f"Setting: {'; '.join(profile.setting)}" if profile.setting else "",
        f"Camera and motion: {'; '.join(profile.camera_motion)}" if profile.camera_motion else "",
        f"Text treatment: {'; '.join(profile.text_treatment)}" if profile.text_treatment else "",
        f"Timeline: {'; '.join(profile.temporal_structure)}" if profile.temporal_structure else "",
        f"Audio: {'; '.join(profile.audio)}" if profile.audio else "",
        f"Applicability limits: {'; '.join(profile.applicability_constraints)}"
        if profile.applicability_constraints
        else "",
    ]
    labels = tuple(
        (kind, value)
        for kind, values in (
            ("reference_type", profile.reference_types),
            ("product_category", profile.product_categories),
            ("visual_style", profile.visual_style),
        )
        for value in values[:6]
        if value.strip()
    )
    return " ".join(section.strip() for section in sections if section.strip())[:4000], labels


async def _creative_reference_candidates(
    repository: ResearchCrawlRepository,
    brand: str,
    selected_reference_ids: tuple[str, ...] = (),
    media_assets: MediaAssetService | None = None,
) -> tuple[CreativeReferenceCandidate, ...]:
    if not selected_reference_ids:
        return ()
    research_reference_ids = tuple(
        reference_id
        for reference_id in selected_reference_ids
        if reference_id.startswith("research:")
    )
    uploaded_reference_ids = tuple(
        reference_id
        for reference_id in selected_reference_ids
        if reference_id.startswith("upload:")
    )
    if len(research_reference_ids) + len(uploaded_reference_ids) != len(selected_reference_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected Creative references use an unsupported reference type",
        )
    page = None
    if research_reference_ids:
        page = await repository.search_records(
            ResearchRecordQuery(
                brand_id=brand,
                review_status="approved",
                media_type="image",
                media_status="available",
                sort="last_seen_desc",
                page_size=100,
            )
        )
    candidates: list[CreativeReferenceCandidate] = []
    selected_research = set(research_reference_ids)
    if page is not None:
        for record in page.items:
            if record.review_status != "approved" or record.screening_status != "kept":
                continue
            description, reference_labels = _research_reference_description(record)
            for media in record.media_assets:
                if (
                    media.media_kind != "image"
                    or media.status != "available"
                    or media.artifact_ref is None
                    or media.sha256 is None
                ):
                    continue
                reference_id = f"research:{record.record_key}:{media.media_id}"
                if reference_id not in selected_research:
                    continue
                candidates.append(
                    CreativeReferenceCandidate(
                        reference_id=reference_id,
                        record_key=record.record_key,
                        media_id=media.media_id,
                        artifact_ref=media.artifact_ref,
                        checksum_sha256=media.sha256,
                        description=description or "Marketing-approved research reference image",
                        platform=record.platform,
                        source_url=record.source_url,
                        labels=reference_labels,
                    )
                )

    for reference_id in uploaded_reference_ids:
        if media_assets is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Uploaded Creative reference storage is unavailable",
            )
        asset_id = reference_id.removeprefix("upload:")
        try:
            asset = await media_assets.get(asset_id)
        except MediaAssetError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="One or more uploaded Creative references are unavailable",
            ) from error
        if (
            not asset_id
            or asset.origin != MediaAssetOrigin.UPLOAD
            or asset.media_kind != MediaAssetKind.IMAGE
            or asset.state != MediaAssetState.READY
            or asset.original_artifact_ref is None
            or asset.detected_content_type not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Uploaded Creative references must be ready PNG, JPEG or WebP images",
            )
        candidates.append(
            CreativeReferenceCandidate(
                reference_id=reference_id,
                record_key=f"human-upload:{asset.asset_id}",
                media_id=asset.asset_id,
                artifact_ref=asset.original_artifact_ref,
                checksum_sha256=asset.checksum_sha256,
                description=(
                    "Human-uploaded visual reference. Use only its transferable composition, "
                    "framing, lighting, palette, setting and creative pattern."
                ),
                platform="human_upload",
                labels=(("reference_type", "human_upload"),),
            )
        )
    found = {item.reference_id for item in candidates}
    selected = set(selected_reference_ids)
    if found != selected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "One or more selected Creative references are unavailable, invalid, "
                "or not Marketing-approved"
            ),
        )
    order = {reference_id: index for index, reference_id in enumerate(selected_reference_ids)}
    candidates.sort(key=lambda item: order[item.reference_id])
    return tuple(candidates)


def _intake_source_run_id(request_id: str) -> str:
    source_key = f"marketing_request:{request_id}"
    return f"creative-intake-{hashlib.sha256(source_key.encode()).hexdigest()[:20]}"


def _existing_conflict(
    existing,
    request: MarketingCreativeAutomationRequest,
    stored_package=None,
) -> str | None:
    if stored_package is not None:
        recorded_request = stored_package.request
        if replace(request, requested_at=recorded_request.requested_at) != recorded_request:
            return "This idempotency key was already used with a different Creative request."
        return None
    context = existing.context
    expected = (
        request.brand,
        request.sku_id,
        request.market,
        request.objective,
        request.platform,
        request.output.image_count,
        request.output.video_count,
        request.output.video_duration_seconds,
        request.output.video_duration_min_seconds,
        request.output.video_duration_max_seconds,
        request.output.video_scene_duration_max_seconds,
        request.output.include_background_music,
        request.execution_mode.value,
        decide_production_route(request).route.value,
        decide_production_route(request).requires_override,
    )
    recorded = (
        context.brand_id,
        context.sku_id,
        context.market,
        context.objective,
        context.channel,
        context.requested_image_count,
        context.requested_video_count,
        context.requested_video_duration_seconds,
        context.requested_video_duration_min_seconds,
        context.requested_video_duration_max_seconds,
        context.requested_video_scene_duration_max_seconds,
        context.include_background_music,
        context.execution_mode,
        context.production_route,
        context.routing_requires_override,
    )
    if recorded != expected:
        return "This idempotency key was already used with a different Creative request."
    return None


def _status(
    route: ProductionRoute,
    intake_state: str,
    job_id: str | None,
    execution_mode: CreativeAutomationExecutionMode,
) -> str:
    if intake_state != "released":
        return "needs_input"
    if job_id is None:
        return "preparing"
    if execution_mode == CreativeAutomationExecutionMode.BRIEF_ONLY:
        return "brief_ready"
    if route == ProductionRoute.MANUAL:
        return "manual_handoff_ready"
    if route == ProductionRoute.ASSISTED:
        return "assisted_handoff_ready"
    return "awaiting_generation_provider"


def _item_response(
    request: MarketingCreativeAutomationRequest,
    route: str,
    reasons: list[str],
    item_status: str,
    intake_run_id: str | None,
    creative_job_id: str | None,
    package_ref: str | None,
    workflow_ref: str | None,
    workflow_state: MarketingCreativeAutomationState | None,
    issues: list[MarketingCreativeAutomationIssueResponse],
    provider_status: str,
    batch_id: str | None = None,
) -> MarketingCreativeAutomationItemResponse:
    return MarketingCreativeAutomationItemResponse(
        request_id=request.request_id,
        batch_id=batch_id,
        sku_id=request.sku_id,
        source_id=request.product_family.source_id if request.product_family else None,
        product_id=request.product_family.product_id if request.product_family else None,
        family_key=request.product_family.family_key if request.product_family else None,
        selection_scope=request.selection_scope.value,
        selected_variant_id=request.selected_variant_id,
        product_media_selection_mode=request.product_media_selection_mode.value,
        selected_product_media_ids=list(request.selected_product_media_ids),
        route=route,
        routing_reasons=reasons,
        status=item_status,
        intake_run_id=intake_run_id,
        creative_job_id=creative_job_id,
        package_ref=package_ref,
        workflow_ref=workflow_ref,
        review_id=(
            workflow_state.final_review.review_id
            if workflow_state is not None and workflow_state.final_review is not None
            else None
        ),
        asset_count=(_successful_output_count(workflow_state) if workflow_state is not None else 0),
        ads_draft_id=(
            workflow_state.ads_draft.draft_id
            if workflow_state is not None and workflow_state.ads_draft is not None
            else None
        ),
        issues=issues,
        image_count=request.output.image_output_count,
        video_count=request.output.video_output_count,
        image_provider_id=request.image_provider_id,
        image_model_id=request.image_model_id,
        image_resolution=request.image_resolution,
        image_quality=request.image_quality,
        image_generation_mode=request.image_generation_mode,
        video_duration_seconds=request.output.video_duration_seconds,
        video_model_id=request.video_model_id,
        video_resolution=request.video_resolution,
        video_generate_audio=request.video_generate_audio,
        video_duration_min_seconds=request.output.video_duration_min_seconds,
        video_duration_max_seconds=request.output.video_duration_max_seconds,
        video_scene_duration_max_seconds=request.output.video_scene_duration_max_seconds,
        audio_selected_by_agent=(
            request.output.video_output_count > 0
            and request.video_generate_audio is None
        ),
        execution_mode=request.execution_mode.value,
        provider_status=provider_status,
        output_profiles=[
            MarketingCreativeOutputProfileResponse(
                profile_id=profile.profile_id,
                media_kind=profile.media_kind,
                aspect_ratio=profile.aspect_ratio,
                file_format=profile.file_format,
                count=profile.count,
                image_size=profile.image_size,
            )
            for profile in request.output.output_profiles
        ],
    )


def _maximum_assigned_references(
    assignments: tuple[CreativeReferenceAssignment, ...],
    media_kind: str,
) -> int:
    prefix = f"{media_kind}:"
    return max(
        (len(item.reference_ids) for item in assignments if item.output_key.startswith(prefix)),
        default=0,
    )


def _apply_provider_defaults(
    payload: MarketingCreativeAutomationCreateRequest,
    providers: ManagedMediaProviderRegistry,
) -> None:
    """Fill omitted media choices without rejecting provider-owned capabilities."""
    if payload.execution_mode == "brief_only":
        return
    has_image_outputs = payload.image_count > 0 or any(
        item.media_kind == "image" and item.count > 0 for item in payload.output_profiles
    )
    image_descriptor = providers.image_descriptor(payload.image_provider_id)
    if has_image_outputs and image_descriptor is not None:
        payload.image_provider_id = payload.image_provider_id or image_descriptor.provider_id
        selected_image_model = next(
            (
                item
                for item in image_descriptor.image_models
                if item.model_id == payload.image_model_id
            ),
            None,
        )
        if payload.image_model_id is None and image_descriptor.image_models:
            selected_image_model = image_descriptor.image_models[0]
            payload.image_model_id = selected_image_model.model_id
        if selected_image_model is not None:
            if payload.image_resolution is None and selected_image_model.supported_resolutions:
                payload.image_resolution = selected_image_model.supported_resolutions[0]
            if payload.image_quality is None and selected_image_model.supported_qualities:
                payload.image_quality = (
                    "auto"
                    if "auto" in selected_image_model.supported_qualities
                    else selected_image_model.supported_qualities[0]
                )
            if selected_image_model.fidelity_mode == "exact_source_transform":
                payload.image_quality = None

    has_video_outputs = payload.video_count > 0 or any(
        item.media_kind == "video" and item.count > 0 for item in payload.output_profiles
    )
    video_descriptor = providers.video_descriptor()
    if has_video_outputs and video_descriptor is not None:
        selected_video_model = next(
            (
                item
                for item in video_descriptor.video_models
                if item.model_id == payload.video_model_id
            ),
            None,
        )
        if payload.video_model_id is None and video_descriptor.video_models:
            selected_video_model = video_descriptor.video_models[0]
            payload.video_model_id = selected_video_model.model_id
        if selected_video_model is not None:
            if payload.video_resolution is None and selected_video_model.supported_resolutions:
                payload.video_resolution = selected_video_model.supported_resolutions[0]
            if payload.video_generate_audio is None:
                payload.video_generate_audio = False


def _image_supports_multi_edit(
    payload: MarketingCreativeAutomationCreateRequest,
    providers: ManagedMediaProviderRegistry,
) -> bool:
    descriptor = providers.image_descriptor(payload.image_provider_id)
    if descriptor is None:
        return False
    selected_model = next(
        (item for item in descriptor.image_models if item.model_id == payload.image_model_id),
        None,
    )
    return bool(
        selected_model is not None
        and "multi_image_edit" in selected_model.supported_modes
    )


def _validate_exact_source_output_profiles(
    payload: MarketingCreativeAutomationCreateRequest,
    media_kind: Literal["image", "video"],
) -> None:
    profiles = [
        item for item in payload.output_profiles if item.media_kind == media_kind and item.count > 0
    ]
    if not profiles:
        count = payload.image_count if media_kind == "image" else payload.video_count
        if count <= 1:
            return
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Exact Shopify source transforms allow one {media_kind} per aspect ratio "
                "because repeated transforms would be identical"
            ),
        )
    aspect_ratios = [item.aspect_ratio for item in profiles for _ in range(item.count)]
    if len(aspect_ratios) == len(set(aspect_ratios)):
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Exact Shopify source transforms allow one {media_kind} per aspect ratio "
            "because repeated transforms would be identical"
        ),
    )


def _targets_are_exact_source_transforms(
    state: MarketingCreativeAutomationState,
    target_asset_version_ids: tuple[str, ...],
) -> bool:
    assets = (
        tuple((asset.asset_version_id, asset) for asset in state.final_review.assets)
        if state.final_review is not None
        else tuple(
            (record.asset_version_id, record.selected_artifact)
            for record in state.production_assets
            if record.selected_artifact is not None
        )
    )
    if target_asset_version_ids:
        selected = tuple(
            asset
            for asset_version_id, asset in assets
            if asset_version_id in target_asset_version_ids
        )
    else:
        selected = tuple(asset for _, asset in assets)
    return bool(selected) and all(
        asset.fidelity_mode == "exact_source_transform" for asset in selected
    )


def _validate_provider_profiles(
    payload: MarketingCreativeAutomationCreateRequest,
    providers: ManagedMediaProviderRegistry,
) -> None:
    if payload.execution_mode == "brief_only":
        return
    reference_assignments = _creative_reference_assignments(payload)
    image_descriptor = providers.image_descriptor(payload.image_provider_id)
    has_image_outputs = payload.image_count > 0 or any(
        item.media_kind == "image" and item.count > 0 for item in payload.output_profiles
    )
    selected_image_model = None
    if (
        has_image_outputs
        and image_descriptor is not None
        and image_descriptor.fidelity_mode == "exact_source_transform"
        and providers.image_status(payload.image_provider_id) == "ready"
        and image_descriptor.image_models
    ):
        selected_default = image_descriptor.image_models[0]
        payload.image_provider_id = payload.image_provider_id or image_descriptor.provider_id
        payload.image_model_id = payload.image_model_id or selected_default.model_id
        payload.image_resolution = (
            payload.image_resolution or selected_default.supported_resolutions[0]
        )
        payload.image_quality = None
        _validate_exact_source_output_profiles(payload, "image")
    if has_image_outputs and payload.image_provider_id and image_descriptor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected image provider is not configured",
        )
    if image_descriptor is not None and not image_descriptor.selected_sku_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected image provider is not enabled for exact-SKU Creative production",
        )
    if (
        has_image_outputs
        and providers.image_status(payload.image_provider_id) == "ready"
        and image_descriptor is not None
        and image_descriptor.image_models
    ):
        if not payload.image_model_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Select an image model for generated image outputs",
            )
        selected_image_model = next(
            (
                item
                for item in image_descriptor.image_models
                if item.model_id == payload.image_model_id
            ),
            None,
        )
        if selected_image_model is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Configured image provider does not support the selected model",
            )
        if payload.image_resolution not in selected_image_model.supported_resolutions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selected image model does not support the requested resolution",
            )
        if selected_image_model.supported_qualities:
            quality_valid = payload.image_quality in selected_image_model.supported_qualities
        else:
            quality_valid = payload.image_quality is None
        if not quality_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selected image model does not support the requested quality",
            )
        if (
            payload.image_background is not None
            and payload.image_background not in selected_image_model.supported_backgrounds
        ):
            raise HTTPException(
                status_code=422,
                detail="Selected image model does not support the requested background",
            )
        if (
            payload.image_moderation is not None
            and payload.image_moderation not in selected_image_model.supported_moderation
        ):
            raise HTTPException(
                status_code=422,
                detail="Selected image model does not support the requested moderation",
            )
        if (
            payload.image_output_compression is not None
            and not selected_image_model.supports_output_compression
        ):
            raise HTTPException(
                status_code=422, detail="Selected image model does not support output compression"
            )
        if (
            payload.image_input_fidelity is not None
            and payload.image_input_fidelity
            not in selected_image_model.supported_input_fidelities
        ):
            raise HTTPException(
                status_code=422,
                detail="Selected image model does not support the requested input fidelity",
            )
        if payload.include_text and not selected_image_model.supports_text_rendering:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selected image model does not support generated text",
            )
        if payload.include_logo and not selected_image_model.supports_logo_input:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selected image model does not support logo input",
            )
    if (
        has_image_outputs
        and providers.image_status(payload.image_provider_id) == "ready"
        and image_descriptor is not None
        and 1
        + _maximum_assigned_references(reference_assignments, "image")
        + int(payload.include_logo)
        > (
            selected_image_model.max_reference_images
            if selected_image_model is not None
            else image_descriptor.max_reference_images
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Selected product, research and logo images exceed the configured image "
                "model input limit"
            ),
        )
    requested_profiles = [
        (item.media_kind, item.aspect_ratio, item.file_format) for item in payload.output_profiles
    ]
    if not requested_profiles:
        if payload.image_count:
            requested_profiles.append(("image", payload.aspect_ratio, "png"))
        if payload.video_count:
            requested_profiles.append(("video", payload.aspect_ratio, "mp4"))
    if payload.image_output_compression is not None and any(
        media_kind == "image" and file_format == "png"
        for media_kind, _aspect_ratio, file_format in requested_profiles
    ):
        raise HTTPException(status_code=422, detail="Output compression requires JPEG or WebP")
    for media_kind, aspect_ratio, file_format in requested_profiles:
        descriptor = image_descriptor if media_kind == "image" else providers.video_descriptor()
        status_value = (
            providers.image_status(payload.image_provider_id)
            if media_kind == "image"
            else providers.video_status()
        )
        if status_value != "ready" or descriptor is None:
            continue
        if aspect_ratio not in descriptor.supported_aspect_ratios:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Configured {media_kind} model does not support {aspect_ratio}",
            )
        if media_kind == "image" and file_format not in descriptor.supported_image_formats:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Configured image model does not support {file_format}",
            )
        if media_kind == "image" and selected_image_model is not None:
            if aspect_ratio not in selected_image_model.supported_aspect_ratios:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Selected image model does not support every requested aspect ratio",
                )
            if file_format not in selected_image_model.supported_formats:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Selected image model does not support every requested format",
                )
    for profile in payload.output_profiles:
        if profile.media_kind != "image":
            continue
        if selected_image_model is not None and profile.image_size is not None:
            if profile.image_size not in selected_image_model.supported_image_sizes:
                raise HTTPException(
                    status_code=422,
                    detail="Selected image model does not support the requested size",
                )
            width, height = map(int, profile.image_size.split("x"))
            ratio_width, ratio_height = map(int, profile.aspect_ratio.split(":"))
            if width * ratio_height != height * ratio_width:
                raise HTTPException(
                    status_code=422, detail="Image size does not match the output aspect ratio"
                )
        if payload.image_background == "transparent" and profile.file_format == "jpeg":
            raise HTTPException(
                status_code=422, detail="JPEG does not support transparent backgrounds"
            )
        if payload.image_output_compression is not None and profile.file_format == "png":
            raise HTTPException(status_code=422, detail="Output compression requires JPEG or WebP")
    has_video_outputs = payload.video_count > 0 or any(
        item.media_kind == "video" and item.count > 0 for item in payload.output_profiles
    )
    video_descriptor = providers.video_descriptor()
    if (
        has_video_outputs
        and video_descriptor is not None
        and video_descriptor.fidelity_mode == "exact_source_transform"
        and providers.video_status() == "ready"
        and video_descriptor.video_models
    ):
        selected_default = video_descriptor.video_models[0]
        payload.video_model_id = payload.video_model_id or selected_default.model_id
        payload.video_resolution = (
            payload.video_resolution or selected_default.supported_resolutions[0]
        )
        payload.video_generate_audio = False
        _validate_exact_source_output_profiles(payload, "video")
    if not has_video_outputs or providers.video_status() != "ready" or video_descriptor is None:
        return
    if not video_descriptor.selected_sku_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected video provider is not enabled for exact-SKU Creative production",
        )
    if not video_descriptor.video_models:
        return
    if not payload.video_model_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a video model for generated video outputs",
        )
    selected_model = next(
        (item for item in video_descriptor.video_models if item.model_id == payload.video_model_id),
        None,
    )
    if selected_model is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Configured video provider does not support the selected model",
        )
    if (
        _minimum_video_product_images(selected_model, payload.video_resolution)
        + _maximum_assigned_references(reference_assignments, "video")
        > selected_model.max_reference_images
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected product and research images exceed the video model input limit",
        )
    if payload.video_generate_audio and not (
        selected_model.supports_native_voice or selected_model.supports_native_music
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected video model produces silent clips only",
        )
    if payload.video_resolution not in selected_model.supported_resolutions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected video model does not support the requested resolution",
        )
    if (
        payload.video_resolution not in selected_model.reference_to_video_resolutions
        and _maximum_assigned_references(reference_assignments, "video")
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Research references require a reference-to-video resolution",
        )
    requested_video_ratios = {ratio for kind, ratio, _ in requested_profiles if kind == "video"}
    if not requested_video_ratios.issubset(set(selected_model.supported_aspect_ratios)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected video model does not support every requested aspect ratio",
        )


def _validate_request_source_limits(
    requests: tuple[MarketingCreativeAutomationRequest, ...],
    providers: ManagedMediaProviderRegistry,
) -> None:
    video_descriptor = providers.video_descriptor()
    for request in requests:
        if request.execution_mode != CreativeAutomationExecutionMode.GENERATE_ONCE:
            continue
        image_reference_count = _maximum_assigned_references(
            request.reference_assignments,
            "image",
        )
        video_reference_count = _maximum_assigned_references(
            request.reference_assignments,
            "video",
        )
        image_descriptor = providers.image_descriptor(request.image_provider_id)
        selected_image_model = (
            next(
                (
                    item
                    for item in image_descriptor.image_models
                    if item.model_id == request.image_model_id
                ),
                None,
            )
            if image_descriptor is not None
            else None
        )
        image_limit = (
            selected_image_model.max_reference_images
            if selected_image_model is not None
            else image_descriptor.max_reference_images
            if image_descriptor is not None
            else None
        )
        minimum_image_sources = 1 + image_reference_count + int(request.include_logo)
        if (
            request.output.image_output_count > 0
            and providers.image_status(request.image_provider_id) == "ready"
            and image_limit is not None
            and minimum_image_sources > image_limit
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Selected research and logo images leave no input slot for the "
                    "Shopify product image"
                ),
            )
        if request.output.image_output_count > 0 and selected_image_model is not None:
            # The request mode is derived after the exact Shopify media has been
            # resolved. Agent-selected complementary Product views can therefore
            # require multi-image edit even without a Research reference or logo.
            mode = request.image_generation_mode or (
                "multi_image_edit" if minimum_image_sources > 1 else "single_image_edit"
            )
            if (
                mode not in selected_image_model.supported_modes
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Selected image model does not support the required edit mode",
                )
        if (
            request.output.video_output_count == 0
            or providers.video_status() != "ready"
            or video_descriptor is None
        ):
            continue
        selected_video_model = next(
            (
                item
                for item in video_descriptor.video_models
                if item.model_id == request.video_model_id
            ),
            None,
        )
        if (
            selected_video_model is not None
            and _minimum_video_product_images(
                selected_video_model, request.video_resolution
            )
            + video_reference_count
            > selected_video_model.max_reference_images
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Selected research images leave no input slot for the Shopify "
                    "product image in the video model"
                ),
            )
        if (
            selected_video_model is not None
            and request.video_resolution
            not in selected_video_model.reference_to_video_resolutions
            and video_reference_count
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Research references require a reference-to-video resolution",
            )


def _minimum_video_product_images(model, resolution: str | None) -> int:
    if resolution in model.reference_to_video_resolutions:
        return min(2, model.max_product_images)
    return 1


def _video_scene_duration_max_seconds(payload, providers, settings) -> int:
    descriptor = providers.video_descriptor()
    if descriptor is not None and payload.video_model_id:
        selected_model = next(
            (item for item in descriptor.video_models if item.model_id == payload.video_model_id),
            None,
        )
        if selected_model is not None:
            return max(selected_model.supported_generation_durations_seconds)
    return settings.creative_automation_video_source_duration_max_seconds


def _workflow_entity_id(prefix: str, request_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{request_id}:{idempotency_key}".encode()).hexdigest()[:20]
    return f"{prefix}-{digest}"


async def _load_creative_knowledge_versions(
    knowledge: CreativeKnowledgeService,
    version_refs: tuple[str, ...],
) -> tuple[CreativeKnowledge, ...]:
    """Load the exact SecondBrain versions pinned by an earlier attempt."""

    resolved: list[CreativeKnowledge] = []
    for version_ref in version_refs:
        knowledge_id, separator, raw_version = version_ref.rpartition("@")
        if not separator or not knowledge_id or not raw_version.isdigit():
            raise ValueError(f"Invalid pinned Creative knowledge reference: {version_ref}")
        item = await knowledge.repository.get(knowledge_id, int(raw_version))
        if item is None or item.version_ref != version_ref:
            raise ValueError(f"Pinned Creative knowledge version is unavailable: {version_ref}")
        resolved.append(item)
    return tuple(resolved)


def _creative_knowledge_memory(
    items: tuple[CreativeKnowledge, ...],
) -> tuple[ApprovedCreativeMemory, ...]:
    return tuple(
        ApprovedCreativeMemory(
            memory_id=item.version_ref,
            summary=f"{item.title}: {item.content}",
            supported_facts=(item.content,),
            non_conclusions=(
                item.non_conclusions or ("Apply only within the pinned knowledge scope.",)
            ),
            evidence_refs=item.evidence_refs or item.source_refs,
            knowledge_type=item.knowledge_type.value,
            authority=item.authority.value,
            scope=tuple(
                (name, value) for name, value in item.scope.__dict__.items() if value is not None
            ),
        )
        for item in items
    )


def _memory_sources(
    memory: tuple[ApprovedCreativeMemory, ...],
) -> tuple[SourceDocument, ...]:
    return tuple(
        SourceDocument(
            source_id=item.memory_id,
            data_version=item.memory_id,
            content=(
                f"{item.summary} Evidence: {', '.join(item.evidence_refs)}."
            ),
            category="knowledge" if item.knowledge_type != "lesson" else "history",
            knowledge_type=item.knowledge_type,
            knowledge_authority=item.authority,
            knowledge_scope=item.scope,
            non_conclusions=item.non_conclusions,
        )
        for item in memory
    )


async def _resolve_creative_knowledge(
    knowledge: CreativeKnowledgeService,
    scope: KnowledgeScope,
    *,
    stage: KnowledgeStage,
    include_image: bool,
    include_video: bool,
) -> tuple[CreativeKnowledge, ...]:
    """Resolve shared and media-specific records without duplicating versions."""

    scopes = [scope]
    if include_image:
        scopes.append(replace(scope, asset_type="image"))
    if include_video:
        scopes.append(replace(scope, asset_type="video"))
    resolved: dict[str, CreativeKnowledge] = {}
    for candidate_scope in scopes:
        for item in await knowledge.resolve(candidate_scope, stage=stage):
            resolved[item.version_ref] = item
    return tuple(resolved.values())


async def _record_human_feedback(
    knowledge: CreativeKnowledgeService,
    package: ProductionReadyCreativePackage,
    state: MarketingCreativeAutomationState,
    *,
    feedback_id: str,
    title: str,
    content: str,
    reviewer: str,
    asset_version_ids: tuple[str, ...],
    source_refs: tuple[str, ...],
    acceptance: bool,
) -> None:
    media_kind = _single_media_kind(state, asset_version_ids)
    await knowledge.record_feedback(
        feedback_id=feedback_id,
        title=title,
        content=content,
        scope=_knowledge_scope_for_package(package, asset_type=media_kind),
        reviewer=reviewer,
        source_refs=source_refs,
        non_conclusions=(
            (
                "Human approval confirms this exact reviewed output, not Ads performance or a "
                "reusable Brand-wide rule."
            )
            if acceptance
            else (
                "Apply this feedback only within its pinned product and media scope; it is not a "
                "reusable Brand-wide rule."
            ),
        ),
    )


def _knowledge_scope_for_package(
    package: ProductionReadyCreativePackage,
    *,
    asset_type: str | None = None,
) -> KnowledgeScope:
    family = package.sku.product_family
    return KnowledgeScope(
        niche_id=(
            product_niche(product_type=family.product_type, title=family.title)
            if family is not None
            else None
        ),
        brand_id=package.request.brand,
        product_archetype=(
            product_archetype(product_type=family.product_type, title=family.title)
            if family is not None
            else None
        ),
        product_family_id=(
            package.request.product_family.product_id
            if package.request.product_family is not None
            else None
        ),
        variant_id=package.request.selected_variant_id,
        platform=package.request.platform,
        market=package.request.market,
        asset_type=asset_type,
        task_type="sku_to_output",
    )


def _single_media_kind(
    state: MarketingCreativeAutomationState,
    asset_version_ids: tuple[str, ...],
) -> str | None:
    selected_ids = set(asset_version_ids)
    records = ((asset.asset_version_id, asset.media_kind) for asset in state.production_assets)
    kinds = {
        media_kind
        for asset_version_id, media_kind in records
        if not selected_ids or asset_version_id in selected_ids
    }
    return next(iter(kinds)) if len(kinds) == 1 else None


def _artifact_web_url(artifact_ref: str) -> str | None:
    if artifact_ref.startswith(("http://", "https://")):
        return artifact_ref
    if artifact_ref.startswith("artifact:"):
        artifact_id = artifact_ref.removeprefix("artifact:")
        return f"/api/v1/artifacts/{quote(artifact_id, safe='')}/content"
    return f"/artifacts/{quote(artifact_ref.replace(chr(92), '/'), safe='/')}"


def _state_response(
    state: MarketingCreativeAutomationState,
    ads_providers: AdsActivationProviderRegistry | None = None,
    *,
    issues: list[MarketingCreativeAutomationIssueResponse] | None = None,
    trace: MarketingCreativeAutomationTraceResponse | None = None,
) -> MarketingCreativeAutomationDetailResponse:
    review = state.final_review
    decision = state.review_decision
    draft = state.ads_draft
    return MarketingCreativeAutomationDetailResponse(
        request_id=state.request_id,
        package_id=state.package_id,
        package_ref=state.package_ref,
        route=state.route,
        status=state.status.value,
        issues=issues or [],
        final_review=(
            MarketingCreativeFinalReviewResponse(
                review_id=review.review_id,
                direction_summary=review.direction_summary,
                review_checklist=list(review.review_checklist),
                assets=[
                    MarketingCreativeAssetResponse(
                        asset_version_id=asset.asset_version_id,
                        media_kind=asset.media_kind,
                        artifact_ref=asset.artifact_ref,
                        artifact_web_url=_artifact_web_url(asset.artifact_ref),
                        checksum_sha256=asset.checksum_sha256,
                        content_type=asset.content_type,
                        qa_summary=asset.qa_summary,
                        revision_count=asset.revision_count,
                        provider_id=asset.provider_id,
                        cost=asset.cost,
                        fidelity_mode=asset.fidelity_mode,
                        product_source_checksum_sha256=asset.product_source_checksum_sha256,
                    )
                    for asset in review.assets
                ],
                image_count=review.image_count,
                video_count=review.video_count,
                created_at=review.created_at,
            )
            if review is not None
            else None
        ),
        production_versions=[
            MarketingCreativeProductionVersionResponse(
                asset_version_id=record.asset_version_id,
                parent_asset_version_id=record.parent_asset_version_id,
                generation_request_id=record.generation_request_id,
                revision_feedback=record.revision_feedback,
                media_kind=record.media_kind,
                variation_key=record.variation_key,
                success=record.success,
                outcome=record.outcome,
                attempt_count=len(record.attempts),
                total_cost=record.total_cost,
                artifact_ref=(artifact.artifact_ref if artifact is not None else None),
                artifact_web_url=(
                    _artifact_web_url(artifact.artifact_ref) if artifact is not None else None
                ),
                checksum_sha256=(artifact.checksum_sha256 if artifact is not None else None),
                content_type=(artifact.content_type if artifact is not None else None),
                provider_id=(artifact.provider_id if artifact is not None else None),
                actual_width=(artifact.width if artifact is not None else None),
                actual_height=(artifact.height if artifact is not None else None),
                actual_duration_seconds=(
                    artifact.duration_seconds if artifact is not None else None
                ),
                has_audio_stream=(artifact.has_audio_stream if artifact is not None else None),
                fidelity_mode=(artifact.fidelity_mode if artifact is not None else None),
                product_source_checksum_sha256=(
                    artifact.product_source_checksum_sha256 if artifact is not None else None
                ),
                technical_check_summary=(
                    record.attempts[-1].evaluation.summary if record.attempts else None
                ),
                intermediate_artifacts=[
                    MarketingCreativeIntermediateArtifactResponse(
                        artifact_ref=scene.artifact_ref,
                        artifact_web_url=_artifact_web_url(scene.artifact_ref),
                        checksum_sha256=scene.checksum_sha256,
                        content_type=scene.content_type,
                        provider_id=scene.provider_id,
                        duration_seconds=scene.duration_seconds,
                        cost=scene.cost,
                        fidelity_mode=scene.fidelity_mode,
                        product_source_checksum_sha256=scene.product_source_checksum_sha256,
                    )
                    for scene in record.intermediate_artifacts
                ],
            )
            for record in state.production_assets
            for artifact in [
                record.selected_artifact
                or (record.attempts[-1].artifact if record.attempts else None)
            ]
        ],
        review_decision=(
            MarketingCreativeReviewDecisionResponse(
                decision_id=decision.decision_id,
                review_id=decision.review_id,
                decision=decision.decision,
                asset_version_ids=list(decision.asset_version_ids),
                asset_checksums=list(decision.asset_checksums),
                reviewer_alias=decision.reviewer_alias,
                reason=decision.reason,
                decided_at=decision.decided_at,
                key_visual_asset_version_id=decision.key_visual_asset_version_id,
            )
            if decision is not None
            else None
        ),
        manual_takeover=(
            MarketingCreativeManualTakeoverResponse(
                takeover_id=state.manual_takeover.takeover_id,
                requested_by=state.manual_takeover.requested_by,
                reason=state.manual_takeover.reason,
                requested_at=state.manual_takeover.requested_at,
            )
            if state.manual_takeover is not None
            else None
        ),
        ads_draft=(
            MarketingCreativeAdsDraftResponse(
                draft_id=draft.draft_id,
                destination_ref=draft.destination_ref,
                daily_budget=draft.daily_budget,
                currency=draft.currency,
                draft_fingerprint=draft.draft_fingerprint,
                status=draft.status.value,
                asset_version_ids=[asset.asset_version_id for asset in draft.assets],
                asset_checksums=[asset.checksum_sha256 for asset in draft.assets],
                created_at=draft.created_at,
            )
            if draft is not None
            else None
        ),
        ads_approved=state.ads_approval is not None,
        ads_provider_status=(
            ads_providers.status(draft.platform)
            if ads_providers is not None and draft is not None
            else "not_configured"
        ),
        ads_activation=(
            MarketingCreativeAdsActivationResponse(
                platform=state.ads_receipt.platform,
                account_id=state.ads_receipt.account_id,
                campaign_id=state.ads_receipt.campaign_id,
                ad_ids=list(state.ads_receipt.ad_ids),
                activated_at=state.ads_receipt.activated_at,
            )
            if state.ads_receipt is not None
            else None
        ),
        production_attempt_count=sum(len(asset.attempts) for asset in state.production_assets),
        generation_request_count=len(state.generation_requests),
        generation_requests=[
            MarketingCreativeGenerationRequestResponse(
                generation_request_id=item.generation_request_id,
                requested_by=item.requested_by,
                reason=item.reason,
                requested_at=item.requested_at,
                target_asset_version_ids=list(item.target_asset_version_ids),
                knowledge_refs=list(item.knowledge_refs),
            )
            for item in state.generation_requests
        ],
        production_cost=sum(
            (asset.total_cost for asset in state.production_assets),
            start=Decimal("0"),
        ),
        production_error_code=state.production_error_code,
        production_error_detail=state.production_error_detail,
        created_at=state.created_at,
        updated_at=state.updated_at,
        trace=trace,
    )


def _trace_response(
    state: MarketingCreativeAutomationState,
    job: CreativeAutomationJobSnapshot | None,
    events: list[CreativeAutomationEvent],
    package: ProductionReadyCreativePackage | None,
) -> MarketingCreativeAutomationTraceResponse | None:
    if job is None and package is None:
        return None
    plan = package.automation_plan if package is not None else None
    return MarketingCreativeAutomationTraceResponse(
        request=asdict(package.request if package is not None else job.request),
        source_refs=(
            [f"{item.source_id}:{item.data_version}" for item in package.context.evidence]
            if package is not None
            else []
        ),
        memory_refs=list(
            dict.fromkeys(
                (
                    *(plan.memory_refs if plan is not None else ()),
                    *(package.knowledge_refs if package is not None else ()),
                )
            )
        ),
        knowledge_refs_by_stage=(
            {
                assignment.stage: list(assignment.version_refs)
                for assignment in package.knowledge_assignments
            }
            if package is not None
            else {}
        ),
        selected_idea=(
            asdict(package.selected_idea)
            if package is not None and package.selected_idea is not None
            else None
        ),
        prepared_brief=(
            asdict(package.brief) if package is not None and package.brief is not None else None
        ),
        strategy=(
            asdict(package.strategy)
            if package is not None and package.strategy is not None
            else None
        ),
        plan=(
            MarketingCreativeAutomationPlanResponse(
                plan_id=plan.plan_id,
                readiness=plan.readiness.value,
                strategy_summary=plan.strategy_summary,
                rationale=plan.rationale,
                evidence_refs=list(plan.evidence_refs),
                image_plans=[asdict(item) for item in plan.image_plans],
                video_plan=(
                    asdict(plan.resolved_video_plans[0]) if plan.resolved_video_plans else None
                ),
                video_plans=[asdict(item) for item in plan.resolved_video_plans],
                missing_context=list(plan.missing_context),
                uncertainties=list(plan.uncertainties),
                memory_refs=list(plan.memory_refs),
                model_profile=plan.model_profile,
                prompt_version=plan.prompt_version,
            )
            if plan is not None
            else None
        ),
        events=[
            MarketingCreativeAutomationEventResponse(
                event_id=event.event_id,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in events
        ],
        input_tokens=job.input_tokens if job is not None else None,
        output_tokens=job.output_tokens if job is not None else None,
        total_cost=job.total_cost if job is not None else Decimal("0"),
        technical_checks=(
            [asset.qa_summary for asset in state.final_review.assets]
            if state.final_review is not None
            else []
        ),
        latency=_latency_response(events),
    )


def _latency_response(
    events: list[CreativeAutomationEvent],
) -> MarketingCreativeAutomationLatencyResponse:
    steps: list[MarketingCreativeAutomationLatencyStepResponse] = []
    total_duration_ms: float | None = None
    total_outcome: Literal["succeeded", "failed"] | None = None
    for event in events:
        if not event.event_type.startswith("latency:"):
            continue
        payload = event.payload
        try:
            item = MarketingCreativeAutomationLatencyStepResponse.model_validate(payload)
        except ValueError:
            logger.warning(
                "Ignoring malformed Creative latency event event_id={}",
                event.event_id,
            )
            continue
        if item.step == "total":
            total_duration_ms = item.duration_ms
            total_outcome = item.outcome
        else:
            steps.append(item)
    return MarketingCreativeAutomationLatencyResponse(
        total_duration_ms=total_duration_ms,
        total_outcome=total_outcome,
        is_final=total_duration_ms is not None,
        steps=steps,
    )


def _configured_model_api_key(settings, api_key_env: str | None) -> str | None:
    credential = getattr(settings, "credential", None)
    if callable(credential):
        return credential(api_key_env)
    if api_key_env == "ROUTER_API_KEY":
        return settings.router_api_key
    if api_key_env == "GEMINI_API_KEY":
        return settings.gemini_api_key
    if api_key_env is None:
        return None
    raise ValueError(f"Unsupported model credential environment variable: {api_key_env}")


async def _existing_or_initialize_state(
    repository: IMarketingCreativeAutomationStateRepository,
    request: MarketingCreativeAutomationRequest,
    route: str,
    item_status: str,
    package_ref: str | None,
) -> tuple[MarketingCreativeAutomationState, str]:
    existing = await resolve_state_repository_call(repository.get(request.request_id))
    if existing is not None:
        return existing, repository.reference(request.request_id)
    if package_ref is None:
        raise RuntimeError("Production-ready Creative package artifact is missing")
    state = initialize_automation_state(
        request_id=request.request_id,
        package_id=f"creative-package:{request.request_id}",
        package_ref=package_ref,
        route=route,
        status=item_status,
    )
    reference = await resolve_state_repository_call(repository.save(state))
    return state, reference


def _provider_status(
    output: CreativeOutputSelection,
    providers: ManagedMediaProviderRegistry,
) -> str:
    if output.video_output_count == 0 and output.image_output_count == 0:
        return "not_required"
    statuses = []
    if output.image_output_count:
        statuses.append(providers.image_status())
    if output.video_output_count:
        statuses.append(providers.video_status())
    if all(item == "ready" for item in statuses):
        return "ready"
    if "not_approved" in statuses:
        return "not_approved"
    return "not_configured"


__all__ = ["router"]
