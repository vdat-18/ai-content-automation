"""Dependency helpers for API request handlers."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from celery import Celery
from fastapi import Depends, FastAPI, Request
from loguru import logger
from pydantic import ValidationError

from ai_content.domains.marketing.creative.adapters.automation_artifacts import (
    FileMarketingCreativeAutomationStateRepository,
)
from ai_content.domains.marketing.creative.adapters.automation_job_repositories import (
    SqliteCreativeAutomationJobRepository,
)
from ai_content.domains.marketing.creative.adapters.automation_storage import (
    FileMarketingCreativeAutomationStorage,
    MarketingCreativeAutomationStorage,
)
from ai_content.domains.marketing.creative.application.ads_provider_registry import (
    AdsActivationProviderRegistry,
)
from ai_content.domains.marketing.creative.application.automation_production import (
    MarketingCreativeAutomationProducer,
)
from ai_content.domains.marketing.creative.application.provider_registry import (
    ManagedMediaProviderRegistry,
)
from ai_content.domains.marketing.creative.bootstrap import CreativeRuntime, build_runtime
from ai_content.domains.marketing.creative.managed_media_runtime import (
    build_managed_media_runtime,
)
from ai_content.domains.marketing.creative.ports.automation_jobs import (
    ICreativeAutomationJobRepository,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    IMarketingCreativeAutomationStateRepository,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    IFrozenProductMediaResolver,
)
from ai_content.domains.marketing.creative_feedback.bootstrap import CreativeFeedbackRuntime
from ai_content.domains.marketing.creative_feedback.bootstrap import (
    build_read_runtime as build_creative_feedback_read_runtime,
)
from ai_content.domains.marketing.creative_intake.bootstrap import CreativeIntakeRuntime
from ai_content.domains.marketing.creative_intake.bootstrap import (
    build_fixture_runtime as build_creative_intake_write_runtime,
)
from ai_content.domains.marketing.creative_intake.bootstrap import (
    build_read_runtime as build_creative_intake_read_runtime,
)
from ai_content.domains.marketing.creative_knowledge.repositories import (
    SqliteCreativeKnowledgeRepository,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.creative_loop.bootstrap import (
    CreativeLoopRuntime,
)
from ai_content.domains.marketing.creative_loop.bootstrap import (
    build_runtime as build_creative_loop_runtime,
)
from ai_content.domains.marketing.creator_operations.bootstrap import (
    CreatorRuntime,
)
from ai_content.domains.marketing.creator_operations.bootstrap import (
    build_read_runtime as build_creator_read_runtime,
)
from ai_content.domains.marketing.creator_outreach.bootstrap import CreatorOutreachRuntime
from ai_content.domains.marketing.creator_outreach.bootstrap import (
    build_read_runtime as build_creator_outreach_read_runtime,
)
from ai_content.domains.marketing.data_sources.adapters.sqlite_repository import (
    SqliteDataSourceRepository,
)
from ai_content.domains.marketing.data_sources.application.scheduler import (
    run_data_source_sync_schedule,
)
from ai_content.domains.marketing.data_sources.bootstrap import DataSourceRuntime
from ai_content.domains.marketing.data_sources.bootstrap import (
    build_runtime as build_data_source_runtime,
)
from ai_content.domains.marketing.data_sources.config import load_data_sources_config
from ai_content.domains.marketing.data_sources.ports.interfaces import IDataSourceRepository
from ai_content.domains.marketing.email_health.bootstrap import EmailHealthRuntime
from ai_content.domains.marketing.email_health.bootstrap import (
    build_read_runtime as build_email_health_read_runtime,
)
from ai_content.domains.marketing.email_production.bootstrap import (
    EmailProductionRuntime,
)
from ai_content.domains.marketing.email_production.bootstrap import (
    build_read_runtime as build_email_production_read_runtime,
)
from ai_content.domains.marketing.email_reporting.bootstrap import (
    EmailReportRuntime,
    build_read_runtime,
)
from ai_content.domains.marketing.media_lab.adapters.asset_artifacts import (
    ObjectStorageMediaAssetArtifacts,
)
from ai_content.domains.marketing.media_lab.adapters.http_video_verifier import (
    HttpVideoEvidenceVerifier,
)
from ai_content.domains.marketing.media_lab.application.assets import MediaAssetService
from ai_content.domains.marketing.media_lab.application.image_runs import (
    MediaLabImageService,
    build_image_capabilities,
)
from ai_content.domains.marketing.media_lab.application.orchestration import (
    MediaLabImageOrchestrationService,
)
from ai_content.domains.marketing.media_lab.application.planning_jobs import (
    MediaLabPlanningJobService,
)
from ai_content.domains.marketing.media_lab.application.video_ads import MediaLabVideoAdService
from ai_content.domains.marketing.media_lab.application.video_orchestration import (
    MediaLabVideoOrchestrationService,
)
from ai_content.domains.marketing.media_lab.application.video_projects import (
    MediaLabVideoProjectService,
)
from ai_content.domains.marketing.media_lab.application.video_runs import (
    MediaLabVideoService,
    build_video_capabilities,
)
from ai_content.domains.marketing.media_lab.bootstrap import (
    build_media_asset_runtime,
    build_planning_job_runtime,
    build_terra_runtime,
    build_video_ad_runtime,
    build_video_frame_sampler,
    build_video_project_runtime,
    build_video_terra_runtime,
)
from ai_content.domains.marketing.media_lab.bootstrap import (
    build_runtime as build_media_lab_image_runtime,
)
from ai_content.domains.marketing.media_lab.bootstrap import (
    build_video_runtime as build_media_lab_video_runtime,
)
from ai_content.domains.marketing.media_lab.config.orchestration import (
    load_media_lab_video_verifier_config,
)
from ai_content.domains.marketing.media_lab.domain.assets import MediaAssetLimits
from ai_content.domains.marketing.media_lab.ports.interfaces import (
    MediaLabImageOrchestrationError,
)
from ai_content.domains.marketing.media_lab.ports.video_interfaces import (
    IVideoGenerationBackend,
    MediaLabVideoOrchestrationError,
)
from ai_content.domains.marketing.performance_data.adapters.sqlite_repository import (
    SqliteGmcRunRepository,
)
from ai_content.domains.marketing.performance_data.ports.interfaces import IGmcRunRepository
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    PerformanceDecisionRuntime,
)
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    build_read_runtime as build_performance_decision_read_runtime,
)
from ai_content.domains.marketing.research_crawler.artifacts import (
    ResearchCrawlArtifactWriter,
)
from ai_content.domains.marketing.research_crawler.brand_context import (
    ResearchBrandContextResolver,
)
from ai_content.domains.marketing.research_crawler.jev_navigation import (
    JevBrowserNavigator,
)
from ai_content.domains.marketing.research_crawler.media_capture import (
    ResearchMediaCapturer,
)
from ai_content.domains.marketing.research_crawler.repositories import (
    SqliteResearchCrawlRepository,
)
from ai_content.domains.marketing.research_crawler.repository import (
    ResearchCrawlRepository,
)
from ai_content.domains.marketing.research_crawler.scrapling_adapter import (
    ScraplingCrawler,
)
from ai_content.domains.marketing.research_crawler.screening import (
    NineRouterResearchScreener,
    load_research_screening_config,
)
from ai_content.domains.marketing.research_crawler.service import ResearchCrawlService
from ai_content.entrypoints.postgres_runtime import PostgresRuntimeContainer
from ai_content.platform.ai_usage import (
    AIUsageRepository,
    AIUsageTracker,
    SqliteAIUsageRepository,
)
from ai_content.platform.artifacts import ArtifactStore, ObjectStorage, ObjectStorageSettings
from ai_content.platform.database import Database
from ai_content.platform.execution import (
    CommandScheduler,
    CommandStatusStore,
    SqliteCommandQueue,
)
from ai_content.platform.notifications import (
    NotificationRepository,
    SqliteNotificationRepository,
)
from ai_content.platform.observability import (
    ObservabilitySettings,
    instrument_sqlalchemy,
    sample_commands_forever,
)
from ai_content.settings import ApplicationSettings

from .media_lab import LegacyMediaGraphService, build_legacy_media_graph_service


@dataclass(frozen=True)
class ApiRuntimeSettings:
    """Runtime settings used for dashboard API and front-end."""

    db_path: Path
    artifacts_root: Path
    config_dir: Path
    legacy_local_models_enabled: bool = False
    preparation_config_path: Path | None = None
    orchestration_config_path: Path | None = None
    router_api_key: str | None = None
    gemini_api_key: str | None = None
    image_api_key: str | None = None
    video_api_key: str | None = None
    managed_media_config_path: Path | None = None
    image_config_path: Path | None = None
    product_segmenter_config_path: Path | None = None
    database_backend: Literal["sqlite", "postgresql"] = "sqlite"
    database_url: str | None = None
    execution_backend: Literal["lease_worker", "celery"] = "lease_worker"
    celery_broker_url: str | None = None
    celery_broker_connection_timeout_seconds: int = 10
    creative_automation_max_concurrency: int = 10
    creative_automation_allow_cached_shopify_fallback: bool = False
    creative_automation_default_market: str = "US"
    creative_automation_video_duration_min_seconds: int = 15
    creative_automation_video_duration_max_seconds: int = 25
    creative_automation_video_source_duration_max_seconds: int = 15
    object_storage: ObjectStorageSettings = ObjectStorageSettings()
    data_sources_config_path: Path | None = None
    data_source_timeout_seconds: float = 60
    research_crawl_timeout_seconds: float = 300
    research_screening_config_path: Path | None = None
    jev_api_url: str | None = None
    jev_api_key: str | None = None
    jev_navigation_model: str = "jev-latest"
    data_source_sync_interval_seconds: float | None = None
    meta_token_expires_at: datetime | None = None
    google_ads_token_expires_at: datetime | None = None
    shopify_token_expires_at: datetime | None = None
    media_lab_image_comfyui_url: str | None = None
    media_lab_video_comfyui_url: str | None = None
    media_lab_image_runpod_endpoint_id: str | None = None
    media_lab_image_runpod_api_key: str | None = None
    media_lab_video_runpod_endpoint_id: str | None = None
    media_lab_video_runpod_api_key: str | None = None
    media_lab_verifier_runpod_endpoint_id: str | None = None
    media_lab_verifier_runpod_api_key: str | None = None
    media_asset_max_image_bytes: int = 100_000_000
    media_asset_max_video_bytes: int = 1_000_000_000
    media_asset_max_image_pixels: int = 100_000_000
    media_asset_max_video_duration_seconds: int = 600
    media_asset_max_working_image_pixels: int = 16_777_216
    media_asset_max_preview_image_pixels: int = 2_073_600
    media_asset_processing_timeout_seconds: int = 120
    media_lab_orchestrator_config_path: Path | None = None
    media_lab_video_orchestrator_config_path: Path | None = None
    media_lab_video_verifier_config_path: Path | None = None
    shopify_access_token: str | None = None
    shopify_demohome_access_token: str | None = None
    shopify_demofurn_access_token: str | None = None
    shopify_demohome_client_id: str | None = None
    shopify_demohome_client_secret: str | None = None
    shopify_demofurn_client_id: str | None = None
    shopify_demofurn_client_secret: str | None = None
    lark_tenant_access_token: str | None = None
    lark_app_id: str | None = None
    lark_app_secret: str | None = None
    google_access_token: str | None = None
    meta_access_token: str | None = None
    google_ads_access_token: str | None = None
    google_ads_client_id: str | None = None
    google_ads_client_secret: str | None = None
    google_ads_refresh_token: str | None = None
    google_ads_developer_token: str | None = None
    google_ads_login_customer_id: str | None = None
    pinterest_access_token: str | None = None
    google_merchant_access_token: str | None = None
    klaviyo_api_key: str | None = None


@dataclass(frozen=True)
class RuntimeReadiness:
    """Dependency status exposed by the lightweight readiness endpoint."""

    ready: bool
    checks: dict[str, str]


def get_runtime_settings() -> ApiRuntimeSettings:
    """Build default runtime settings for the dashboard API."""
    application = ApplicationSettings()
    return ApiRuntimeSettings(
        db_path=application.data_root / "state.db",
        artifacts_root=application.data_root / "artifacts",
        config_dir=application.config_dir,
        legacy_local_models_enabled=application.legacy_local_models_enabled,
        preparation_config_path=application.preparation_config_path,
        orchestration_config_path=application.orchestration_config_path,
        router_api_key=application.credential("ROUTER_API_KEY"),
        gemini_api_key=application.credential("GEMINI_API_KEY"),
        image_api_key=application.credential("IMAGE_API_KEY"),
        video_api_key=application.credential("VIDEO_API_KEY"),
        managed_media_config_path=application.managed_media_config,
        image_config_path=application.image_config,
        product_segmenter_config_path=(
            application.product_segmenter_config
            if application.legacy_local_models_enabled
            else None
        ),
        database_backend=application.database_backend,
        database_url=(
            application.database_url.get_secret_value() if application.database_url else None
        ),
        execution_backend=application.execution_backend,
        celery_broker_url=(
            application.celery_broker_url.get_secret_value()
            if application.celery_broker_url
            else None
        ),
        celery_broker_connection_timeout_seconds=(
            application.celery_broker_connection_timeout_seconds
        ),
        creative_automation_max_concurrency=application.creative_automation_max_concurrency,
        creative_automation_allow_cached_shopify_fallback=(
            application.creative_automation_allow_cached_shopify_fallback
        ),
        creative_automation_default_market=application.creative_automation_default_market,
        creative_automation_video_duration_min_seconds=(
            application.creative_automation_video_duration_min_seconds
        ),
        creative_automation_video_duration_max_seconds=(
            application.creative_automation_video_duration_max_seconds
        ),
        creative_automation_video_source_duration_max_seconds=(
            application.creative_automation_video_source_duration_max_seconds
        ),
        object_storage=application.object_storage(),
        data_sources_config_path=application.data_sources_config,
        data_source_timeout_seconds=application.data_source_timeout_seconds,
        research_crawl_timeout_seconds=application.research_crawl_timeout_seconds,
        research_screening_config_path=application.research_screening_config,
        jev_api_url=application.jev_api_url,
        jev_api_key=application.credential("JEV_API_KEY"),
        jev_navigation_model=application.jev_navigation_model,
        data_source_sync_interval_seconds=application.data_source_sync_interval_seconds,
        meta_token_expires_at=application.meta_token_expires_at,
        google_ads_token_expires_at=application.google_ads_token_expires_at,
        shopify_token_expires_at=application.shopify_token_expires_at,
        media_lab_image_comfyui_url=(
            application.resolved_media_lab_image_comfyui_url
            if application.legacy_local_models_enabled
            else None
        ),
        media_lab_video_comfyui_url=(
            application.resolved_media_lab_video_comfyui_url
            if application.legacy_local_models_enabled
            else None
        ),
        media_lab_image_runpod_endpoint_id=(
            application.media_lab_image_runpod_endpoint_id
            if application.legacy_local_models_enabled
            else None
        ),
        media_lab_image_runpod_api_key=(
            application.media_lab_image_runpod_api_key.get_secret_value()
            if application.legacy_local_models_enabled
            and application.media_lab_image_runpod_api_key
            else None
        ),
        media_lab_video_runpod_endpoint_id=(
            application.media_lab_video_runpod_endpoint_id
            if application.legacy_local_models_enabled
            else None
        ),
        media_lab_video_runpod_api_key=(
            application.media_lab_video_runpod_api_key.get_secret_value()
            if application.legacy_local_models_enabled
            and application.media_lab_video_runpod_api_key
            else None
        ),
        media_lab_verifier_runpod_endpoint_id=(
            application.media_lab_verifier_runpod_endpoint_id
            if application.legacy_local_models_enabled
            else None
        ),
        media_lab_verifier_runpod_api_key=(
            application.media_lab_verifier_runpod_api_key.get_secret_value()
            if application.legacy_local_models_enabled
            and application.media_lab_verifier_runpod_api_key
            else None
        ),
        media_asset_max_image_bytes=application.media_asset_max_image_bytes,
        media_asset_max_video_bytes=application.media_asset_max_video_bytes,
        media_asset_max_image_pixels=application.media_asset_max_image_pixels,
        media_asset_max_video_duration_seconds=application.media_asset_max_video_duration_seconds,
        media_asset_max_working_image_pixels=application.media_asset_max_working_image_pixels,
        media_asset_max_preview_image_pixels=application.media_asset_max_preview_image_pixels,
        media_asset_processing_timeout_seconds=application.media_asset_processing_timeout_seconds,
        media_lab_orchestrator_config_path=(
            application.media_lab_orchestrator_config
            if application.legacy_local_models_enabled
            else None
        ),
        media_lab_video_orchestrator_config_path=application.media_lab_video_orchestrator_config,
        media_lab_video_verifier_config_path=(
            application.media_lab_video_verifier_config
            if application.legacy_local_models_enabled
            else None
        ),
        shopify_access_token=(
            application.shopify_access_token.get_secret_value()
            if application.shopify_access_token
            else None
        ),
        shopify_demohome_access_token=(
            application.shopify_demohome_access_token.get_secret_value()
            if application.shopify_demohome_access_token
            else None
        ),
        shopify_demofurn_access_token=(
            application.shopify_demofurn_access_token.get_secret_value()
            if application.shopify_demofurn_access_token
            else None
        ),
        shopify_demohome_client_id=application.shopify_demohome_client_id,
        shopify_demohome_client_secret=(
            application.shopify_demohome_client_secret.get_secret_value()
            if application.shopify_demohome_client_secret
            else None
        ),
        shopify_demofurn_client_id=application.shopify_demofurn_client_id,
        shopify_demofurn_client_secret=(
            application.shopify_demofurn_client_secret.get_secret_value()
            if application.shopify_demofurn_client_secret
            else None
        ),
        lark_tenant_access_token=(
            application.lark_tenant_access_token.get_secret_value()
            if application.lark_tenant_access_token
            else None
        ),
        lark_app_id=application.lark_app_id,
        lark_app_secret=(
            application.lark_app_secret.get_secret_value() if application.lark_app_secret else None
        ),
        google_access_token=(
            application.google_access_token.get_secret_value()
            if application.google_access_token
            else None
        ),
        meta_access_token=(
            application.meta_access_token.get_secret_value()
            if application.meta_access_token
            else None
        ),
        google_ads_access_token=(
            application.google_ads_access_token.get_secret_value()
            if application.google_ads_access_token
            else None
        ),
        google_ads_client_id=application.google_ads_client_id,
        google_ads_client_secret=(
            application.google_ads_client_secret.get_secret_value()
            if application.google_ads_client_secret
            else None
        ),
        google_ads_refresh_token=(
            application.google_ads_refresh_token.get_secret_value()
            if application.google_ads_refresh_token
            else None
        ),
        google_ads_developer_token=(
            application.google_ads_developer_token.get_secret_value()
            if application.google_ads_developer_token
            else None
        ),
        google_ads_login_customer_id=application.google_ads_login_customer_id,
        pinterest_access_token=(
            application.pinterest_access_token.get_secret_value()
            if application.pinterest_access_token
            else None
        ),
        google_merchant_access_token=(
            application.google_merchant_access_token.get_secret_value()
            if application.google_merchant_access_token
            else None
        ),
        klaviyo_api_key=(
            application.klaviyo_api_key.get_secret_value() if application.klaviyo_api_key else None
        ),
    )


def get_managed_media_provider_registry(request: Request) -> ManagedMediaProviderRegistry:
    """Return the configured approved media registry or a fail-closed default."""
    return getattr(
        request.app.state,
        "managed_media_provider_registry",
        ManagedMediaProviderRegistry(),
    )


def get_ads_activation_provider_registry(request: Request) -> AdsActivationProviderRegistry:
    """Return the approved Ads registry or a fail-closed default."""
    return getattr(
        request.app.state,
        "ads_activation_provider_registry",
        AdsActivationProviderRegistry(),
    )


def get_creative_automation_producer(
    request: Request,
) -> MarketingCreativeAutomationProducer | None:
    """Return an explicitly composed paid production service, never an implicit provider."""
    return getattr(request.app.state, "creative_automation_producer", None)


def get_product_media_source_resolver(
    request: Request,
) -> IFrozenProductMediaResolver | None:
    """Return the secure resolver used to freeze Shopify media before preparation."""
    return getattr(request.app.state, "product_media_source_resolver", None)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own PostgreSQL resources for the lifetime of the API process."""
    settings = get_runtime_settings()
    observability = getattr(
        application.state,
        "observability_settings",
        ObservabilitySettings(service_name="aicontent-api"),
    )
    container = None
    metrics_stop = asyncio.Event()
    metrics_task: asyncio.Task[None] | None = None
    sync_stop = asyncio.Event()
    sync_task: asyncio.Task[None] | None = None
    sync_scheduler: CommandScheduler | None = None
    owns_sync_scheduler = False
    legacy_media_graph_service: LegacyMediaGraphService = build_legacy_media_graph_service(
        settings.config_dir,
        settings.artifacts_root,
        settings.media_lab_image_comfyui_url,
        video_comfyui_url=settings.media_lab_video_comfyui_url,
        image_runpod_endpoint_id=settings.media_lab_image_runpod_endpoint_id,
        image_runpod_api_key=settings.media_lab_image_runpod_api_key,
        video_runpod_endpoint_id=settings.media_lab_video_runpod_endpoint_id,
        video_runpod_api_key=settings.media_lab_video_runpod_api_key,
    )
    application.state.legacy_media_graph_service = legacy_media_graph_service
    media_lab_video_backend: IVideoGenerationBackend = legacy_media_graph_service
    application.state.media_lab_video_backend = media_lab_video_backend
    media_asset_service: MediaAssetService | None = None
    media_lab_image_service: MediaLabImageService | None = None
    media_lab_image_orchestration_service: MediaLabImageOrchestrationService | None = None
    media_lab_video_service: MediaLabVideoService | None = None
    media_lab_video_project_service: MediaLabVideoProjectService | None = None
    media_lab_video_ad_service: MediaLabVideoAdService | None = None
    media_lab_video_ad_stop = asyncio.Event()
    media_lab_video_ad_task: asyncio.Task[None] | None = None
    media_lab_planning_job_service: MediaLabPlanningJobService | None = None
    media_lab_planning_job_stop = asyncio.Event()
    media_lab_planning_job_task: asyncio.Task[None] | None = None
    media_lab_video_orchestration_service: MediaLabVideoOrchestrationService | None = None
    media_lab_orchestration_usage_repository: SqliteAIUsageRepository | None = None

    def media_lab_usage_tracker() -> AIUsageTracker:
        nonlocal media_lab_orchestration_usage_repository
        if container is not None:
            return container.ai_usage_tracker
        if media_lab_orchestration_usage_repository is None:
            settings.db_path.parent.mkdir(parents=True, exist_ok=True)
            media_lab_orchestration_usage_repository = SqliteAIUsageRepository(settings.db_path)
        return AIUsageTracker(media_lab_orchestration_usage_repository)

    if settings.database_backend == "postgresql":
        assert settings.database_url is not None
        database = Database(settings.database_url)
        container = PostgresRuntimeContainer(
            database,
            settings.artifacts_root,
            settings.config_dir,
            preparation_config_path=_preparation_config_path(settings),
            preparation_api_key=settings.gemini_api_key or settings.router_api_key,
            image_config_path=settings.image_config_path,
            product_segmenter_config_path=settings.product_segmenter_config_path,
            legacy_local_models_enabled=settings.legacy_local_models_enabled,
            product_segmenter_runpod_endpoint_id=(settings.media_lab_verifier_runpod_endpoint_id),
            product_segmenter_runpod_api_key=settings.media_lab_verifier_runpod_api_key,
            execution_backend=settings.execution_backend,
            object_storage=settings.object_storage.build()
            if settings.object_storage.backend == "s3"
            else None,
            object_storage_bucket=settings.object_storage.bucket,
        )
        application.state.postgres_runtime = container
        instrument_sqlalchemy(database.engine, observability)
        if observability.metrics_enabled:
            metrics_task = asyncio.create_task(
                sample_commands_forever(
                    container.execution_status_store,
                    metrics_stop,
                    observability.command_metrics_interval_seconds,
                )
            )
    managed_state_repository = (
        container.creative_automation_state_repository
        if container is not None
        else FileMarketingCreativeAutomationStateRepository(ArtifactStore(settings.artifacts_root))
    )
    try:
        managed_media = build_managed_media_runtime(
            config_path=settings.managed_media_config_path,
            api_key=settings.router_api_key,
            image_api_key=settings.image_api_key,
            video_api_key=settings.video_api_key,
            artifact_store=(
                container.artifacts
                if container is not None
                else ArtifactStore(settings.artifacts_root)
            ),
            artifact_service=(container.artifact_service if container is not None else None),
            state_repository=managed_state_repository,
        )
    except (OSError, ValueError) as error:
        logger.error("Managed Creative media disabled: {}", error)
        managed_media = build_managed_media_runtime(
            config_path=None,
            api_key=None,
            artifact_store=(
                container.artifacts
                if container is not None
                else ArtifactStore(settings.artifacts_root)
            ),
            artifact_service=None,
            state_repository=managed_state_repository,
        )
    application.state.managed_media_provider_registry = managed_media.providers
    application.state.creative_automation_producer = managed_media.producer
    application.state.product_media_source_resolver = managed_media.source_resolver

    media_asset_limits = MediaAssetLimits(
        max_image_bytes=settings.media_asset_max_image_bytes,
        max_video_bytes=settings.media_asset_max_video_bytes,
        max_image_pixels=settings.media_asset_max_image_pixels,
        max_video_duration_seconds=settings.media_asset_max_video_duration_seconds,
        max_working_image_pixels=settings.media_asset_max_working_image_pixels,
        max_preview_image_pixels=settings.media_asset_max_preview_image_pixels,
        processing_timeout_seconds=settings.media_asset_processing_timeout_seconds,
    )
    if container is not None and container.artifact_service is not None:
        if container.object_storage is None:
            raise RuntimeError("Media asset object storage is unavailable")
        media_asset_service = build_media_asset_runtime(
            settings.db_path,
            settings.artifacts_root,
            media_asset_limits,
            repository=container.media_lab_asset_repository,
            artifacts=ObjectStorageMediaAssetArtifacts(
                container.artifact_service,
                container.artifact_service.catalog,
                container.object_storage,
            ),
        )
    else:
        media_asset_service = build_media_asset_runtime(
            settings.db_path,
            settings.artifacts_root,
            media_asset_limits,
        )
    application.state.media_asset_service = media_asset_service

    media_lab_quality_reviewer = None
    if settings.media_lab_orchestrator_config_path is not None:
        try:
            terra_runtime = build_terra_runtime(
                settings.media_lab_orchestrator_config_path,
                api_key=settings.gemini_api_key or settings.router_api_key,
                capabilities=build_image_capabilities(legacy_media_graph_service),
                usage_tracker=media_lab_usage_tracker(),
            )
            media_lab_image_orchestration_service = terra_runtime.orchestration
            media_lab_quality_reviewer = terra_runtime.quality_reviewer
        except (OSError, ValueError, ValidationError, MediaLabImageOrchestrationError) as error:
            logger.error(
                "Media Lab image orchestration disabled: configuration could not be loaded from {}: {}",
                settings.media_lab_orchestrator_config_path,
                error,
            )
    media_lab_image_service = build_media_lab_image_runtime(
        settings.db_path,
        settings.artifacts_root,
        legacy_media_graph_service,
        repository=(container.media_lab_image_repository if container is not None else None),
        quality_reviewer=media_lab_quality_reviewer,
        media_assets=media_asset_service,
    )
    await media_lab_image_service.interrupt_inflight()
    application.state.media_lab_image_service = media_lab_image_service
    if media_lab_image_orchestration_service is not None:
        application.state.media_lab_image_orchestration_service = (
            media_lab_image_orchestration_service
        )

    media_lab_video_quality_reviewer = None
    media_lab_video_ad_planner = None
    if settings.media_lab_video_orchestrator_config_path is not None:
        try:
            video_terra_runtime = build_video_terra_runtime(
                settings.media_lab_video_orchestrator_config_path,
                api_key=settings.gemini_api_key or settings.router_api_key,
                capabilities=build_video_capabilities(media_lab_video_backend),
                usage_tracker=media_lab_usage_tracker(),
            )
            media_lab_video_orchestration_service = video_terra_runtime.orchestration
            media_lab_video_quality_reviewer = video_terra_runtime.quality_reviewer
            media_lab_video_ad_planner = video_terra_runtime.video_ad_planner
        except (OSError, ValueError, ValidationError, MediaLabVideoOrchestrationError) as error:
            logger.error(
                "Media Lab video orchestration disabled: configuration could not be "
                "loaded from {}: {}",
                settings.media_lab_video_orchestrator_config_path,
                error,
            )
    media_lab_video_evidence_verifier = None
    media_lab_video_frame_sampler = None
    if settings.media_lab_video_verifier_config_path is not None:
        try:
            verifier_config = load_media_lab_video_verifier_config(
                settings.media_lab_video_verifier_config_path
            )
            media_lab_video_evidence_verifier = HttpVideoEvidenceVerifier(
                verifier_config,
                runpod_endpoint_id=settings.media_lab_verifier_runpod_endpoint_id,
                runpod_api_key=settings.media_lab_verifier_runpod_api_key,
            )
            media_lab_video_frame_sampler = build_video_frame_sampler(verifier_config)
        except (OSError, ValueError, ValidationError) as error:
            logger.error(
                "Media Lab video evidence verification disabled: configuration could not be "
                "loaded from {}: {}",
                settings.media_lab_video_verifier_config_path,
                error,
            )
    media_lab_video_service = build_media_lab_video_runtime(
        settings.db_path,
        settings.artifacts_root,
        media_lab_video_backend,
        media_lab_image_service,
        repository=(container.media_lab_video_repository if container is not None else None),
        quality_reviewer=media_lab_video_quality_reviewer,
        evidence_verifier=media_lab_video_evidence_verifier,
        frame_sampler=media_lab_video_frame_sampler,
        media_assets=media_asset_service,
    )
    await media_lab_video_service.interrupt_inflight()
    application.state.media_lab_video_service = media_lab_video_service
    if media_lab_video_orchestration_service is not None:
        application.state.media_lab_video_orchestration_service = (
            media_lab_video_orchestration_service
        )
    media_lab_video_project_service = build_video_project_runtime(
        settings.db_path,
        settings.artifacts_root,
        media_lab_video_service,
        media_asset_service,
        repository=(
            container.media_lab_video_project_repository if container is not None else None
        ),
    )
    application.state.media_lab_video_project_service = media_lab_video_project_service
    if media_lab_video_ad_planner is not None:
        media_lab_video_ad_service = build_video_ad_runtime(
            settings.db_path,
            settings.artifacts_root,
            media_lab_video_ad_planner,
            media_lab_video_service,
            media_asset_service,
            repository=(container.media_lab_video_ad_repository if container is not None else None),
        )
        application.state.media_lab_video_ad_service = media_lab_video_ad_service
        media_lab_video_ad_task = asyncio.create_task(
            media_lab_video_ad_service.run_forever(media_lab_video_ad_stop)
        )
    media_lab_planning_job_service = build_planning_job_runtime(
        settings.db_path,
        media_asset_service,
        media_lab_image_orchestration_service,
        media_lab_video_orchestration_service,
        repository=(container.media_lab_planning_job_repository if container is not None else None),
    )
    application.state.media_lab_planning_job_service = media_lab_planning_job_service
    media_lab_planning_job_task = asyncio.create_task(
        media_lab_planning_job_service.run_forever(media_lab_planning_job_stop)
    )

    interval = settings.data_source_sync_interval_seconds
    if interval is not None:
        try:
            sync_definitions = load_data_sources_config(settings.data_sources_config_path)
        except (OSError, ValueError, ValidationError) as error:
            logger.error(
                "Scheduled data source sync disabled: configuration could not be "
                "loaded from {}: {}",
                settings.data_sources_config_path,
                error,
            )
            sync_definitions = None
        if sync_definitions:
            sync_scheduler = (
                container.execution_scheduler
                if container is not None
                else SqliteCommandQueue(settings.db_path)
            )
            owns_sync_scheduler = container is None
            logger.info(
                "Scheduled data source sync enabled every {} seconds for {} sources",
                interval,
                len(sync_definitions),
            )
            sync_task = asyncio.create_task(
                run_data_source_sync_schedule(
                    sync_scheduler,
                    tuple(definition.source_id for definition in sync_definitions),
                    interval,
                    sync_stop,
                )
            )
        elif sync_definitions is not None:
            logger.warning("Scheduled data source sync configured but no data source is defined")
    try:
        yield
    finally:
        media_lab_planning_job_stop.set()
        if media_lab_planning_job_task is not None:
            with suppress(asyncio.CancelledError):
                await media_lab_planning_job_task
        if media_lab_planning_job_service is not None:
            media_lab_planning_job_service.close()
        media_lab_video_ad_stop.set()
        if media_lab_video_ad_task is not None:
            with suppress(asyncio.CancelledError):
                await media_lab_video_ad_task
        if media_lab_video_ad_service is not None:
            media_lab_video_ad_service.close()
        if media_lab_video_project_service is not None:
            media_lab_video_project_service.close()
        if media_lab_video_service is not None:
            await media_lab_video_service.interrupt_inflight()
            media_lab_video_service.close()
        if media_lab_image_service is not None:
            await media_lab_image_service.interrupt_inflight()
            media_lab_image_service.close()
        if media_asset_service is not None:
            media_asset_service.close()
        if media_lab_orchestration_usage_repository is not None:
            media_lab_orchestration_usage_repository.close()
        await legacy_media_graph_service.close()
        metrics_stop.set()
        if metrics_task is not None:
            with suppress(asyncio.CancelledError):
                await metrics_task
        sync_stop.set()
        if sync_task is not None:
            with suppress(asyncio.CancelledError):
                await sync_task
        if sync_scheduler is not None and owns_sync_scheduler:
            sync_scheduler.close()
        if container is not None:
            container.close()
            await container.database.close()
        observability_runtime = getattr(application.state, "observability_runtime", None)
        if observability_runtime is not None:
            observability_runtime.shutdown()


