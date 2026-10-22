"""Pydantic schema models for Creative dashboard APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_content.domains.marketing.creative.domain.entities import ApprovalDecision


class HealthResponse(BaseModel):
    """Simple service health check payload."""

    status: str = "ok"
    service: str = "creative-dashboard-api"
    checks: dict[str, str] = Field(default_factory=dict)


class JobVersionResponse(BaseModel):
    """Version snapshot for a creative job."""

    version_id: str
    attempt_number: int
    creative_set_id: str | None
    variation_id: str | None
    variation_attempt_number: int | None
    artifact_url: str | None
    artifact_path: str | None
    artifact_web_url: str | None
    review_context_web_url: str | None
    cost: str | None
    input_ref: str
    input_hash: str | None
    prompt_version: str | None
    rubric_version: str | None
    policy_version: str | None
    workflow_version: str | None
    generator_version: str | None
    qa_passed: bool | None
    qa_score: str | None
    qa_issues: list[str]
    qa_warnings: list[str]
    qa_feedback: str | None
    qa_outcome: str | None
    qa_retryable: bool
    qa_requires_human_review: bool
    qa_repair_actions: list[str]
    qa_evidence_refs: list[str]
    qa_reviewer_version: str | None
    created_at: str


class JobCardResponse(BaseModel):
    """Approval card visible in dashboard queues."""

    work_item_id: str
    candidate_summary: str
    final_version_ref: str
    final_version_refs: list[str]
    thumbnail_ref: str | None
    thumbnail_web_url: str | None
    warnings: list[str]
    score: str | None
    evidence_refs: list[str]
    decision: str | None = None
    reviewer_id: str | None = None
    decided_at: str | None = None
    reason: str | None = None


class LineageResponse(BaseModel):
    """Single lineage edge record."""

    entry_type: str
    ref: str
    parent_ref: str | None
    details: dict[str, object]
    recorded_at: str


class JobSummaryResponse(BaseModel):
    """Compact job row used in inbox and list views."""

    job_id: str
    source_run_id: str | None
    status: str
    idea_id: str | None
    context_ref: str | None
    total_cost: str | None
    version_count: int
    latest_version: str | None
    latest_score: str | None
    pending_approval: bool
    display_title: str
    thumbnail_web_url: str | None = None


class JobListResponse(BaseModel):
    """Dashboard job list response."""

    items: list[JobSummaryResponse]
    total: int


class JobDetailResponse(BaseModel):
    """Detailed job payload for Job Detail view."""

    job_id: str
    source_run_id: str | None
    status: str
    context_ref: str | None
    idea_id: str | None
    brief_ref: str | None
    brief_artifact_id: str | None
    brief_web_url: str | None
    preparation_hash: str | None
    creative_set_id: str | None
    total_cost: str | None
    versions: list[JobVersionResponse]
    card: JobCardResponse | None
    audit_count: int
    lineage: list[LineageResponse]


class ApprovalDecisionRequest(BaseModel):
    """Decision request for a review card."""

    decision: ApprovalDecision
    reviewer: str = Field(min_length=1)
    reason: str | None = None


class ApprovalDecisionResponse(BaseModel):
    """Decision result after posting approve/reject."""

    ok: bool
    job_id: str
    status: str
    decision: str
    reviewer: str


class ExceptionItemResponse(BaseModel):
    """Operational/policy exception row."""

    job_id: str
    source_run_id: str | None
    status: str
    exception_type: str
    error_message: str
    suggested_action: str | None


class ExceptionListResponse(BaseModel):
    """List view for exception queue."""

    items: list[ExceptionItemResponse]
    total: int
