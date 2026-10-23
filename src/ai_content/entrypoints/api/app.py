"""FastAPI application for the Creative pilot dashboard."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_content.domains.marketing.creative.adapters.mock_meta_ads import (
    MOCK_META_PROVIDER_ID,
    MockMetaAdsActivationProvider,
)
from ai_content.domains.marketing.creative.application.ads_provider_registry import (
    AdsActivationProviderRegistry,
)
from ai_content.domains.marketing.creative.bootstrap import CreativeRuntime
from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJob,
    CreativeJobId,
    CreativeJobStatus,
)
from ai_content.domains.marketing.creative_feedback.adapters.serialization import (
    run_to_dict as creative_feedback_to_dict,
)
from ai_content.domains.marketing.creative_feedback.bootstrap import CreativeFeedbackRuntime
from ai_content.domains.marketing.creative_intake.adapters.artifacts import (
    write_creative_intake_artifacts,
)
from ai_content.domains.marketing.creative_intake.adapters.serialization import (
    run_to_dict as creative_intake_to_dict,
)
from ai_content.domains.marketing.creative_intake.bootstrap import CreativeIntakeRuntime
from ai_content.domains.marketing.creative_intake.domain.models import HandoffState
from ai_content.domains.marketing.creative_loop.adapters.commands import (
    CreativeLoopCommandService,
)
from ai_content.domains.marketing.creative_loop.bootstrap import CreativeLoopRuntime
from ai_content.domains.marketing.creative_loop.domain.models import (
    CreativeLoopRun,
    CreativeLoopState,
)
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    PerformanceDecisionRuntime,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    CreativeDemandPreview,
    ExperimentProposal,
    OpportunityCategory,
    PerformanceDecisionRun,
)
from ai_content.platform.artifacts import (
    ArtifactRecord,
    ArtifactService,
    ArtifactStatus,
    ObjectStorageError,
)
from ai_content.platform.artifacts.object_storage import iter_download, normalize_object_key
from ai_content.platform.execution import (
    CommandPayloadDriftError,
    CommandScheduler,
    CommandStatus,
    CommandStatusStore,
    ExecutionCommand,
    resolve_queue_call,
)
from ai_content.platform.observability import (
    READINESS,
    HttpObservabilityMiddleware,
    configure_observability,
    instrument_fastapi,
    metrics_asgi_app,
    set_span_attributes,
)
from ai_content.settings import ApplicationSettings

from .ai_usage import router as ai_usage_router
from .creative_automation import router as creative_automation_router
from .creative_knowledge import router as creative_knowledge_router
from .dashboard import router as dashboard_router
from .data_sources import router as data_sources_router
from .dependencies import (
    ApiRuntimeSettings,
    check_runtime_readiness_async,
    get_command_scheduler,
    get_command_status_store,
    get_creative_feedback_runtime,
    get_creative_intake_runtime,
    get_creative_loop_runtime,
    get_gmc_repository,
    get_performance_decision_runtime,
    get_runtime,
    get_runtime_settings,
    lifespan,
)
from .media_assets import router as media_assets_router
from .notifications import router as notifications_router
from .research_crawler import library_router as research_library_router
from .research_crawler import router as research_crawler_router
from .schemas.artifacts import ArtifactResponse
from .schemas.creative import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ExceptionItemResponse,
    ExceptionListResponse,
    HealthResponse,
    JobDetailResponse,
    JobListResponse,
    JobSummaryResponse,
    JobVersionResponse,
    LineageResponse,
)
from .schemas.creative_feedback import (
    CreativeFeedbackDecisionRequest,
    CreativeFeedbackRunListResponse,
    CreativeFeedbackRunResponse,
    FeedbackLessonResponse,
    NextCreativeTaskPreviewResponse,
)
from .schemas.creative_intake import (
    CreativeIntakeIssueResponse,
    CreativeIntakeRunListResponse,
    CreativeIntakeRunResponse,
    CreativePipelineResponse,
)
from .schemas.creative_loop import (
    CreativeLoopAdsOutcomeRequest,
    CreativeLoopCreativeDecisionRequest,
    CreativeLoopDemandDecisionRequest,
    CreativeLoopLessonDecisionRequest,
    CreativeLoopRunListResponse,
    CreativeLoopRunResponse,
    CreativeLoopTimelineResponse,
    CreativeLoopTimelineStepResponse,
)
from .schemas.execution import (
    CommandAcceptedResponse,
    CreativeLoopStartCommandRequest,
    ExecutionCommandListResponse,
    ExecutionCommandResponse,
)
from .schemas.performance_data import GmcRunIssueResponse, GmcRunListResponse, GmcRunResponse
from .schemas.performance_decisions import (
    CreativeDemandPreviewResponse,
    CreativeOpportunityResponse,
    ExperimentProposalData,
    PerformanceCriterionResponse,
    PerformanceDecisionRequestBody,
    PerformanceDecisionRunListResponse,
    PerformanceDecisionRunResponse,
    PerformanceMetricResponse,
    PerformanceRuleAssessmentResponse,
)

_APPLICATION_SETTINGS = ApplicationSettings()
_OBSERVABILITY_SETTINGS = _APPLICATION_SETTINGS.observability("aicontent-api")
_OBSERVABILITY_RUNTIME = configure_observability(_OBSERVABILITY_SETTINGS)

app = FastAPI(
    title="AI Content Automation Marketing Pilot API",
    version="0.1.0",
    description="APIs for supervised Marketing automation pilots.",
    lifespan=lifespan,
)
app.state.observability_settings = _OBSERVABILITY_SETTINGS
app.state.observability_runtime = _OBSERVABILITY_RUNTIME
app.state.ads_activation_provider_registry = AdsActivationProviderRegistry(
    (MockMetaAdsActivationProvider(),),
    default_provider_ids={"meta": MOCK_META_PROVIDER_ID},
)
app.add_middleware(
    HttpObservabilityMiddleware,
    service_name=_OBSERVABILITY_SETTINGS.service_name,
)
app.mount("/internal/metrics", metrics_asgi_app(), name="internal-metrics")
app.include_router(creative_automation_router)
app.include_router(creative_knowledge_router)
app.include_router(notifications_router)
app.include_router(research_crawler_router)
app.include_router(research_library_router)


def _configure_cors(application: FastAPI) -> None:
    """Allow local browser origin access during dashboard development."""
    allow_origins = [
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    allow_pattern = _APPLICATION_SETTINGS.cors_allow_origin
    if allow_pattern:
        allow_origins.append(allow_pattern)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )


def _settings() -> ApiRuntimeSettings:
    return get_runtime_settings()


def _artifact_service(request: Request) -> ArtifactService | None:
    container = getattr(request.app.state, "postgres_runtime", None)
    return container.artifact_service if container is not None else None


def _artifact_response(record: ArtifactRecord) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=record.artifact_id,
        kind=record.kind.value,
        status=record.status.value,
        source_path=record.source_path,
        sha256=record.sha256,
        size_bytes=record.size_bytes,
        content_type=record.content_type,
        retention_class=record.retention_class.value,
        owner_type=record.owner_type,
        owner_id=record.owner_id,
        brand_scope=record.brand_scope,
        created_at=record.created_at,
        content_url=f"/api/v1/artifacts/{record.artifact_id}/content",
    )


def _parse_range(value: str | None, size: int) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("Only one bytes range is supported")
    start_raw, separator, end_raw = value[6:].partition("-")
    if not separator or (not start_raw and not end_raw):
        raise ValueError("Invalid Range header")
    if not start_raw:
        length = int(end_raw)
        if length <= 0:
            raise ValueError("Invalid suffix byte range")
        return max(size - length, 0), size - 1
    start = int(start_raw)
    return start, int(end_raw) if end_raw else None


async def _object_response(
    service: ArtifactService,
    record: ArtifactRecord,
    range_header: str | None,
    *,
    immutable: bool,
) -> StreamingResponse:
    if record.status != ArtifactStatus.AVAILABLE:
        raise HTTPException(status_code=404, detail="Artifact is not available")
    try:
        start, end = _parse_range(range_header, record.size_bytes)
        context = service.storage.open(record.object_key, start=start, end=end)
        download = await asyncio.to_thread(context.__enter__)
    except (ValueError, ObjectStorageError) as error:
        status_code = 416 if isinstance(error, ValueError) else 503
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    def content() -> Iterator[bytes]:
        try:
            yield from iter_download(download)
        finally:
            context.__exit__(None, None, None)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(download.content_length),
        "ETag": f'"{record.sha256}"',
        "X-Artifact-ID": record.artifact_id,
        "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache",
    }
    if download.content_range is not None:
        headers["Content-Range"] = download.content_range
    return StreamingResponse(
        content(),
        status_code=206 if download.content_range is not None else 200,
        media_type=record.content_type,
        headers=headers,
    )


@app.get("/api/v1/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(artifact_id: str, request: Request) -> ArtifactResponse:
    service = _artifact_service(request)
    if service is None:
        raise HTTPException(status_code=404, detail="Artifact catalog is not configured")
    record = await service.catalog.get(artifact_id)
    if record is None or record.status != ArtifactStatus.AVAILABLE:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_response(record)


@app.get("/api/v1/artifacts/{artifact_id}/content")
async def get_artifact_content(artifact_id: str, request: Request) -> StreamingResponse:
    service = _artifact_service(request)
    if service is None:
        raise HTTPException(status_code=404, detail="Artifact catalog is not configured")
    record = await service.catalog.get(artifact_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return await _object_response(
        service,
        record,
        request.headers.get("range"),
        immutable=True,
    )


@app.get("/artifacts/{source_path:path}", response_model=None)
async def get_legacy_artifact(
    source_path: str, request: Request
) -> FileResponse | StreamingResponse:
    """Resolve a legacy path to the latest immutable object during migration."""
    settings = _settings()
    service = _artifact_service(request)
    if service is not None:
        try:
            normalized = normalize_object_key(source_path)
            record = await service.catalog.latest_available(normalized)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if record is not None:
            return await _object_response(
                service,
                record,
                request.headers.get("range"),
                immutable=False,
            )
    try:
        root = settings.artifacts_root.resolve()
        path = root.joinpath(source_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Artifact path escapes configured root")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)


def _decimal_to_str(value) -> str | None:
    return None if value is None else str(value)


def _time_to_str(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _safe_artifact_url(
    artifacts_root: Path, raw_url: str | None, raw_path: str | None
) -> str | None:
    """Resolve artifact URL path for UI preview."""
    if raw_url and raw_url.startswith(("http://", "https://")):
        return raw_url

    source = raw_path or raw_url
    if not source:
        return None

    if source.startswith("fake://"):
        return None

    path = Path(source)
    if not path.is_absolute():
        normalized_source = source.replace("\\", "/")
        return f"/artifacts/{normalized_source}"

    try:
        rel = path.resolve().relative_to(artifacts_root.resolve())
        return f"/artifacts/{rel.as_posix()}"
    except ValueError:
        return None


def _to_job_summary(job) -> JobSummaryResponse:
    latest_version = job.latest_version
    display_source = job.card.candidate_summary if job.card else None
    return JobSummaryResponse(
        job_id=job.job_id.value,
        source_run_id=job.source_run_id,
        status=job.status.value,
        idea_id=job.idea_id,
        context_ref=job.context_ref,
        total_cost=_decimal_to_str(job.total_cost.amount) + " " + job.total_cost.currency
        if job.total_cost is not None
        else None,
        version_count=len(job.versions),
        latest_version=latest_version.version_id.value if latest_version else None,
        latest_score=_decimal_to_str(latest_version.qa_score) if latest_version else None,
        pending_approval=job.card is not None and job.card.decision is None,
        display_title=display_source or job.source_run_id or job.job_id.value,
        thumbnail_web_url=_safe_artifact_url(
            _settings().artifacts_root,
            latest_version.artifact_url if latest_version else None,
            latest_version.artifact_path if latest_version else None,
        ),
    )


def _to_version_response(
    settings: ApiRuntimeSettings,
    version,
) -> JobVersionResponse:
    artifact_web_url = _safe_artifact_url(
        settings.artifacts_root, version.artifact_url, version.artifact_path
    )
    return JobVersionResponse(
        version_id=version.version_id.value,
        attempt_number=version.attempt_number,
        creative_set_id=version.creative_set_id,
        variation_id=version.variation_id,
        variation_attempt_number=version.variation_attempt_number,
        artifact_url=version.artifact_url,
        artifact_path=version.artifact_path,
        artifact_web_url=artifact_web_url,
        review_context_web_url=(
            f"{artifact_web_url.rsplit('/', 1)[0]}/review.json"
            if artifact_web_url and artifact_web_url.startswith("/artifacts/images/")
            else None
        ),
        cost=_decimal_to_str(version.cost.amount) + " " + version.cost.currency
        if version.cost is not None
        else None,
        input_ref=version.input_ref,
        input_hash=version.input_hash,
        prompt_version=version.prompt_version,
        rubric_version=version.rubric_version,
        policy_version=version.policy_version,
        workflow_version=version.workflow_version,
        generator_version=version.generator_version,
        qa_passed=version.qa_passed,
        qa_score=_decimal_to_str(version.qa_score),
        qa_issues=list(version.qa_issues),
        qa_warnings=list(version.qa_warnings),
        qa_feedback=version.qa_feedback,
        qa_outcome=version.qa_outcome.value if version.qa_outcome else None,
        qa_retryable=version.qa_retryable,
        qa_requires_human_review=version.qa_requires_human_review,
        qa_repair_actions=[item.value for item in version.qa_repair_actions],
        qa_evidence_refs=list(version.qa_evidence_refs),
        qa_reviewer_version=version.qa_reviewer_version,
        created_at=_time_to_str(version.created_at),
    )


def _to_lineage(item) -> LineageResponse:
    return LineageResponse(
        entry_type=item.entry_type,
        ref=item.ref,
        parent_ref=item.parent_ref,
        details=dict(item.details),
        recorded_at=_time_to_str(item.recorded_at) or "",
    )


def _to_job_detail_response(
    job: CreativeJob,
    *,
    brief_artifact_id: str | None = None,
    brief_web_url: str | None = None,
) -> JobDetailResponse:
    settings = _settings()
    versions = [_to_version_response(settings, version) for version in job.versions]
    lineage = [_to_lineage(item) for item in job.lineage]
    card = None
    if job.card is not None:
        card = {
            "work_item_id": job.card.work_item_id,
            "candidate_summary": job.card.candidate_summary,
            "final_version_ref": job.card.final_version_ref,
            "final_version_refs": list(job.card.final_version_refs),
            "thumbnail_ref": job.card.thumbnail_ref,
            "thumbnail_web_url": _safe_artifact_url(
                settings.artifacts_root,
                job.card.thumbnail_ref,
                job.card.thumbnail_ref,
            ),
            "warnings": list(job.card.warnings),
            "score": _decimal_to_str(job.card.score),
            "evidence_refs": list(job.card.evidence_refs),
            "decision": job.card.decision.value if job.card.decision else None,
            "reviewer_id": job.card.reviewer_id,
            "decided_at": _time_to_str(job.card.decided_at),
            "reason": job.card.reason,
        }
    return JobDetailResponse(
        job_id=job.job_id.value,
        source_run_id=job.source_run_id,
        status=job.status.value,
        context_ref=job.context_ref,
        idea_id=job.idea_id,
        brief_ref=job.brief_ref,
        brief_artifact_id=brief_artifact_id,
        brief_web_url=brief_web_url,
        preparation_hash=job.preparation_hash,
        creative_set_id=job.creative_set_id,
        total_cost=(
            _decimal_to_str(job.total_cost.amount) + " " + job.total_cost.currency
            if job.total_cost is not None
            else None
        ),
        versions=versions,
        card=card,
        audit_count=len(job.audit_log),
        lineage=lineage,
    )


async def _brief_artifact_reference(
    request: Request,
    job: CreativeJob,
) -> tuple[str | None, str | None]:
    web_url = _safe_artifact_url(_settings().artifacts_root, None, job.brief_ref)
    service = _artifact_service(request)
    if service is None or job.brief_ref is None:
        return None, web_url
    record = await service.catalog.latest_available(normalize_object_key(job.brief_ref))
    if record is None:
        return None, web_url
    return record.artifact_id, f"/api/v1/artifacts/{record.artifact_id}/content"


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report process liveness without touching external dependencies."""
    return HealthResponse(checks={"process": "ok"})


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    """Report whether local config, storage and selected database are usable."""
    container = getattr(request.app.state, "postgres_runtime", None)
    database = container.database if container is not None else None
    object_storage = (
        container.artifact_service.storage
        if container is not None and container.artifact_service is not None
        else None
    )
    readiness = await check_runtime_readiness_async(_settings(), database, object_storage)
    for dependency, value in readiness.checks.items():
        READINESS.labels(
            service=_OBSERVABILITY_SETTINGS.service_name,
            dependency=dependency,
        ).set(value == "ok")
    response = HealthResponse(
        status="ok" if readiness.ready else "not_ready",
        checks=readiness.checks,
    )
    if readiness.ready:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )


def _to_gmc_run_response(run) -> GmcRunResponse:
    return GmcRunResponse(
        run_id=run.run_id,
        source_run_id=run.specification.source_run_id,
        brand_id=run.specification.brand_id,
        store_id=run.specification.store_id,
        status=run.status.value,
        source_ref=run.source.source_ref,
        source_checksum_sha256=run.source.checksum_sha256,
        source_size_bytes=run.source.size_bytes,
        schema_version=run.specification.schema_version,
        mapping_version=run.specification.mapping_version,
        total_rows=run.total_rows,
        accepted_rows=run.accepted_rows,
        rejected_rows=run.rejected_rows,
        matched_rows=run.matched_rows,
        gmc_only_rows=run.gmc_only_rows,
        conflicting_rows=run.conflicting_rows,
        duplicate_rows=run.duplicate_rows,
        normalized_artifact_ref=run.normalized_artifact_ref,
        rejected_artifact_ref=run.rejected_artifact_ref,
        normalized_checksum_sha256=run.normalized_checksum_sha256,
        rejected_checksum_sha256=run.rejected_checksum_sha256,
        created_at=run.created_at.isoformat(),
        issues=[
            GmcRunIssueResponse(
                code=issue.code,
                severity=issue.severity.value,
                detail=issue.detail,
                source_ref=issue.source_ref,
            )
            for issue in run.issues
        ],
    )