def _postgres_runtime(request: Request) -> PostgresRuntimeContainer | None:
    settings = get_runtime_settings()
    if settings.database_backend == "sqlite":
        return None
    container = getattr(request.app.state, "postgres_runtime", None)
    if container is None:
        raise RuntimeError("PostgreSQL runtime was not initialized")
    return container


def check_runtime_readiness(settings: ApiRuntimeSettings) -> RuntimeReadiness:
    """Check required local dependencies without running a business workflow."""
    checks = _check_config_and_storage(settings)

    try:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.db_path, timeout=1) as connection:
            connection.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except (OSError, sqlite3.Error):
        checks["database"] = "unavailable"

    return RuntimeReadiness(
        ready=all(value == "ok" for value in checks.values()),
        checks=checks,
    )


def _check_config_and_storage(settings: ApiRuntimeSettings) -> dict[str, str]:
    """Check filesystem dependencies shared by both database backends."""
    required_config = (
        settings.config_dir / "fixtures" / "creative_loop_synthetic.json",
        _preparation_config_path(settings),
    )
    checks: dict[str, str] = {}
    try:
        for path in required_config:
            with path.open("rb") as config_file:
                config_file.read(1)
        checks["config"] = "ok"
    except OSError:
        checks["config"] = "unavailable"

    try:
        settings.artifacts_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.artifacts_root):
            pass
        checks["storage"] = "ok"
    except OSError:
        checks["storage"] = "unavailable"
    return checks


