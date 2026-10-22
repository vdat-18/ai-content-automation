"""Domain records for the bounded Media Lab Create Image workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ImageIntent(StrEnum):
    CREATE_FROM_TEXT = "create_from_text"
    CREATE_FROM_REFERENCES = "create_from_references"
    EDIT_EXISTING = "edit_existing"


class ImageReferenceRole(StrEnum):
    PRODUCT_SOURCE = "product_source"
    STYLE_REFERENCE = "style_reference"
    PREVIOUS_OUTPUT = "previous_output"


class ImageSourceOrigin(StrEnum):
    UPLOAD = "upload"
    MEDIA_LAB_OUTPUT = "media_lab_output"


class ImageOutputFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class ImageGenerationState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ImageReviewState(StrEnum):
    NOT_READY = "not_ready"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ImageQualityReviewState(StrEnum):
    NOT_REQUESTED = "not_requested"
    REVIEWING = "reviewing"
    PASSED = "passed"
    REGENERATING = "regenerating"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    UNAVAILABLE = "unavailable"


class ImageQualityDecision(StrEnum):
    PASS = "pass"
    REGENERATE = "regenerate"
    HUMAN_REVIEW = "human_review"


class ImageQualityIssueSeverity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class ImagePlanningState(StrEnum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"


@dataclass(frozen=True)
class ImageBinary:
    content: bytes
    extension: str
    content_type: str


@dataclass(frozen=True)
class ImageReferenceInput:
    role: ImageReferenceRole
    priority: int
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    source_origin: ImageSourceOrigin
    binary: ImageBinary | None = None
    source_run_id: str | None = None
    asset_id: str | None = None
    identity_group: str | None = None


@dataclass(frozen=True)
class ImagePlanningSource:
    source_index: int
    image: ImageBinary
    source_origin: ImageSourceOrigin
    source_run_id: str | None = None


@dataclass(frozen=True)
class ImageReferencePlan:
    source_index: int
    role: ImageReferenceRole
    priority: int
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    identity_group: str | None = None


@dataclass(frozen=True)
class ImageQualityIssue:
    category: str
    severity: ImageQualityIssueSeverity
    description: str


@dataclass(frozen=True)
class ImageQualityReview:
    decision: ImageQualityDecision
    summary: str
    issues: tuple[ImageQualityIssue, ...]
    repair_instructions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    reviewer_model: str
    reviewer_prompt_version: str
    reviewer_prompt_hash: str
    reviewer_config_hash: str
    review_hash: str
    repair_prompt: str | None = None
    repair_prompt_version: str | None = None
    repair_prompt_hash: str | None = None


@dataclass(frozen=True)
class ImageQualityReviewSource:
    label: str
    role: ImageReferenceRole
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    image: ImageBinary
    identity_group: str | None = None


@dataclass(frozen=True)
class ImageQualityReviewRequest:
    run_id: str
    user_request: str | None
    production_prompt: str
    candidate: ImageBinary
    sources: tuple[ImageQualityReviewSource, ...]
    retry_memory: ImageRetryMemory | None = None


@dataclass(frozen=True)
class ImageOrchestrationTrace:
    user_request: str
    capability_id: str
    summary: str
    planner_model: str
    planner_prompt_version: str
    planner_prompt_hash: str
    planner_config_hash: str
    plan_hash: str


@dataclass(frozen=True)
class ImageOrchestrationPlan:
    state: ImagePlanningState
    summary: str
    questions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    capability_id: str | None
    production_prompt: str | None
    references: tuple[ImageReferencePlan, ...]
    trace: ImageOrchestrationTrace


@dataclass(frozen=True)
class CreateImageCommand:
    intent: ImageIntent
    prompt: str
    references: tuple[ImageReferenceInput, ...]
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    orchestration: ImageOrchestrationTrace | None = None
    output_preset_id: str | None = None
    output_format: ImageOutputFormat = ImageOutputFormat.PNG
    retry_memory: ImageRetryMemory | None = None


@dataclass(frozen=True)
class ImageReference:
    reference_id: str
    role: ImageReferenceRole
    priority: int
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    source_origin: ImageSourceOrigin
    source_checksum_sha256: str
    artifact_ref: str
    content_type: str
    source_run_id: str | None = None
    asset_id: str | None = None
    identity_group: str | None = None


@dataclass(frozen=True)
class ImageOutputSpec:
    width: int | None
    height: int | None
    candidate_count: int = 1
    preset_id: str | None = None
    aspect_ratio: str | None = None
    delivery_format: ImageOutputFormat = ImageOutputFormat.PNG


@dataclass(frozen=True)
class ImageOutputPreset:
    preset_id: str
    label: str
    aspect_ratio: str
    width: int
    height: int


@dataclass(frozen=True)
class ImageRetryAttempt:
    run_id: str
    seed: int | None
    production_prompt: str
    output_asset_id: str | None
    output_checksum_sha256: str | None
    review_decision: ImageQualityDecision | None
    review_summary: str | None
    repair_instructions: tuple[str, ...]
    repair_prompt: str | None


@dataclass(frozen=True)
class ImageRetryMemory:
    root_run_id: str
    attempts: tuple[ImageRetryAttempt, ...]


@dataclass(frozen=True)
class ImageRun:
    run_id: str
    intent: ImageIntent
    prompt: str
    rendered_prompt: str
    references: tuple[ImageReference, ...]
    output_spec: ImageOutputSpec
    seed: int | None
    generation_state: ImageGenerationState
    review_state: ImageReviewState
    model: str | None
    checkpoint_observation: str | None
    graph_template_hash: str | None
    backend_run_id: str | None
    provider_job_id: str | None
    parent_run_id: str | None
    orchestration: ImageOrchestrationTrace | None
    output_ref: str | None
    output_checksum_sha256: str | None
    output_content_type: str | None
    manifest_ref: str | None
    error_code: str | None
    quality_review_state: ImageQualityReviewState
    quality_review: ImageQualityReview | None
    quality_review_error_code: str | None
    regenerated_run_id: str | None
    retry_of_run_id: str | None
    regeneration_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    reviewed_at: datetime | None = None
    output_asset_id: str | None = None
    delivery_ref: str | None = None
    delivery_checksum_sha256: str | None = None
    delivery_content_type: str | None = None
    retry_memory: ImageRetryMemory | None = None
    queue_wait_milliseconds: int | None = None
    provider_delay_milliseconds: int | None = None
    provider_execution_milliseconds: int | None = None


@dataclass(frozen=True)
class ImageCapability:
    capability_id: str
    intent: ImageIntent
    label: str
    description: str
    required_roles: tuple[ImageReferenceRole, ...]
    supports_output_size: bool
    candidate_count: int = 1
    minimum_product_source_count: int = 0
    maximum_product_source_count: int = 0
    minimum_style_reference_count: int = 0
    maximum_style_reference_count: int = 0
    minimum_reference_count: int = 0
    maximum_reference_count: int = 0
    output_presets: tuple[ImageOutputPreset, ...] = ()
    supported_output_formats: tuple[ImageOutputFormat, ...] = ()


__all__ = [
    "CreateImageCommand",
    "ImageBinary",
    "ImageCapability",
    "ImageGenerationState",
    "ImageIntent",
    "ImageOrchestrationPlan",
    "ImageOrchestrationTrace",
    "ImageOutputFormat",
    "ImageOutputPreset",
    "ImageOutputSpec",
    "ImagePlanningSource",
    "ImagePlanningState",
    "ImageQualityDecision",
    "ImageQualityIssue",
    "ImageQualityIssueSeverity",
    "ImageQualityReview",
    "ImageQualityReviewRequest",
    "ImageQualityReviewSource",
    "ImageQualityReviewState",
    "ImageReference",
    "ImageReferenceInput",
    "ImageReferencePlan",
    "ImageReferenceRole",
    "ImageRetryAttempt",
    "ImageRetryMemory",
    "ImageReviewState",
    "ImageRun",
    "ImageSourceOrigin",
]
