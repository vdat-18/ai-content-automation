"""Read-only cross-workstream projection for the Marketing dashboard."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from ai_content.domains.marketing.creative.bootstrap import CreativeRuntime
from ai_content.domains.marketing.creative_feedback.bootstrap import CreativeFeedbackRuntime
from ai_content.domains.marketing.creative_intake.bootstrap import CreativeIntakeRuntime
from ai_content.domains.marketing.creative_loop.bootstrap import CreativeLoopRuntime
from ai_content.platform.execution import CommandStatus, CommandStatusStore, resolve_queue_call

from .dependencies import (
    get_command_status_store,
    get_creative_feedback_runtime,
    get_creative_intake_runtime,
    get_creative_loop_runtime,
    get_runtime,
)
from .schemas.dashboard import (
    DashboardApprovalResponse,
    DashboardExceptionResponse,
    DashboardSnapshotResponse,
    DashboardSummaryResponse,
    DashboardWorkflowResponse,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _business_stage(state: str) -> str:
    if state in {"awaiting_demand_approval", "ready_for_review", "needs_business_review"}:
        return "plan_review"
    if state in {"awaiting_creative_approval", "awaiting_approval"}:
        return "output_review"
    if state in {"awaiting_ads_outcome", "testing", "scheduled"}:
        return "waiting_results"
    if state == "awaiting_lesson_approval":
        return "learning_review"
    if _workflow_status(state) == "failed":
        return "needs_attention"
    if _workflow_status(state) == "completed":
        return "completed"
    return "working"


def _workflow_status(state: str) -> str:
    if state in {
        "blocked_conflict",
        "blocked_policy",
        "exception_operational",
        "exception_policy",
        "failed",
        "needs_evidence",
        "needs_context",
        "preflight_blocked",
        "source_blocked",
    }:
        return "failed"
    if state in {
        "approved",
        "archived",
        "closed_declined",
        "closed_no_reply",
        "completed",
        "dismissed",
        "healthy",
        "next_brief_ready",
        "ready_for_lark_preview",
        "rejected",
        "verified_resolved",
    }:
        return "completed"
    if state.startswith("awaiting_") or state in {
        "deferred",
        "needs_business_review",
        "ready_for_review",
        "waiting_reply",
    }:
        return "waiting"
    return "running"


def _creative_job_updated_at(job) -> datetime:
    if job.audit_log:
        return job.audit_log[-1].timestamp
    if job.latest_version is not None:
        return job.latest_version.created_at
    return datetime.now(UTC)


def _approval(
    *,
    approval_id: str,
    workstream: str,
    kind: str,
    title: str,
    detail: str,
    brand_id: str | None,
    entity_id: str,
    version_ref: str | None,
    created_at: datetime,
    action_path: str,
) -> DashboardApprovalResponse:
    return DashboardApprovalResponse(
        approval_id=approval_id,
        workstream=workstream,
        kind=kind,
        title=title,
        detail=detail,
        status="pending",
        brand_id=brand_id,
        entity_id=entity_id,
        version_ref=version_ref,
        created_at=created_at.isoformat(),
        action_path=action_path,
        decision_type=kind,
    )


def _workflow(
    *,
    workflow_id: str,
    workstream: str,
    title: str,
    detail: str,
    state: str,
    brand_id: str | None,
    entity_id: str,
    updated_at: datetime,
    action_path: str,
) -> DashboardWorkflowResponse:
    return DashboardWorkflowResponse(
        workflow_id=workflow_id,
        workstream=workstream,
        title=title,
        detail=detail,
        state=state,
        status=_workflow_status(state),
        brand_id=brand_id,
        entity_id=entity_id,
        updated_at=updated_at.isoformat(),
        action_path=action_path,
        business_stage=_business_stage(state),
    )


def _exception(
    *,
    exception_id: str,
    workstream: str,
    title: str,
    detail: str,
    queue: str,
    severity: str,
    brand_id: str | None,
    entity_id: str,
    evidence_refs: tuple[str, ...] | list[str],
    created_at: datetime,
    action_path: str,
) -> DashboardExceptionResponse:
    return DashboardExceptionResponse(
        exception_id=exception_id,
        workstream=workstream,
        title=title,
        detail=detail,
        queue=queue,
        severity=severity,
        status="open",
        brand_id=brand_id,
        entity_id=entity_id,
        evidence_refs=list(evidence_refs),
        created_at=created_at.isoformat(),
        action_path=action_path,
    )


@router.get("/snapshot", response_model=DashboardSnapshotResponse)
async def get_dashboard_snapshot(
    creative: CreativeRuntime = Depends(get_runtime),
    loops: CreativeLoopRuntime = Depends(get_creative_loop_runtime),
    intake: CreativeIntakeRuntime = Depends(get_creative_intake_runtime),
    feedback: CreativeFeedbackRuntime = Depends(get_creative_feedback_runtime),
    queue: CommandStatusStore = Depends(get_command_status_store),
) -> DashboardSnapshotResponse:
    (
        creative_jobs,
        loop_runs,
        intake_runs,
        feedback_runs,
    ) = await asyncio.gather(
        creative.repository.list_jobs(),
        loops.repository.list(),
        intake.repository.list(),
        feedback.repository.list(),
    )
    commands = await resolve_queue_call(queue.list())

    linked_creative = {run.creative_job_id for run in loop_runs if run.creative_job_id}

    approvals: list[DashboardApprovalResponse] = []
    workflows: list[DashboardWorkflowResponse] = []
    exceptions: list[DashboardExceptionResponse] = []

    for run in loop_runs:
        state = run.state.value
        workflows.append(
            _workflow(
                workflow_id=run.run_id,
                workstream="creative",
                title="Marketing Creative closed loop",
                detail=f"Current gate: {state}",
                state=state,
                brand_id=None,
                entity_id=run.run_id,
                updated_at=run.updated_at,
                action_path=f"/workflows?loop={run.run_id}",
            )
        )
        gate = {
            "awaiting_demand_approval": ("demand", run.initial_evaluation_id),
            "awaiting_creative_approval": ("creative", run.creative_job_id),
            "awaiting_lesson_approval": ("lesson", run.lesson_id),
        }.get(state)
        if gate is not None:
            kind, version_ref = gate
            action_path = (
                f"/creatives/{run.creative_job_id}?loop={run.run_id}"
                if kind == "creative" and run.creative_job_id
                else f"/workflows?loop={run.run_id}"
            )
            approvals.append(
                _approval(
                    approval_id=f"creative-loop:{run.run_id}:{kind}",
                    workstream="creative",
                    kind=f"creative_loop_{kind}",
                    title=f"Creative loop {kind} decision",
                    detail="Review the exact saved workflow gate before continuing.",
                    brand_id=None,
                    entity_id=run.run_id,
                    version_ref=version_ref,
                    created_at=run.updated_at,
                    action_path=action_path,
                )
            )
        if state in {"needs_evidence", "blocked_conflict"}:
            exceptions.append(
                _exception(
                    exception_id=f"creative-loop:{run.run_id}:{state}",
                    workstream="creative",
                    title="Creative loop cannot continue",
                    detail=f"Workflow stopped in {state}.",
                    queue="operations",
                    severity="blocking",
                    brand_id=None,
                    entity_id=run.run_id,
                    evidence_refs=(),
                    created_at=run.updated_at,
                    action_path=f"/workflows?loop={run.run_id}",
                )
            )

    for job in creative_jobs:
        if job.job_id.value in linked_creative:
            continue
        state = job.status.value
        workflows.append(
            _workflow(
                workflow_id=job.job_id.value,
                workstream="creative",
                title="Static Creative production",
                detail=f"Creative job {job.job_id.value}",
                state=state,
                brand_id=None,
                entity_id=job.job_id.value,
                updated_at=_creative_job_updated_at(job),
                action_path=f"/creatives/{job.job_id.value}",
            )
        )
        if job.card is not None and job.card.decision is None:
            version_ref = job.card.final_version_refs or (job.card.final_version_ref,)
            approvals.append(
                _approval(
                    approval_id=f"creative:{job.job_id.value}",
                    workstream="creative",
                    kind="creative",
                    title="Creative output approval",
                    detail=job.card.candidate_summary,
                    brand_id=None,
                    entity_id=job.job_id.value,
                    version_ref=",".join(version_ref),
                    created_at=_creative_job_updated_at(job),
                    action_path=f"/creatives/{job.job_id.value}",
                )
            )
        if state in {"exception_operational", "exception_policy"}:
            exceptions.append(
                _exception(
                    exception_id=f"creative:{job.job_id.value}:{state}",
                    workstream="creative",
                    title="Creative workflow exception",
                    detail=f"Creative job stopped in {state}.",
                    queue="policy" if state == "exception_policy" else "operations",
                    severity="blocking",
                    brand_id=None,
                    entity_id=job.job_id.value,
                    evidence_refs=(),
                    created_at=_creative_job_updated_at(job),
                    action_path=f"/creatives/{job.job_id.value}",
                )
            )

    for command in commands:
        if command.status != CommandStatus.FAILED:
            continue
        exceptions.append(
            _exception(
                exception_id=f"execution:{command.command_id}",
                workstream="creative",
                title="Workflow command failed",
                detail=f"{command.last_error_code or 'UNKNOWN'}: {command.last_error_message or 'No detail'}",
                queue="operations",
                severity="blocking",
                brand_id=None,
                entity_id=command.workflow_run_id or command.command_id,
                evidence_refs=(),
                created_at=command.updated_at,
                action_path=(
                    f"/workflows?loop={command.workflow_run_id}"
                    if command.workflow_run_id
                    else "/workflows"
                ),
            )
        )

    approvals.sort(key=lambda item: item.created_at, reverse=True)
    workflows.sort(key=lambda item: item.updated_at, reverse=True)
    exceptions.sort(key=lambda item: item.created_at, reverse=True)
    active_commands = sum(
        command.status
        in {
            CommandStatus.PENDING,
            CommandStatus.RUNNING,
            CommandStatus.RETRY_WAIT,
            CommandStatus.CANCEL_REQUESTED,
        }
        for command in commands
    )
    return DashboardSnapshotResponse(
        summary=DashboardSummaryResponse(
            pending_approvals=len(approvals),
            open_workflows=sum(item.status in {"running", "waiting"} for item in workflows),
            active_commands=active_commands,
            open_exceptions=len(exceptions),
            failed_commands=sum(command.status == CommandStatus.FAILED for command in commands),
        ),
        approvals=approvals,
        workflows=workflows,
        exceptions=exceptions,
        generated_at=datetime.now(UTC).isoformat(),
    )


__all__ = ["router"]