@app.get("/api/v1/performance/gmc/runs", response_model=GmcRunListResponse)
async def list_gmc_runs(repository=Depends(get_gmc_repository)) -> GmcRunListResponse:
    runs = await repository.list()
    items = [_to_gmc_run_response(run) for run in runs]
    return GmcRunListResponse(items=items, total=len(items))


@app.get("/api/v1/performance/gmc/runs/{run_id}", response_model=GmcRunResponse)
async def get_gmc_run(run_id: str, repository=Depends(get_gmc_repository)) -> GmcRunResponse:
    run = await repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GMC run not found.")
    return _to_gmc_run_response(run)


def _to_creative_demand_preview(
    preview: CreativeDemandPreview,
) -> CreativeDemandPreviewResponse:
    return CreativeDemandPreviewResponse(
        preview_id=preview.preview_id,
        state=preview.state.value,
        source_decision_run_id=preview.source_decision_run_id,
        source_evaluation_id=preview.source_evaluation_id,
        brand_id=preview.brand_id,
        sku_id=preview.sku_id,
        objective=preview.objective,
        channel=preview.channel,
        action=preview.action.value,
        classification=preview.classification.value,
        evidence_refs=list(preview.evidence_refs),
        missing_context=list(preview.missing_context),
    )


def _to_creative_feedback_response(run) -> CreativeFeedbackRunResponse:
    return CreativeFeedbackRunResponse.model_validate(creative_feedback_to_dict(run))