def _preparation_config_path(settings: ApiRuntimeSettings) -> Path:
    return settings.preparation_config_path or settings.config_dir / "preparation/synthetic.json"


async def check_runtime_readiness_async(
    settings: ApiRuntimeSettings,
    database: Database | None,
    object_storage: ObjectStorage | None = None,
) -> RuntimeReadiness:
    """Check local dependencies and the selected database backend."""
    if settings.database_backend == "sqlite":
        return check_runtime_readiness(settings)
    checks = _check_config_and_storage(settings)
    if settings.object_storage.backend == "s3":
        try:
            storage = object_storage or settings.object_storage.build()
            await asyncio.to_thread(storage.check)
            checks["storage"] = "ok"
        except Exception:
            checks["storage"] = "unavailable"
    try:
        if database is None:
            raise RuntimeError("PostgreSQL runtime is unavailable")
        await database.check()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    if settings.execution_backend == "celery":
        checks.update(await _check_celery_readiness(settings))
    return RuntimeReadiness(
        ready=all(value == "ok" for value in checks.values()),
        checks=checks,
    )


async def _check_celery_readiness(settings: ApiRuntimeSettings) -> dict[str, str]:
    """Verify that the configured broker is reachable and a worker responds."""
    if settings.celery_broker_url is None:
        return {"broker": "unavailable", "worker": "unavailable"}
    try:
        await asyncio.to_thread(
            _check_celery_broker,
            settings.celery_broker_url,
            settings.celery_broker_connection_timeout_seconds,
        )
    except Exception:
        return {"broker": "unavailable", "worker": "unavailable"}
    try:
        workers = await asyncio.to_thread(
            _ping_celery_workers,
            settings.celery_broker_url,
            settings.celery_broker_connection_timeout_seconds,
        )
    except Exception:
        workers = False
    return {"broker": "ok", "worker": "ok" if workers else "unavailable"}


