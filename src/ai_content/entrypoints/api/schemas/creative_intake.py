"""API schemas for Creative context intake and M1 handoff."""

from pydantic import BaseModel

from .creative import JobDetailResponse


class CreativeIntakeTriggerResponse(BaseModel):
    trigger_id: str
    source: str
    source_preview_id: str
    source_decision_ref: str
    source_released: bool
    brand_id: str
    sku_id: str
    action: str
    objective: str | None
    channel: str | None
    evidence_refs: list[str]
    requested_at: str
    source_creative_version_id: str | None
    reusable_context_refs: list[str]


class CreativeContextComponentResponse(BaseModel):
    component: str
    status: str
    evidence_refs: list[str]
    observed_at: str
    valid_until: str | None
    detail: str | None


class CreativeContextSnapshotResponse(BaseModel):
    snapshot_id: str
    version: str
    brand_id: str
    sku_id: str
    market: str
    objective: str
    channel: str
    product_image_count: int
    persona_count: int
    output_width: int
    output_height: int
    requested_image_count: int
    requested_video_count: int
    requested_video_duration_seconds: int | None
    requested_video_duration_min_seconds: int
    requested_video_duration_max_seconds: int
    requested_video_scene_duration_max_seconds: int
    include_background_music: bool
    production_route: str
    routing_reasons: list[str]
    routing_requires_override: bool
    version_refs: list[str]
    resolved_context_refs: list[str]
    components: list[CreativeContextComponentResponse]
    evidence_refs: list[str]
    captured_at: str


class CreativeIntakeIssueResponse(BaseModel):
    code: str
    component: str | None
    status: str
    detail: str
    evidence_refs: list[str]
    required_for_release: bool


class CreativeTaskReleaseResponse(BaseModel):
    release_id: str
    intake_run_id: str
    source_trigger_id: str
    source_run_id: str
    work_item_ref: str
    context_ref: str
    display_name: str
    handoff_state: str
    released_at: str
    downstream_job_id: str | None
    handoff_error: str | None


class CreativeIntakeRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    trigger: CreativeIntakeTriggerResponse
    context: CreativeContextSnapshotResponse
    state: str
    issues: list[CreativeIntakeIssueResponse]
    release: CreativeTaskReleaseResponse | None
    created_at: str
    audit_log: list[str]


class CreativeIntakeRunListResponse(BaseModel):
    items: list[CreativeIntakeRunResponse]
    total: int


class CreativePipelineResponse(BaseModel):
    intake: CreativeIntakeRunResponse
    downstream_job: JobDetailResponse | None


__all__ = [
    "CreativeContextComponentResponse",
    "CreativeContextSnapshotResponse",
    "CreativeIntakeIssueResponse",
    "CreativeIntakeRunListResponse",
    "CreativeIntakeRunResponse",
    "CreativePipelineResponse",
    "CreativeIntakeTriggerResponse",
    "CreativeTaskReleaseResponse",
]