def _to_creative_intake_response(run) -> CreativeIntakeRunResponse:
    return CreativeIntakeRunResponse.model_validate(creative_intake_to_dict(run))


def _to_creative_loop_response(run: CreativeLoopRun) -> CreativeLoopRunResponse:
    return CreativeLoopRunResponse(
        run_id=run.run_id,
        source_run_id=run.source_run_id,
        input_snapshot_id=run.input_snapshot_id,
        context_snapshot_id=run.context_snapshot_id,
        state=run.state.value,
        initial_performance_run_id=run.initial_performance_run_id,
        initial_evaluation_id=run.initial_evaluation_id,
        initial_intake_run_id=run.initial_intake_run_id,
        creative_job_id=run.creative_job_id,
        approved_creative_version_id=run.approved_creative_version_id,
        ads_event_id=run.ads_event_id,
        post_ads_performance_run_id=run.post_ads_performance_run_id,
        feedback_run_id=run.feedback_run_id,
        lesson_id=run.lesson_id,
        next_intake_run_id=run.next_intake_run_id,
        next_creative_job_id=run.next_creative_job_id,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        audit_log=list(run.audit_log),
    )


def _to_execution_command_response(command: ExecutionCommand) -> ExecutionCommandResponse:
    return ExecutionCommandResponse(
        command_id=command.command_id,
        name=command.name,
        workflow_run_id=command.workflow_run_id,
        status=command.status.value,
        attempts=command.attempts,
        max_attempts=command.max_attempts,
        created_at=command.created_at.isoformat(),
        updated_at=command.updated_at.isoformat(),
        available_at=command.available_at.isoformat(),
        lease_expires_at=_time_to_str(command.lease_expires_at),
        last_error_code=command.last_error_code,
        last_error_message=command.last_error_message,
        completed_at=_time_to_str(command.completed_at),
        execution_backend=command.execution_backend.value,
        queue_name=command.queue_name,
        dispatch_generation=command.dispatch_generation,
        execution_id=command.execution_id,
        started_at=_time_to_str(command.started_at),
        cancel_requested_at=_time_to_str(command.cancel_requested_at),
        cancelled_at=_time_to_str(command.cancelled_at),
        audit_log=list(command.audit_log),
    )


def _accepted(command: ExecutionCommand, created: bool) -> CommandAcceptedResponse:
    set_span_attributes(
        **{
            "aic.command.id": command.command_id,
            "aic.command.name": command.name,
            "aic.workflow.run_id": command.workflow_run_id,
            "aic.execution.id": command.execution_id,
        }
    )
    return CommandAcceptedResponse(command=_to_execution_command_response(command), created=created)


def _creative_loop_timeline(run: CreativeLoopRun) -> list[CreativeLoopTimelineStepResponse]:
    audit = " ".join(run.audit_log)
    return [
        CreativeLoopTimelineStepResponse(
            key="performance-demand",
            label="H2 Performance demand",
            status="completed",
            reference=run.initial_performance_run_id,
            detail=f"Exact evaluation {run.initial_evaluation_id}",
        ),
        CreativeLoopTimelineStepResponse(
            key="demand-approval",
            label="Demand approval",
            status=(
                "awaiting_approval"
                if run.state.value == "awaiting_demand_approval"
                else "rejected"
                if "demand:rejected" in audit
                else "deferred"
                if "demand:deferred" in audit
                else "completed"
            ),
            reference=run.initial_evaluation_id,
            detail="Pins the exact H2 evaluation before Creative production starts.",
        ),
        CreativeLoopTimelineStepResponse(
            key="creative-production",
            label="M3/M4 context -> M1 brief -> M2 QA",
            status=(
                "completed"
                if run.creative_job_id
                else "blocked"
                if run.state.value in {"needs_evidence", "blocked_conflict"}
                else "pending"
            ),
            reference=run.creative_job_id or run.initial_intake_run_id,
            detail="Versioned context, bounded revision and exact Creative Set lineage.",
        ),
        CreativeLoopTimelineStepResponse(
            key="creative-approval",
            label="Final Creative approval",
            status=(
                "completed"
                if run.approved_creative_version_id
                else "awaiting_approval"
                if run.state.value == "awaiting_creative_approval"
                else "rejected"
                if "creative:rejected" in audit
                else "pending"
            ),
            reference=run.approved_creative_version_id,
            detail="Approval applies only to the pinned QA-passing version.",
        ),
        CreativeLoopTimelineStepResponse(
            key="ads-outcome",
            label="Ads outcome event",
            status=(
                "completed"
                if run.ads_event_id
                else "awaiting_event"
                if run.state.value == "awaiting_ads_outcome"
                else "pending"
            ),
            reference=run.ads_event_id,
            detail="External evidence event pinned to the approved Creative version.",
        ),
        CreativeLoopTimelineStepResponse(
            key="feedback-lesson",
            label="H2 evaluation -> X1 lesson",
            status=(
                "awaiting_approval"
                if run.state.value == "awaiting_lesson_approval"
                else "completed"
                if run.feedback_run_id
                else "pending"
            ),
            reference=run.lesson_id or run.feedback_run_id,
            detail="Performance stays attached to the exact tested Creative version.",
        ),
        CreativeLoopTimelineStepResponse(
            key="next-brief",
            label="Next-cycle brief",
            status="completed" if run.next_creative_job_id else "pending",
            reference=run.next_creative_job_id or run.next_intake_run_id,
            detail="The bounded pilot stops after preparing the next exact brief.",
        ),
    ]


@app.get("/api/v1/marketing/creative-loops", response_model=CreativeLoopRunListResponse)
async def list_creative_loops(
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
) -> CreativeLoopRunListResponse:
    runs = await runtime.repository.list()
    return CreativeLoopRunListResponse(
        items=[_to_creative_loop_response(run) for run in runs], total=len(runs)
    )