def _check_celery_broker(broker_url: str, timeout_seconds: int) -> None:
    app = Celery("aicontent-readiness", broker=broker_url)
    try:
        with app.connection_for_read() as connection:
            connection.ensure_connection(max_retries=0, timeout=timeout_seconds)
    finally:
        app.close()


def _ping_celery_workers(broker_url: str, timeout_seconds: int) -> bool:
    app = Celery("aicontent-readiness", broker=broker_url)
    try:
        return bool(app.control.ping(timeout=timeout_seconds, limit=1))
    finally:
        app.close()


async def get_runtime(request: Request) -> AsyncIterator[CreativeRuntime]:
    """Yield a request-scoped runtime and close resources after use."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative()
        return
    runtime = build_runtime(
        db_path=settings.db_path,
        artifacts_root=settings.artifacts_root,
        config_dir=settings.config_dir,
    )
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_creative_loop_runtime(request: Request) -> AsyncIterator[CreativeLoopRuntime]:
    """Yield the unified synthetic Creative loop runtime."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative_loop()
        return
    runtime = build_creative_loop_runtime(
        settings.db_path,
        settings.artifacts_root,
        config_dir=settings.config_dir,
        fixture_path=settings.config_dir / "fixtures/creative_loop_synthetic.json",
        preparation_config=_preparation_config_path(settings),
    )
    try:
        yield runtime
    finally:
        runtime.close()


