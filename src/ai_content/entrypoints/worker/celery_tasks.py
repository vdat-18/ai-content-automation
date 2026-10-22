"""Celery tasks that execute persisted application commands."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from celery import Task
from loguru import logger
from pydantic import SecretStr

from ai_content.domains.marketing.creative.adapters.automation_commands import (
    CreativeAutomationCommandDispatcher,
    CreativeAutomationCommandName,
)
from ai_content.domains.marketing.creative.adapters.baml_orchestration import (
    BamlCreativeAutomationOrchestrator,
)
from ai_content.domains.marketing.creative.adapters.fake_orchestration import (
    FakeCreativeAutomationOrchestrator,
)
from ai_content.domains.marketing.creative.application.automation_workflow import (
    record_production_outcome,
)
from ai_content.domains.marketing.creative.config.images import (
    ImageBackendConfig,
    load_image_config,
)
from ai_content.domains.marketing.creative.config.orchestration import (
    load_orchestration_config,
)
from ai_content.domains.marketing.creative.config.preparation import load_preparation_config
from ai_content.domains.marketing.creative.config.reviewers import (
    load_semantic_reviewer_config,
)
from ai_content.domains.marketing.creative.managed_media_runtime import (
    build_managed_media_runtime,
)
from ai_content.domains.marketing.creative.ports.automation_jobs import (
    CreativeAutomationEvent,
    CreativeAutomationJobIssue,
    ICreativeAutomationJobRepository,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    MarketingCreativeAutomationStatus,
    resolve_state_repository_call,
)
from ai_content.domains.marketing.creative.ports.contracts import (
    MarketingCreativeAutomationRequest,
)
from ai_content.domains.marketing.creative_feedback.config.learning import (
    load_performance_learning_config,
)
from ai_content.domains.marketing.creative_loop.adapters.commands import (
    CreativeLoopCommandDispatcher,
)
from ai_content.domains.marketing.data_sources.application.compile_automation import (
    MarketingCreativeAutomationCompiler,
)
from ai_content.domains.marketing.data_sources.application.compile_context import (
    CreativeSourceContextCompiler,
)
from ai_content.domains.marketing.data_sources.bootstrap import (
    build_runtime as build_data_source_runtime,
)
from ai_content.domains.marketing.data_sources.commands import (
    DataSourceCommandDispatcher,
    DataSourceCommandName,
)
from ai_content.domains.marketing.data_sources.config import load_data_sources_config
from ai_content.domains.marketing.data_sources.ports.interfaces import SourceReadError
from ai_content.domains.marketing.research_crawler.artifacts import (
    ResearchCrawlArtifactWriter,
)
from ai_content.domains.marketing.research_crawler.brand_context import (
    ResearchBrandContextResolver,
)
from ai_content.domains.marketing.research_crawler.commands import (
    ResearchCrawlCommandDispatcher,
    ResearchCrawlCommandName,
)
from ai_content.domains.marketing.research_crawler.jev_navigation import (
    JevBrowserNavigator,
)
from ai_content.domains.marketing.research_crawler.media_capture import (
    ResearchMediaCapturer,
)
from ai_content.domains.marketing.research_crawler.scrapling_adapter import (
    ScraplingCrawler,
)
from ai_content.domains.marketing.research_crawler.screening import (
    NineRouterResearchScreener,
    load_research_screening_config,
)
from ai_content.domains.marketing.research_crawler.service import ResearchCrawlService
from ai_content.entrypoints.api.creative_automation import (
    _job_item_response,
    _notify_batch_completed,
    _notify_job_result,
    _persist_state_job_projection,
    _process_automation_request,
    measure_automation_step,
    record_automation_step_latency,
    record_automation_total_latency,
)
from ai_content.entrypoints.postgres_runtime import PostgresRuntimeContainer
from ai_content.platform.database import Database
from ai_content.platform.execution import (
    CELERY_EXECUTE_COMMAND_TASK,
    CommandStatus,
    ExecutionCommand,
    ExecutionWorker,
)
from ai_content.platform.observability import instrument_sqlalchemy
from ai_content.settings import ApplicationSettings

from .celery_app import app
from .celery_app import settings as worker_settings


@app.task(
    bind=True,
    name=CELERY_EXECUTE_COMMAND_TASK,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=None,
)
def execute_command(self: Task, command_id: str, dispatch_generation: int) -> str:
    """Claim and execute one durable command identified by its generation."""
    try:
        status, retry_after = asyncio.run(_execute_command(command_id, dispatch_generation))
    except Exception as error:
        logger.exception(
            "Celery command {} generation {} failed before durable handling completed",
            command_id,
            dispatch_generation,
        )
        raise self.retry(
            exc=error,
            countdown=worker_settings.celery_retry_poll_interval_seconds,
            max_retries=None,
        ) from error
    if status in {
        CommandStatus.PENDING,
        CommandStatus.RUNNING,
        CommandStatus.RETRY_WAIT,
        CommandStatus.CANCEL_REQUESTED,
    }:
        raise self.retry(countdown=max(retry_after, 1), max_retries=None)
    return status.value


async def _execute_command(
    command_id: str,
    dispatch_generation: int,
) -> tuple[CommandStatus, int]:
    settings = ApplicationSettings()
    if settings.database_backend != "postgresql" or settings.database_url is None:
        raise RuntimeError("Celery commands require the PostgreSQL runtime")
    database = Database(settings.database_url.get_secret_value())
    observability = settings.observability("aicontent-worker")
    instrument_sqlalchemy(database.engine, observability)
    storage_settings = settings.object_storage()
    preparation_settings = load_preparation_config(settings.preparation_config_path)
    image_settings = load_image_config(settings.image_config) if settings.image_config else None
    review_config_path = _legacy_semantic_review_config_path(settings.review_config, image_settings)
    review_settings = (
        load_semantic_reviewer_config(review_config_path)
        if review_config_path is not None
        else None
    )
    learning_settings = (
        load_performance_learning_config(settings.learning_config)
        if settings.learning_config
        else None
    )
    container = PostgresRuntimeContainer(
        database,
        settings.data_root / "artifacts",
        settings.config_dir,
        preparation_config_path=settings.preparation_config_path,
        preparation_api_key=settings.credential(preparation_settings.api_key_env),
        image_config_path=settings.image_config,
        image_api_key=(
            settings.credential(image_settings.api_key_env or image_settings.token_env)
            if image_settings is not None
            else None
        ),
        product_segmenter_config_path=(
            settings.product_segmenter_config if settings.legacy_local_models_enabled else None
        ),
        legacy_local_models_enabled=settings.legacy_local_models_enabled,
        product_segmenter_runpod_endpoint_id=(
            settings.media_lab_verifier_runpod_endpoint_id
            if settings.legacy_local_models_enabled
            else None
        ),
        product_segmenter_runpod_api_key=(
            settings.media_lab_verifier_runpod_api_key.get_secret_value()
            if settings.legacy_local_models_enabled and settings.media_lab_verifier_runpod_api_key
            else None
        ),
        review_config_path=review_config_path,
        review_api_key=(
            settings.credential(review_settings.api_key_env)
            if review_settings is not None
            else None
        ),
        learning_config_path=settings.learning_config,
        learning_api_key=(
            settings.credential(learning_settings.api_key_env)
            if learning_settings is not None
            else None
        ),
        execution_backend="celery",
        object_storage=storage_settings.build() if storage_settings.backend == "s3" else None,
        object_storage_bucket=storage_settings.bucket,
    )
    try:
        managed_media = build_managed_media_runtime(
            config_path=settings.managed_media_config,
            api_key=settings.credential("ROUTER_API_KEY"),
            image_api_key=settings.credential("IMAGE_API_KEY"),
            video_api_key=settings.credential("VIDEO_API_KEY"),
            artifact_store=container.artifacts,
            artifact_service=container.artifact_service,
            state_repository=container.creative_automation_state_repository,
        )
    except (OSError, ValueError) as error:
        logger.error("Managed Creative media disabled: {}", error)
        managed_media = build_managed_media_runtime(
            config_path=None,
            api_key=None,
            artifact_store=container.artifacts,
            artifact_service=None,
            state_repository=container.creative_automation_state_repository,
        )

    loop_dispatcher = CreativeLoopCommandDispatcher(
        None,
        settings.data_root / "artifacts",
        settings.config_dir,
        settings.config_dir / "fixtures/creative_loop_synthetic.json",
        settings.preparation_config_path,
        runtime_factory=container.creative_loop,
    )

    async def notify_batch_if_complete(batch_id: str) -> None:
        jobs = [
            job
            for job in await container.creative_automation_job_repository.list_jobs()
            if job.batch_id == batch_id
        ]
        active_statuses = {"queued", "pending", "running", "retry_wait", "preparing", "producing"}
        if not jobs or any(job.status in active_statuses for job in jobs):
            return
        await _notify_batch_completed(
            container.notification_repository,
            batch_id,
            jobs[0].request.brand,
            [_job_item_response(job) for job in jobs],
        )

    async def execute_selected_sku(batch_id, request, snapshot_ids) -> None:
        if not container.creative_automation_storage.shared_across_processes:
            raise RuntimeError("Celery Creative automation requires shared object storage")
        job = await container.creative_automation_job_repository.get_job(request.request_id)
        if job is None:
            raise ValueError("Creative automation job is missing")
        started_at = datetime.now(UTC)
        await record_automation_step_latency(
            container.creative_automation_job_repository,
            request.request_id,
            step="queue_wait",
            outcome="succeeded",
            started_at=job.created_at,
            completed_at=started_at,
        )
        running = replace(job, status="running", updated_at=started_at)
        await container.creative_automation_job_repository.save_job(
            running,
            CreativeAutomationEvent(
                event_id=(
                    f"automation-event:{request.request_id}:running:{started_at.isoformat()}"
                ),
                job_id=request.request_id,
                event_type="status:running",
                payload={"status": "running", "batch_id": batch_id},
                created_at=started_at,
            ),
        )
        try:
            snapshots = []
            async with measure_automation_step(
                container.creative_automation_job_repository,
                request.request_id,
                "snapshot_loading",
            ):
                for snapshot_id in snapshot_ids:
                    snapshot = await container.data_source_repository.get_snapshot(snapshot_id)
                    if snapshot is None:
                        raise ValueError("Pinned Creative source snapshots are unavailable")
                    snapshots.append(snapshot)
            orchestration_config = load_orchestration_config(settings.orchestration_config_path)
            orchestrator = (
                FakeCreativeAutomationOrchestrator(orchestration_config)
                if orchestration_config.backend == "fake"
                else BamlCreativeAutomationOrchestrator(
                    orchestration_config,
                    api_key=settings.credential(orchestration_config.api_key_env),
                    usage_tracker=container.ai_usage_tracker,
                    image_provider_descriptor=managed_media.providers.image_descriptor(
                        request.image_provider_id
                    ),
                    video_provider_descriptor=managed_media.providers.video_descriptor(),
                    image_reader=managed_media.source_resolver.read_frozen_source,
                )
            )
            await _process_automation_request(
                request=request,
                batch_id=batch_id,
                snapshots=snapshots,
                compiler=MarketingCreativeAutomationCompiler(CreativeSourceContextCompiler()),
                orchestrator=orchestrator,
                intake=container.intake(),
                providers=managed_media.providers,
                jobs=container.creative_automation_job_repository,
                feedback=container.feedback(),
                knowledge=container.creative_knowledge_service,
                notifications=container.notification_repository,
                states=container.creative_automation_state_repository,
                storage=container.creative_automation_storage,
                settings=settings,
                producer=managed_media.producer,
                source_resolver=managed_media.source_resolver,
                usage_tracker=container.ai_usage_tracker,
            )
        except SourceReadError as error:
            await record_automation_total_latency(
                container.creative_automation_job_repository,
                request.request_id,
                outcome="failed",
            )
            if error.code in {
                "INVALID_CONFIGURATION",
                "MALFORMED_RESPONSE",
                "RESOURCE_NOT_FOUND",
            }:
                raise ValueError(f"Pinned Shopify product source read failed: {error}") from error
            raise
        except Exception:
            await record_automation_total_latency(
                container.creative_automation_job_repository,
                request.request_id,
                outcome="failed",
            )
            raise
        await notify_batch_if_complete(batch_id)

    async def execute_generate_again(request_id: str, generation_request_id: str) -> None:
        if not container.creative_automation_storage.shared_across_processes:
            raise RuntimeError("Celery Creative automation requires shared object storage")
        state = await resolve_state_repository_call(
            container.creative_automation_state_repository.get(request_id)
        )
        if state is None:
            raise ValueError("Creative automation state is missing")
        generation_request = next(
            (
                item
                for item in state.generation_requests
                if item.generation_request_id == generation_request_id
            ),
            None,
        )
        if generation_request is None:
            raise ValueError("Generate Again request is missing")
        if any(
            item.generation_request_id == generation_request_id for item in state.production_assets
        ):
            await _persist_state_job_projection(
                container.creative_automation_job_repository,
                container.notification_repository,
                state,
            )
            return
        if state.generation_requests[-1].generation_request_id != generation_request_id:
            raise ValueError("Generate Again command is stale")
        if state.status == MarketingCreativeAutomationStatus.PRODUCING:
            interrupted = record_production_outcome(
                state,
                (),
                error_code="CREATIVE_GENERATION_WORKER_INTERRUPTED",
                error_detail=(
                    "Generate Again stopped after production started; request another version "
                    "explicitly to avoid duplicate provider output."
                ),
            )
            await resolve_state_repository_call(
                container.creative_automation_state_repository.save(interrupted)
            )
            await _persist_state_job_projection(
                container.creative_automation_job_repository,
                container.notification_repository,
                interrupted,
            )
            return
        if state.status != MarketingCreativeAutomationStatus.AWAITING_GENERATION_PROVIDER:
            raise ValueError("Creative automation is not ready for Generate Again")
        package = await container.creative_automation_storage.read_package(
            request_id,
            state.package_ref,
        )
        if package is None:
            raise ValueError("Creative package is unavailable")
        try:
            produced = await managed_media.producer.produce(package)
        except Exception:
            current = await resolve_state_repository_call(
                container.creative_automation_state_repository.get(request_id)
            )
            if current is not None:
                await _persist_state_job_projection(
                    container.creative_automation_job_repository,
                    container.notification_repository,
                    current,
                )
            raise
        await _persist_state_job_projection(
            container.creative_automation_job_repository,
            container.notification_repository,
            produced,
        )

    async def record_selected_sku_retry(batch_id, request, error_code) -> None:
        job = await container.creative_automation_job_repository.get_job(request.request_id)
        if job is None:
            return
        timestamp = datetime.now(UTC)
        retrying = replace(job, status="retry_wait", updated_at=timestamp)
        await container.creative_automation_job_repository.save_job(
            retrying,
            CreativeAutomationEvent(
                event_id=(
                    f"automation-event:{request.request_id}:retry_wait:{timestamp.isoformat()}"
                ),
                job_id=request.request_id,
                event_type="status:retry_wait",
                payload={
                    "status": "retry_wait",
                    "batch_id": batch_id,
                    "error_code": error_code,
                },
                created_at=timestamp,
            ),
        )

    async def record_selected_sku_failure(batch_id, request, error_code) -> None:
        job = await container.creative_automation_job_repository.get_job(request.request_id)
        if job is None:
            return
        timestamp = datetime.now(UTC)
        detail = "Creative automation worker could not complete this SKU job."
        failed = replace(
            job,
            status="failed",
            issues=(*job.issues, CreativeAutomationJobIssue(error_code, detail)),
            updated_at=timestamp,
        )
        await container.creative_automation_job_repository.save_job(
            failed,
            CreativeAutomationEvent(
                event_id=f"automation-event:{request.request_id}:failed:{error_code}",
                job_id=request.request_id,
                event_type="status:failed",
                payload={"status": "failed", "error_code": error_code},
                created_at=timestamp,
            ),
        )
        await _notify_job_result(
            container.notification_repository,
            _job_item_response(failed),
        )
        await notify_batch_if_complete(batch_id)

    automation_dispatcher = CreativeAutomationCommandDispatcher(
        execute_selected_sku,
        execute_generate_again=execute_generate_again,
        on_failure=record_selected_sku_failure,
        on_retry=record_selected_sku_retry,
    )
    research_artifacts = ResearchCrawlArtifactWriter(
        container.artifacts, container.artifact_service
    )
    research_screener = _build_research_screener(
        settings,
        container.ai_usage_tracker,
        research_artifacts,
    )
    research_dispatcher = ResearchCrawlCommandDispatcher(
        ResearchCrawlService(
            container.research_crawl_repository,
            ScraplingCrawler(
                timeout_seconds=settings.research_crawl_timeout_seconds,
                navigator=(
                    JevBrowserNavigator(
                        settings.credential("JEV_API_KEY") or "",
                        model=settings.jev_navigation_model,
                        endpoint=settings.jev_api_url,
                    )
                    if settings.credential("JEV_API_KEY") and settings.jev_api_url
                    else None
                ),
            ),
            research_artifacts,
            ResearchMediaCapturer(research_artifacts),
            ResearchBrandContextResolver(container.data_source_repository),
            screener=research_screener,
        )
    )
    data_source_runtime = build_data_source_runtime(
        load_data_sources_config(settings.data_sources_config),
        settings.data_root / "state.db",
        settings.data_root / "artifacts",
        shopify_token=_secret_value(settings.shopify_access_token),
        shopify_source_tokens={
            "shopify-demohome-products": _secret_value(settings.shopify_demohome_access_token),
            "shopify-demofurn-products": _secret_value(settings.shopify_demofurn_access_token),
        },
        shopify_source_client_credentials={
            "shopify-demohome-products": (
                settings.shopify_demohome_client_id,
                _secret_value(settings.shopify_demohome_client_secret),
            ),
            "shopify-demofurn-products": (
                settings.shopify_demofurn_client_id,
                _secret_value(settings.shopify_demofurn_client_secret),
            ),
        },
        lark_token=_secret_value(settings.lark_tenant_access_token),
        lark_app_id=settings.lark_app_id,
        lark_app_secret=_secret_value(settings.lark_app_secret),
        google_token=_secret_value(settings.google_access_token),
        meta_token=_secret_value(settings.meta_access_token),
        google_ads_token=_secret_value(settings.google_ads_access_token),
        google_ads_client_id=settings.google_ads_client_id,
        google_ads_client_secret=_secret_value(settings.google_ads_client_secret),
        google_ads_refresh_token=_secret_value(settings.google_ads_refresh_token),
        google_ads_developer_token=_secret_value(settings.google_ads_developer_token),
        google_ads_login_customer_id=settings.google_ads_login_customer_id,
        pinterest_token=_secret_value(settings.pinterest_access_token),
        google_merchant_token=_secret_value(settings.google_merchant_access_token),
        klaviyo_api_key=_secret_value(settings.klaviyo_api_key),
        timeout_seconds=settings.data_source_timeout_seconds,
        repository=container.data_source_repository,
        artifact_service=container.artifact_service,
    )
    dispatcher = _CompositeCommandDispatcher(
        loop_dispatcher,
        automation_dispatcher,
        research_dispatcher,
        DataSourceCommandDispatcher(data_source_runtime),
    )
    task_id = execute_command.request.id or f"celery-{command_id}"
    worker_id = f"{execute_command.request.hostname or 'celery-worker'}:{task_id}"
    try:
        claimed = await container.execution_status_store.claim_command(
            command_id,
            dispatch_generation,
            worker_id,
            lease_seconds=settings.celery_command_lease_seconds,
        )
        if claimed is not None and claimed.status == CommandStatus.RUNNING:
            outcome = await ExecutionWorker(
                container.execution_status_store,
                dispatcher,
                worker_id,
                lease_seconds=settings.celery_command_lease_seconds,
                retry_delay_seconds=settings.celery_retry_delay_seconds,
            ).run_claimed(claimed)
            command = await container.execution_status_store.get(command_id)
            if command is None:
                raise RuntimeError("Execution command disappeared after dispatch")
            await _reconcile_failed_selected_sku_command(
                command,
                container.creative_automation_job_repository,
                record_selected_sku_failure,
            )
            return outcome.status, _retry_after(
                command, settings.celery_retry_poll_interval_seconds
            )
        command = claimed or await container.execution_status_store.get(command_id)
        if command is None:
            raise RuntimeError("Execution command not found")
        if command.dispatch_generation != dispatch_generation:
            logger.info(
                "Ignoring stale Celery task for command {} generation {}",
                command_id,
                dispatch_generation,
            )
            return CommandStatus.CANCELLED, 0
        await _reconcile_failed_selected_sku_command(
            command,
            container.creative_automation_job_repository,
            record_selected_sku_failure,
        )
        return command.status, _retry_after(command, settings.celery_retry_poll_interval_seconds)
    finally:
        container.close()
        await database.close()


def _legacy_semantic_review_config_path(
    review_config_path: Path | None,
    image_config: ImageBackendConfig | None,
) -> Path | None:
    """Enable semantic review only when its legacy image workflow is configured."""
    if review_config_path is not None and image_config is None:
        logger.warning(
            "Ignoring semantic review configuration because no legacy image configuration is active"
        )
        return None
    return review_config_path


def _build_research_screener(
    settings: ApplicationSettings,
    usage_tracker,
    artifact_reader: ResearchCrawlArtifactWriter,
) -> NineRouterResearchScreener | None:
    if settings.research_screening_config is None:
        return None
    try:
        config = load_research_screening_config(settings.research_screening_config)
    except (OSError, ValueError) as error:
        logger.error(
            "Research analysis unavailable because its configuration is invalid: {}", error
        )
        return None
    api_key = settings.credential(config.api_key_env)
    if not api_key:
        logger.error(
            "Research analysis unavailable because {} is not configured", config.api_key_env
        )
        return None
    return NineRouterResearchScreener(
        config,
        api_key=api_key,
        usage_tracker=usage_tracker,
        artifact_reader=artifact_reader,
    )


class _CompositeCommandDispatcher:
    def __init__(
        self,
        loop_dispatcher,
        automation_dispatcher,
        research_dispatcher,
        data_source_dispatcher,
    ) -> None:
        self._loop_dispatcher = loop_dispatcher
        self._automation_dispatcher = automation_dispatcher
        self._research_dispatcher = research_dispatcher
        self._data_source_dispatcher = data_source_dispatcher

    async def dispatch(self, command) -> None:
        if command.name in {
            CreativeAutomationCommandName.PROCESS_SKU.value,
            CreativeAutomationCommandName.GENERATE_AGAIN.value,
        }:
            await self._automation_dispatcher.dispatch(command)
            return
        if command.name == ResearchCrawlCommandName.CRAWL_URL.value:
            await self._research_dispatcher.dispatch(command)
            return
        if command.name == DataSourceCommandName.SYNC.value:
            await self._data_source_dispatcher.dispatch(command)
            return
        await self._loop_dispatcher.dispatch(command)


def _secret_value(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def _retry_after(command, max_poll_interval_seconds: int) -> int:
    target = command.available_at
    if (
        command.status in {CommandStatus.RUNNING, CommandStatus.CANCEL_REQUESTED}
        and command.lease_expires_at is not None
    ):
        target = command.lease_expires_at
    delay = max(1, math.ceil((target - datetime.now(UTC)).total_seconds()))
    return min(delay, max_poll_interval_seconds)


async def _reconcile_failed_selected_sku_command(
    command: ExecutionCommand,
    jobs: ICreativeAutomationJobRepository,
    on_failure: Callable[[str, MarketingCreativeAutomationRequest, str], Awaitable[None]],
) -> None:
    if (
        command.name != CreativeAutomationCommandName.PROCESS_SKU.value
        or command.status != CommandStatus.FAILED
        or command.workflow_run_id is None
    ):
        return
    job = await jobs.get_job(command.workflow_run_id)
    if (
        job is None
        or job.command_id != command.command_id
        or job.status not in {"pending", "running", "retry_wait"}
    ):
        return
    await on_failure(
        job.batch_id,
        job.request,
        command.last_error_code or "CREATIVE_AUTOMATION_COMMAND_FAILED",
    )


__all__ = ["execute_command"]
