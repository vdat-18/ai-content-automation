"""Cross-workstream read models for the Marketing dashboard."""

from typing import Literal

from pydantic import BaseModel

DashboardWorkstream = Literal["creative", "email", "performance", "creators"]


class DashboardApprovalResponse(BaseModel):
    approval_id: str
    workstream: DashboardWorkstream
    kind: str
    title: str
    detail: str
    status: Literal["pending"]
    brand_id: str | None
    entity_id: str
    version_ref: str | None
    created_at: str
    action_path: str
    decision_type: str


class DashboardWorkflowResponse(BaseModel):
    workflow_id: str
    workstream: DashboardWorkstream
    title: str
    detail: str
    state: str
    status: Literal["running", "waiting", "completed", "failed"]
    brand_id: str | None
    entity_id: str
    updated_at: str
    action_path: str
    business_stage: str


class DashboardExceptionResponse(BaseModel):
    exception_id: str
    workstream: DashboardWorkstream
    title: str
    detail: str
    queue: Literal["operations", "policy"]
    severity: Literal["warning", "blocking"]
    status: Literal["open"]
    brand_id: str | None
    entity_id: str
    evidence_refs: list[str]
    created_at: str
    action_path: str


class DashboardSummaryResponse(BaseModel):
    pending_approvals: int
    open_workflows: int
    active_commands: int
    open_exceptions: int
    failed_commands: int


class DashboardSnapshotResponse(BaseModel):
    summary: DashboardSummaryResponse
    approvals: list[DashboardApprovalResponse]
    workflows: list[DashboardWorkflowResponse]
    exceptions: list[DashboardExceptionResponse]
    generated_at: str


__all__ = [
    "DashboardApprovalResponse",
    "DashboardExceptionResponse",
    "DashboardSnapshotResponse",
    "DashboardSummaryResponse",
    "DashboardWorkflowResponse",
]