async def get_notification_repository(
    request: Request,
) -> AsyncIterator[NotificationRepository]:
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.notification_repository
        return
    repository = SqliteNotificationRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_creative_automation_storage(
    request: Request,
) -> AsyncIterator[MarketingCreativeAutomationStorage]:
    """Yield package storage shared by API and worker when PostgreSQL is active."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative_automation_storage
        return
    yield FileMarketingCreativeAutomationStorage(ArtifactStore(settings.artifacts_root))


async def get_creative_automation_state_repository(
    request: Request,
) -> AsyncIterator[IMarketingCreativeAutomationStateRepository]:
    """Yield workflow state storage safe for the configured runtime."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative_automation_state_repository
        return
    yield FileMarketingCreativeAutomationStateRepository(ArtifactStore(settings.artifacts_root))


async def get_creative_automation_job_repository(
    request: Request,
) -> AsyncIterator[ICreativeAutomationJobRepository]:
    """Yield durable selected-SKU monitoring state."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative_automation_job_repository
        return
    repository = SqliteCreativeAutomationJobRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_command_scheduler(request: Request) -> AsyncIterator[CommandScheduler]:
    """Yield the configured command scheduler."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.execution_scheduler
        return
    queue = SqliteCommandQueue(settings.db_path)
    try:
        yield queue
    finally:
        queue.close()