@app.get("/api/v1/marketing/creative-loops/{run_id}", response_model=CreativeLoopRunResponse)
async def get_creative_loop(
    run_id: str,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
) -> CreativeLoopRunResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative loop run not found")
    return _to_creative_loop_response(run)


@app.get(
    "/api/v1/marketing/creative-loops/{run_id}/timeline",
    response_model=CreativeLoopTimelineResponse,
)
async def get_creative_loop_timeline(
    run_id: str,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
) -> CreativeLoopTimelineResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative loop run not found")
    return CreativeLoopTimelineResponse(
        run=_to_creative_loop_response(run), steps=_creative_loop_timeline(run)
    )


@app.post(
    "/api/v1/marketing/creative-loops/commands/start",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_creative_loop_start(
    payload: CreativeLoopStartCommandRequest,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> CommandAcceptedResponse:
    try:
        source = runtime.fixture.case(payload.input_snapshot_id)
        command, created = await resolve_queue_call(
            CreativeLoopCommandService(queue).enqueue_start(source)
        )
    except (ValueError, CommandPayloadDriftError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _accepted(command, created)


@app.post(
    "/api/v1/marketing/creative-loops/{run_id}/demand-decision",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def decide_creative_loop_demand(
    run_id: str,
    payload: CreativeLoopDemandDecisionRequest,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> CommandAcceptedResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative loop run not found")
    dedupe_key = f"creative-loop:demand:{run.run_id}:{payload.evaluation_id}"
    if (
        run.state != CreativeLoopState.AWAITING_DEMAND_APPROVAL
        or run.initial_evaluation_id != payload.evaluation_id
    ):
        existing = await resolve_queue_call(queue.get_by_dedupe_key(dedupe_key))
        if existing is None:
            raise HTTPException(status_code=409, detail="Creative loop is not awaiting this demand")
    try:
        command, created = await resolve_queue_call(
            CreativeLoopCommandService(queue).enqueue_demand_decision(
                run,
                payload.evaluation_id,
                payload.decision,
                payload.reviewer_alias,
                payload.reason,
            )
        )
    except (ValueError, CommandPayloadDriftError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _accepted(command, created)


@app.post(
    "/api/v1/marketing/creative-loops/{run_id}/creative-decision",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def decide_creative_loop_creative(
    run_id: str,
    payload: CreativeLoopCreativeDecisionRequest,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> CommandAcceptedResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative loop run not found")
    dedupe_key = f"creative-loop:creative:{run.run_id}:{run.creative_job_id}"
    if run.state != CreativeLoopState.AWAITING_CREATIVE_APPROVAL:
        existing = await resolve_queue_call(queue.get_by_dedupe_key(dedupe_key))
        if existing is None:
            raise HTTPException(
                status_code=409, detail="Creative loop is not awaiting Creative approval"
            )
    if run.creative_job_id is None:
        raise HTTPException(status_code=409, detail="Creative loop has no Creative job")
    job = await runtime.creative_runtime.repository.get_job(
        CreativeJobId.from_string(run.creative_job_id)
    )
    if job is None or job.card is None:
        raise HTTPException(status_code=409, detail="Creative approval card not found")
    creative_version_ids = job.card.final_version_refs or (job.card.final_version_ref,)
    try:
        command, created = await resolve_queue_call(
            CreativeLoopCommandService(queue).enqueue_creative_decision(
                run,
                creative_version_ids,
                payload.decision,
                payload.reviewer_alias,
                payload.reason,
            )
        )
    except (ValueError, CommandPayloadDriftError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _accepted(command, created)


@app.post(
    "/api/v1/marketing/creative-loops/{run_id}/ads-outcome",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_creative_loop_ads_outcome(
    run_id: str,
    payload: CreativeLoopAdsOutcomeRequest,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> CommandAcceptedResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative loop run not found")
    outcome = payload.to_domain()
    dedupe_key = f"creative-loop:ads:{run.run_id}:{outcome.event_id}"
    if run.state != CreativeLoopState.AWAITING_ADS_OUTCOME:
        existing = await resolve_queue_call(queue.get_by_dedupe_key(dedupe_key))
        if existing is None:
            raise HTTPException(
                status_code=409, detail="Creative loop is not awaiting an Ads event"
            )
    try:
        command, created = await resolve_queue_call(
            CreativeLoopCommandService(queue).enqueue_ads_outcome(run, outcome)
        )
    except (ValueError, CommandPayloadDriftError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _accepted(command, created)


@app.post(
    "/api/v1/marketing/creative-loops/{run_id}/lesson-decision",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def decide_creative_loop_lesson(
    run_id: str,
    payload: CreativeLoopLessonDecisionRequest,
    runtime: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> CommandAcceptedResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative loop run not found")
    dedupe_key = f"creative-loop:lesson:{run.run_id}:{payload.lesson_id}"
    if (
        run.state != CreativeLoopState.AWAITING_LESSON_APPROVAL
        or run.lesson_id != payload.lesson_id
    ):
        existing = await resolve_queue_call(queue.get_by_dedupe_key(dedupe_key))
        if existing is None:
            raise HTTPException(status_code=409, detail="Creative loop is not awaiting this lesson")
    try:
        command, created = await resolve_queue_call(
            CreativeLoopCommandService(queue).enqueue_lesson_decision(
                run,
                payload.lesson_id,
                payload.decision,
                payload.reviewer_alias,
                payload.reason,
                payload.learning_proposal_id,
            )
        )
    except (ValueError, CommandPayloadDriftError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _accepted(command, created)


@app.get("/api/v1/execution/commands", response_model=ExecutionCommandListResponse)
async def list_execution_commands(
    command_status: str | None = Query(default=None, alias="status"),
    workflow_run_id: str | None = None,
    queue: CommandStatusStore = Depends(get_command_status_store),
) -> ExecutionCommandListResponse:
    try:
        parsed_status = CommandStatus(command_status) if command_status else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Unknown execution command status") from error
    commands = await resolve_queue_call(
        queue.list(status=parsed_status, workflow_run_id=workflow_run_id)
    )
    return ExecutionCommandListResponse(
        items=[_to_execution_command_response(command) for command in commands],
        total=len(commands),
    )


@app.get("/api/v1/execution/commands/{command_id}", response_model=ExecutionCommandResponse)
async def get_execution_command(
    command_id: str,
    queue: CommandStatusStore = Depends(get_command_status_store),
) -> ExecutionCommandResponse:
    command = await resolve_queue_call(queue.get(command_id))
    if command is None:
        raise HTTPException(status_code=404, detail="Execution command not found")
    return _to_execution_command_response(command)


@app.post(
    "/api/v1/execution/commands/{command_id}/retry",
    response_model=ExecutionCommandResponse,
)
async def retry_execution_command(
    command_id: str,
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> ExecutionCommandResponse:
    try:
        command = await resolve_queue_call(queue.retry_failed(command_id))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _to_execution_command_response(command)


@app.post(
    "/api/v1/execution/commands/{command_id}/cancel",
    response_model=ExecutionCommandResponse,
)
async def cancel_execution_command(
    command_id: str,
    queue: CommandScheduler = Depends(get_command_scheduler),
) -> ExecutionCommandResponse:
    try:
        command = await resolve_queue_call(queue.request_cancel(command_id))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _to_execution_command_response(command)


@app.get("/api/v1/creative/intakes", response_model=CreativeIntakeRunListResponse)
async def list_creative_intake_runs(
    runtime: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
) -> CreativeIntakeRunListResponse:
    runs = await runtime.repository.list()
    return CreativeIntakeRunListResponse(
        items=[_to_creative_intake_response(run) for run in runs], total=len(runs)
    )


@app.get("/api/v1/creative/intakes/{run_id}", response_model=CreativeIntakeRunResponse)
async def get_creative_intake_run(
    run_id: str,
    runtime: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
) -> CreativeIntakeRunResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative intake run not found")
    return _to_creative_intake_response(run)


@app.get(
    "/api/v1/creative/intakes/{run_id}/issues",
    response_model=list[CreativeIntakeIssueResponse],
)
async def get_creative_intake_issues(
    run_id: str,
    runtime: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
) -> list[CreativeIntakeIssueResponse]:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative intake run not found")
    response = _to_creative_intake_response(run)
    return response.issues


@app.get(
    "/api/v1/creative/intakes/{run_id}/work-item",
    response_model=dict[str, object],
)
async def get_creative_intake_work_item(
    run_id: str,
    runtime: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
) -> dict[str, object]:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative intake run not found")
    if run.release is None:
        raise HTTPException(status_code=409, detail="Creative intake has no released work item")
    path = runtime.artifact_store.path(*run.release.work_item_ref.split("/"))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Creative intake work item artifact not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Creative intake work item artifact is invalid")
    return payload


@app.get(
    "/api/v1/creative/intakes/{run_id}/pipeline",
    response_model=CreativePipelineResponse,
)
async def get_creative_pipeline(
    run_id: str,
    request: Request,
    intake_runtime: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
    creative_runtime: CreativeRuntime = Depends(get_runtime),
) -> CreativePipelineResponse:
    run = await intake_runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Creative intake run not found")
    job = None
    if run.release is not None and run.release.downstream_job_id is not None:
        job = await creative_runtime.repository.get_job(
            CreativeJobId.from_string(run.release.downstream_job_id)
        )
    artifact_id, web_url = (
        await _brief_artifact_reference(request, job) if job is not None else (None, None)
    )
    return CreativePipelineResponse(
        intake=_to_creative_intake_response(run),
        downstream_job=(
            _to_job_detail_response(
                job,
                brief_artifact_id=artifact_id,
                brief_web_url=web_url,
            )
            if job is not None
            else None
        ),
    )


@app.get("/api/v1/creative-feedback", response_model=CreativeFeedbackRunListResponse)
async def list_creative_feedback_runs(
    runtime: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
) -> CreativeFeedbackRunListResponse:
    runs = await runtime.repository.list()
    return CreativeFeedbackRunListResponse(
        items=[_to_creative_feedback_response(run) for run in runs], total=len(runs)
    )


@app.get("/api/v1/creative-feedback/{run_id}", response_model=CreativeFeedbackRunResponse)
async def get_creative_feedback_run(
    run_id: str,
    runtime: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
) -> CreativeFeedbackRunResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Creative feedback run not found."
        )
    return _to_creative_feedback_response(run)


@app.get(
    "/api/v1/creative-feedback/{run_id}/lesson",
    response_model=FeedbackLessonResponse,
)
async def get_creative_feedback_lesson(
    run_id: str,
    runtime: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
) -> FeedbackLessonResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Creative feedback run not found."
        )
    if run.lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This feedback run has no evidence-ready lesson.",
        )
    response = _to_creative_feedback_response(run)
    assert response.lesson is not None
    return response.lesson


@app.get(
    "/api/v1/creative-feedback/{run_id}/next-task-preview",
    response_model=NextCreativeTaskPreviewResponse,
)
async def get_creative_feedback_task_preview(
    run_id: str,
    runtime: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
) -> NextCreativeTaskPreviewResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Creative feedback run not found."
        )
    if run.next_task_preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This feedback run has no actionable next-task preview.",
        )
    response = _to_creative_feedback_response(run)
    assert response.next_task_preview is not None
    return response.next_task_preview


@app.post(
    "/api/v1/creative-feedback/{run_id}/decision",
    response_model=CreativeFeedbackRunResponse,
)
async def decide_creative_feedback_task(
    run_id: str,
    payload: CreativeFeedbackDecisionRequest,
    runtime: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
) -> CreativeFeedbackRunResponse:
    try:
        run = await runtime.decide(
            run_id,
            payload.lesson_id,
            payload.decision,
            payload.reviewer_alias,
            payload.reason,
            payload.learning_proposal_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if detail == "Creative feedback run not found"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    return _to_creative_feedback_response(run)


def _to_performance_decision_response(
    run: PerformanceDecisionRun,
) -> PerformanceDecisionRunResponse:
    snapshot = run.snapshot
    evaluation = run.evaluation
    return PerformanceDecisionRunResponse(
        run_id=run.run_id,
        source_run_id=run.source_run_id,
        snapshot_id=snapshot.snapshot_id,
        subject_type=snapshot.subject.subject_type.value,
        subject_id=snapshot.subject.subject_id,
        brand_id=snapshot.subject.brand_id,
        store_id=snapshot.subject.store_id,
        sku_id=snapshot.subject.sku_id,
        platform=snapshot.subject.platform,
        objective=snapshot.objective,
        channel=snapshot.channel,
        timezone=snapshot.timezone,
        attribution=snapshot.attribution,
        currency=snapshot.currency,
        source_version=snapshot.source_version,
        observed_at=snapshot.observed_at.isoformat(),
        metrics=[
            PerformanceMetricResponse(
                name=metric.name.value,
                window_id=metric.window_id,
                status=metric.status.value,
                value=str(metric.value) if metric.value is not None else None,
                unit=metric.unit,
                source_ref=metric.source_ref,
                observed_at=metric.observed_at.isoformat(),
            )
            for metric in snapshot.metrics
        ],
        evaluation_id=evaluation.evaluation_id,
        evaluation_version=evaluation.version_number,
        evaluation_state=evaluation.state.value,
        classification=evaluation.classification.value,
        recommendation=evaluation.recommendation.value,
        rule_set_id=evaluation.rule_set_id,
        rule_version=evaluation.rule_version,
        rule_mode=evaluation.rule_mode.value,
        rule_status=evaluation.rule_status.value,
        assessments=[
            PerformanceRuleAssessmentResponse(
                rule_id=assessment.rule_id,
                classification=assessment.classification.value,
                outcome=assessment.outcome.value,
                passed_criteria=assessment.passed_criteria,
                required_passes=assessment.required_passes,
                criteria=[
                    PerformanceCriterionResponse(
                        criterion_id=criterion.criterion_id,
                        metric=criterion.metric.value,
                        window_id=criterion.window_id,
                        outcome=criterion.outcome.value,
                        observed_value=str(criterion.observed_value)
                        if criterion.observed_value is not None
                        else None,
                        operator=criterion.operator.value,
                        threshold=str(criterion.threshold),
                        source_ref=criterion.source_ref,
                        detail=criterion.detail,
                    )
                    for criterion in assessment.criteria
                ],
            )
            for assessment in evaluation.assessments
        ],
        evidence_refs=list(evaluation.evidence_refs),
        decision=run.decision.value if run.decision else None,
        decision_evaluation_id=run.decision_evaluation_id,
        reviewer_alias=run.reviewer_alias,
        decision_reason=run.decision_reason,
        decided_at=run.decided_at.isoformat() if run.decided_at else None,
        creative_demand_preview=(
            _to_creative_demand_preview(run.creative_demand_preview)
            if run.creative_demand_preview
            else None
        ),
        opportunity_analysis=(
            CreativeOpportunityResponse(
                analysis_id=run.opportunity_analysis.analysis_id,
                evidence_pack_id=run.opportunity_analysis.evidence_pack_id,
                category=run.opportunity_analysis.category.value,
                priority=run.opportunity_analysis.priority,
                rationale=run.opportunity_analysis.rationale,
                evidence_refs=list(run.opportunity_analysis.evidence_refs),
                uncertainty=run.opportunity_analysis.uncertainty,
                counterargument=run.opportunity_analysis.counterargument,
                proposal=_to_experiment_proposal(run.opportunity_analysis.proposal),
                prompt_version=run.opportunity_analysis.prompt_version,
                model=run.opportunity_analysis.model,
                rubric_version=run.opportunity_analysis.rubric_version,
                created_at=run.opportunity_analysis.created_at.isoformat(),
            )
            if run.opportunity_analysis
            else None
        ),
        decision_proposal_id=run.decision_proposal_id,
        approved_proposal=(
            _to_experiment_proposal(run.approved_proposal) if run.approved_proposal else None
        ),
    )


def _to_experiment_proposal(proposal: ExperimentProposal) -> ExperimentProposalData:
    return ExperimentProposalData(
        proposal_id=proposal.proposal_id,
        version_number=proposal.version_number,
        sku_id=proposal.sku_id,
        priority=proposal.priority,
        category=proposal.category.value,
        hypothesis=proposal.hypothesis,
        experiment=proposal.experiment,
        success_signal=proposal.success_signal,
        evidence_refs=list(proposal.evidence_refs),
        uncertainty=proposal.uncertainty,
    )


def _from_experiment_proposal(proposal: ExperimentProposalData | None) -> ExperimentProposal | None:
    if proposal is None:
        return None
    return ExperimentProposal(
        proposal_id=proposal.proposal_id,
        version_number=proposal.version_number,
        sku_id=proposal.sku_id,
        priority=proposal.priority,
        category=OpportunityCategory(proposal.category),
        hypothesis=proposal.hypothesis,
        experiment=proposal.experiment,
        success_signal=proposal.success_signal,
        evidence_refs=tuple(proposal.evidence_refs),
        uncertainty=proposal.uncertainty,
    )


@app.get(
    "/api/v1/performance/decisions",
    response_model=PerformanceDecisionRunListResponse,
)
async def list_performance_decisions(
    runtime: PerformanceDecisionRuntime = Depends(get_performance_decision_runtime),
) -> PerformanceDecisionRunListResponse:
    runs = await runtime.repository.list()
    return PerformanceDecisionRunListResponse(
        items=[_to_performance_decision_response(run) for run in runs], total=len(runs)
    )


@app.get(
    "/api/v1/performance/decisions/{run_id}",
    response_model=PerformanceDecisionRunResponse,
)
async def get_performance_decision(
    run_id: str,
    runtime: PerformanceDecisionRuntime = Depends(get_performance_decision_runtime),
) -> PerformanceDecisionRunResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Performance decision run not found.",
        )
    return _to_performance_decision_response(run)


@app.get(
    "/api/v1/performance/decisions/{run_id}/creative-demand-preview",
    response_model=CreativeDemandPreviewResponse,
)
async def get_creative_demand_preview(
    run_id: str,
    runtime: PerformanceDecisionRuntime = Depends(get_performance_decision_runtime),
) -> CreativeDemandPreviewResponse:
    run = await runtime.repository.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Performance decision run not found.",
        )
    if run.creative_demand_preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This recommendation has no Creative demand preview.",
        )
    return _to_creative_demand_preview(run.creative_demand_preview)


@app.post(
    "/api/v1/performance/decisions/{run_id}/decision",
    response_model=PerformanceDecisionRunResponse,
)
async def decide_performance_recommendation(
    run_id: str,
    payload: PerformanceDecisionRequestBody,
    runtime: PerformanceDecisionRuntime = Depends(get_performance_decision_runtime),
) -> PerformanceDecisionRunResponse:
    try:
        run = await runtime.decide(
            run_id,
            payload.evaluation_id,
            payload.decision,
            payload.reviewer_alias,
            payload.reason,
            payload.proposal_id,
            _from_experiment_proposal(payload.edited_proposal),
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if detail == "Performance decision run not found"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    return _to_performance_decision_response(run)


@app.get("/api/v1/creative/jobs", response_model=JobListResponse)
async def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    decision: str | None = Query(default="pending", description="pending|all|decided"),
    limit: int = Query(default=200, ge=1, le=1000),
    runtime: CreativeRuntime = Depends(get_runtime),
) -> JobListResponse:
    jobs = await runtime.repository.list_jobs()
    if status_filter is not None:
        try:
            wanted = CreativeJobStatus(status_filter)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{status_filter}'.",
            ) from e
        jobs = [job for job in jobs if job.status == wanted]

    if decision == "pending":
        jobs = [job for job in jobs if job.card is not None and job.card.decision is None]
    elif decision == "decided":
        jobs = [job for job in jobs if job.card is not None and job.card.decision is not None]
    elif decision == "all":
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decision filter must be pending, decided, or all.",
        )

    job_items = [_to_job_summary(job) for job in jobs[:limit]]
    return JobListResponse(items=job_items, total=len(job_items))


@app.get("/api/v1/creative/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str,
    request: Request,
    runtime: CreativeRuntime = Depends(get_runtime),
) -> JobDetailResponse:
    job = await runtime.repository.get_job(CreativeJobId.from_string(job_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    artifact_id, web_url = await _brief_artifact_reference(request, job)
    return _to_job_detail_response(
        job,
        brief_artifact_id=artifact_id,
        brief_web_url=web_url,
    )


@app.get("/api/v1/creative/approvals", response_model=JobListResponse)
async def list_approvals(
    runtime: CreativeRuntime = Depends(get_runtime),
    status_filter: str | None = Query(default="pending", description="pending|all|decided"),
) -> JobListResponse:
    jobs = await runtime.repository.list_jobs()
    if status_filter == "pending":
        jobs = [job for job in jobs if job.card is not None and job.card.decision is None]
    elif status_filter == "decided":
        jobs = [job for job in jobs if job.card is not None and job.card.decision is not None]
    elif status_filter == "all":
        jobs = [job for job in jobs if job.card is not None]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status_filter must be pending, decided, or all.",
        )
    items = [_to_job_summary(job) for job in jobs]
    return JobListResponse(items=items, total=len(items))


@app.post("/api/v1/creative/jobs/{job_id}/decision", response_model=ApprovalDecisionResponse)
async def post_decision(
    job_id: str,
    payload: ApprovalDecisionRequest,
    runtime: CreativeRuntime = Depends(get_runtime),
    intake_runtime: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
) -> ApprovalDecisionResponse:
    decision = payload.decision
    if decision == ApprovalDecision.REJECT and not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reason is required when decision is reject.",
        )

    outcome = await runtime.decide(
        job_id=job_id,
        decision=decision,
        reviewer=payload.reviewer,
        reason=payload.reason,
    )
    if not outcome.result.success:
        logger.warning(
            "Failed decision for job {} by {}: {}",
            job_id,
            payload.reviewer,
            outcome.result.error,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=outcome.result.error or "Decision failed.",
        )

    job = outcome.result.job
    if job is not None and job.source_run_id is not None:
        intake = await intake_runtime.repository.get_by_task_source_run_id(job.source_run_id)
        if (
            intake is not None
            and intake.release is not None
            and intake.release.downstream_job_id == job.job_id.value
        ):
            handoff_state = (
                HandoffState.APPROVED
                if job.status == CreativeJobStatus.APPROVED
                else HandoffState.REJECTED
            )
            intake = intake.record_handoff(
                handoff_state,
                downstream_job_id=job.job_id.value,
            )
            await intake_runtime.repository.save(intake)
            try:
                write_creative_intake_artifacts(intake_runtime.artifact_store, intake, None)
            except OSError:
                logger.warning(
                    "Creative decision persisted but intake artifact refresh failed for {}",
                    intake.run_id,
                )
    status_value = job.status.value if job else "unknown"
    return ApprovalDecisionResponse(
        ok=True,
        job_id=job_id,
        status=status_value,
        decision=payload.decision,
        reviewer=payload.reviewer,
    )


@app.get("/api/v1/creative/exceptions", response_model=ExceptionListResponse)
async def list_exceptions(runtime: CreativeRuntime = Depends(get_runtime)) -> ExceptionListResponse:
    jobs = await runtime.repository.list_jobs()
    items: list[ExceptionItemResponse] = []

    for job in jobs:
        if job.status not in {
            CreativeJobStatus.EXCEPTION_OPERATIONAL,
            CreativeJobStatus.EXCEPTION_POLICY,
        }:
            continue

        exception_type = (
            "policy" if job.status == CreativeJobStatus.EXCEPTION_POLICY else "operational"
        )
        message = "no error message persisted"
        suggested = None
        for entry in reversed(job.audit_log):
            if entry.action == "exception":
                for key, value in entry.details:
                    if key == "error":
                        message = str(value)
                    if key == "exception_type":
                        exception_type = str(value)
                    if key == "suggested_action":
                        suggested = str(value)
                break

        items.append(
            ExceptionItemResponse(
                job_id=job.job_id.value,
                source_run_id=job.source_run_id,
                status=job.status.value,
                exception_type=exception_type,
                error_message=message,
                suggested_action=suggested,
            )
        )

    return ExceptionListResponse(items=items, total=len(items))


class DashboardStaticFiles(StaticFiles):
    """Serve the React entrypoint for client-side dashboard routes."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            return await super().get_response("index.html", scope)


def _mount_frontend(application: FastAPI) -> None:
    """Serve the production dashboard build when it exists."""
    frontend_dir = Path(__file__).resolve().parents[4] / "frontend" / "dist"
    if frontend_dir.is_dir():
        application.mount(
            "/dashboard",
            DashboardStaticFiles(directory=str(frontend_dir), html=True),
            name="dashboard",
        )
    else:
        logger.debug("No dashboard frontend found at {}", frontend_dir)


app.include_router(dashboard_router)
app.include_router(ai_usage_router)
app.include_router(data_sources_router)
app.include_router(media_assets_router)
_configure_cors(app)
_mount_frontend(app)
instrument_fastapi(app, _OBSERVABILITY_SETTINGS)


def create_app() -> FastAPI:
    """Factory for external callers (tests / app factories)."""
    return app


app.add_exception_handler(
    ValueError,
    lambda _request, exc: JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    ),
)
