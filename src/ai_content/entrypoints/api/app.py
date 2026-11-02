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

from ai_content.domains.marketing.creative.bootstrap import CreativeRuntime
from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJob,
    CreativeJobId,
    CreativeJobStatus,
)
from ai_content.domains.marketing.creative_intake.adapters.artifacts import (
    write_creative_intake_artifacts,
)
from ai_content.domains.marketing.creative_intake.adapters.serialization import (
    run_to_dict as creative_intake_to_dict,
)
from ai_content.domains.marketing.creative_intake.bootstrap import CreativeIntakeRuntime
from ai_content.domains.marketing.creative_intake.domain.models import HandoffState
from ai_content.platform.artifacts import (
    ArtifactRecord,
    ArtifactService,
    ArtifactStatus,
    ObjectStorageError,
)
from ai_content.platform.artifacts.object_storage import iter_download, normalize_object_key
from ai_content.platform.execution import (
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
    get_creative_intake_runtime,
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
from .schemas.creative_intake import (
    CreativeIntakeIssueResponse,
    CreativeIntakeRunListResponse,
    CreativeIntakeRunResponse,
    CreativePipelineResponse,
)
from .schemas.execution import (
    CommandAcceptedResponse,
    ExecutionCommandListResponse,
    ExecutionCommandResponse,
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


@app.get("/api/v1/features")
async def features() -> dict[str, bool]:
    return {"media_generation": get_runtime_settings().media_generation_enabled}


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


def _to_creative_intake_response(run) -> CreativeIntakeRunResponse:
    return CreativeIntakeRunResponse.model_validate(creative_intake_to_dict(run))


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