async def get_command_status_store(request: Request) -> AsyncIterator[CommandStatusStore]:
    """Yield the public execution command status projection."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.execution_status_store
        return
    queue = SqliteCommandQueue(settings.db_path)
    try:
        yield queue
    finally:
        queue.close()


async def get_research_crawl_repository(
    request: Request,
) -> AsyncIterator[ResearchCrawlRepository]:
    """Yield workspace-neutral research crawl job storage."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.research_crawl_repository
        return
    repository = SqliteResearchCrawlRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_research_brand_source_repository(
    request: Request,
) -> AsyncIterator[IDataSourceRepository]:
    """Yield the snapshot repository used to build pinned research brand context."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.data_source_repository
        return
    repository = SqliteDataSourceRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_research_crawl_service(
    request: Request,
    repository: ResearchCrawlRepository = Depends(get_research_crawl_repository),
    brand_sources: IDataSourceRepository = Depends(get_research_brand_source_repository),
) -> ResearchCrawlService:
    """Build the one-page Scrapling crawl service for API or inline development use."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    artifact_writer = ResearchCrawlArtifactWriter(
        ArtifactStore(settings.artifacts_root),
        postgres.artifact_service if postgres is not None else None,
    )
    return ResearchCrawlService(
        repository,
        ScraplingCrawler(
            timeout_seconds=settings.research_crawl_timeout_seconds,
            navigator=(
                JevBrowserNavigator(
                    settings.jev_api_key,
                    model=settings.jev_navigation_model,
                    endpoint=settings.jev_api_url,
                )
                if settings.jev_api_key and settings.jev_api_url
                else None
            ),
        ),
        artifact_writer,
        ResearchMediaCapturer(artifact_writer),
        ResearchBrandContextResolver(brand_sources),
        screener=_research_screener(
            settings,
            postgres.ai_usage_tracker if postgres is not None else None,
            artifact_writer,
        ),
    )


def _research_screener(
    settings: ApiRuntimeSettings,
    usage_tracker: AIUsageTracker | None,
    artifact_reader: ResearchCrawlArtifactWriter,
) -> NineRouterResearchScreener | None:
    if settings.research_screening_config_path is None:
        return None
    try:
        config = load_research_screening_config(settings.research_screening_config_path)
    except (OSError, ValueError) as error:
        logger.error(
            "Research analysis unavailable because its configuration is invalid: {}", error
        )
        return None
    if not (settings.gemini_api_key or settings.router_api_key):
        logger.error("Research analysis unavailable because its API key is not configured")
        return None
    return NineRouterResearchScreener(
        config,
        api_key=settings.gemini_api_key or settings.router_api_key,
        usage_tracker=usage_tracker,
        artifact_reader=artifact_reader,
    )


async def get_ai_usage_repository(request: Request) -> AsyncIterator[AIUsageRepository]:
    """Yield the durable usage ledger shared by API and workers."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.ai_usage_repository
        return
    repository = SqliteAIUsageRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


get_execution_queue = get_command_scheduler


async def get_email_report_runtime(request: Request) -> AsyncIterator[EmailReportRuntime]:
    """Yield the local read-only Email report repository."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.email_report()
        return
    runtime = build_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_email_health_runtime(request: Request) -> AsyncIterator[EmailHealthRuntime]:
    """Yield the local Email Operations health runtime without external actions."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.email_health()
        return
    runtime = build_email_health_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_email_production_runtime(request: Request) -> AsyncIterator[EmailProductionRuntime]:
    """Yield the local Email production runtime with external writes disabled."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.email_production()
        return
    runtime = build_email_production_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.close()


async def get_gmc_repository(request: Request) -> AsyncIterator[IGmcRunRepository]:
    """Yield the local read-only GMC run repository."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.gmc_repository
        return
    repository = SqliteGmcRunRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_performance_decision_runtime(
    request: Request,
) -> AsyncIterator[PerformanceDecisionRuntime]:
    """Yield the local Performance decision runtime without external actions."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.performance()
        return
    runtime = build_performance_decision_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_creative_feedback_runtime(
    request: Request,
) -> AsyncIterator[CreativeFeedbackRuntime]:
    """Yield the local Creative feedback runtime without external actions."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.feedback()
        return
    runtime = build_creative_feedback_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_creative_knowledge_service(
    request: Request,
) -> AsyncIterator[CreativeKnowledgeService]:
    """Yield the scoped knowledge registry used by Admin and orchestration."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative_knowledge_service
        return
    repository = SqliteCreativeKnowledgeRepository(settings.db_path)
    try:
        yield CreativeKnowledgeService(repository)
    finally:
        repository.close()


async def get_creative_intake_runtime(request: Request) -> AsyncIterator[CreativeIntakeRuntime]:
    """Yield the local Creative intake runtime without external actions."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.intake()
        return
    runtime = build_creative_intake_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_creative_intake_write_runtime(
    request: Request,
) -> AsyncIterator[CreativeIntakeRuntime]:
    """Yield the intake runtime used by explicit Lead Marketing requests."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.intake()
        return
    runtime = build_creative_intake_write_runtime(
        settings.db_path,
        settings.artifacts_root,
        preparation_api_key=settings.gemini_api_key or settings.router_api_key,
    )
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_creator_runtime(request: Request) -> AsyncIterator[CreatorRuntime]:
    """Yield the local Creator Operations runtime without external connectors."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creator()
        return
    runtime = build_creator_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.repository.close()


async def get_creator_outreach_runtime(request: Request) -> AsyncIterator[CreatorOutreachRuntime]:
    """Yield the local Creator outreach runtime with external actions disabled."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creator_outreach()
        return
    runtime = build_creator_outreach_read_runtime(settings.db_path, settings.artifacts_root)
    try:
        yield runtime
    finally:
        runtime.close()


async def get_data_source_runtime(request: Request) -> AsyncIterator[DataSourceRuntime]:
    """Yield configured read-only connectors and durable snapshot storage."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    runtime = _build_data_source_runtime(settings, postgres)
    try:
        yield runtime
    finally:
        await runtime.close()


def _build_data_source_runtime(
    settings: ApiRuntimeSettings,
    postgres: PostgresRuntimeContainer | None,
) -> DataSourceRuntime:
    definitions = load_data_sources_config(settings.data_sources_config_path)
    return build_data_source_runtime(
        definitions,
        settings.db_path,
        settings.artifacts_root,
        shopify_token=settings.shopify_access_token,
        shopify_source_tokens={
            "shopify-demohome-products": settings.shopify_demohome_access_token,
            "shopify-demofurn-products": settings.shopify_demofurn_access_token,
        },
        shopify_source_client_credentials={
            "shopify-demohome-products": (
                settings.shopify_demohome_client_id,
                settings.shopify_demohome_client_secret,
            ),
            "shopify-demofurn-products": (
                settings.shopify_demofurn_client_id,
                settings.shopify_demofurn_client_secret,
            ),
        },
        lark_token=settings.lark_tenant_access_token,
        lark_app_id=settings.lark_app_id,
        lark_app_secret=settings.lark_app_secret,
        google_token=settings.google_access_token,
        meta_token=settings.meta_access_token,
        google_ads_token=settings.google_ads_access_token,
        google_ads_client_id=settings.google_ads_client_id,
        google_ads_client_secret=settings.google_ads_client_secret,
        google_ads_refresh_token=settings.google_ads_refresh_token,
        google_ads_developer_token=settings.google_ads_developer_token,
        google_ads_login_customer_id=settings.google_ads_login_customer_id,
        pinterest_token=settings.pinterest_access_token,
        google_merchant_token=settings.google_merchant_access_token,
        klaviyo_api_key=settings.klaviyo_api_key,
        timeout_seconds=settings.data_source_timeout_seconds,
        repository=postgres.data_source_repository if postgres is not None else None,
        artifact_service=postgres.artifact_service if postgres is not None else None,
    )
