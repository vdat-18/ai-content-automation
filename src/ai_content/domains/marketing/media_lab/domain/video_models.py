"""Domain records for the bounded Media Lab Create Video workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import ImageBinary


class VideoIntent(StrEnum):
    CREATE_FROM_TEXT = "create_from_text"
    CREATE_FROM_IMAGES = "create_from_images"


class VideoSourceRole(StrEnum):
    PRODUCT = "product"
    STYLE = "style"
    BACKGROUND = "background"
    CHARACTER = "character"
    KEYFRAME = "keyframe"
    STORYBOARD = "storyboard"


class VideoSourceUsage(StrEnum):
    GENERATION = "generation"
    VERIFICATION = "verification"
    BOTH = "both"


class VideoSourceOrigin(StrEnum):
    UPLOAD = "upload"
    MEDIA_LAB_IMAGE_OUTPUT = "media_lab_image_output"


class VideoOutputFormat(StrEnum):
    MP4 = "mp4"


class VideoGenerationState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class VideoReviewState(StrEnum):
    NOT_READY = "not_ready"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class VideoQualityReviewState(StrEnum):
    NOT_REQUESTED = "not_requested"
    REVIEWING = "reviewing"
    PASSED = "passed"
    REGENERATING = "regenerating"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    UNAVAILABLE = "unavailable"


class VideoVerificationState(StrEnum):
    NOT_REQUESTED = "not_requested"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"


class VideoVerificationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class VideoVerificationStage(StrEnum):
    TECHNICAL = "technical"
    TRACKING = "tracking"
    PRODUCT_FIDELITY = "product_fidelity"
    TEMPORAL_QUALITY = "temporal_quality"


class VideoQualityDecision(StrEnum):
    PASS = "pass"
    REGENERATE = "regenerate"
    HUMAN_REVIEW = "human_review"


class VideoQualityIssueSeverity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class VideoPlanningState(StrEnum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"


@dataclass(frozen=True)
class VideoImageSourceInput:
    source_index: int
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    source_origin: VideoSourceOrigin
    binary: ImageBinary | None = None
    source_run_id: str | None = None
    identity_group: str | None = None
    is_primary_identity: bool = False
    asset_id: str | None = None


@dataclass(frozen=True)
class VideoPlanningImageSource:
    source_index: int
    image: ImageBinary
    source_origin: VideoSourceOrigin
    source_run_id: str | None = None


@dataclass(frozen=True)
class VideoSourcePlan:
    source_index: int
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    identity_group: str | None = None
    is_primary_identity: bool = False


@dataclass(frozen=True)
class VideoQualityIssue:
    category: str
    severity: VideoQualityIssueSeverity
    description: str


@dataclass(frozen=True)
class VideoReviewFrame:
    label: str
    timestamp_milliseconds: int
    artifact_ref: str
    checksum_sha256: str


@dataclass(frozen=True)
class VideoQualityReview:
    decision: VideoQualityDecision
    summary: str
    issues: tuple[VideoQualityIssue, ...]
    repair_instructions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    reviewer_model: str
    reviewer_prompt_version: str
    reviewer_prompt_hash: str
    reviewer_config_hash: str
    review_hash: str
    sampled_frames: tuple[VideoReviewFrame, ...] = ()
    temporal_sampling_rate_fps: int | None = None
    temporal_duration_milliseconds: int | None = None
    repair_prompt: str | None = None
    repair_prompt_version: str | None = None
    repair_prompt_hash: str | None = None
    verification: VideoVerificationReport | None = None


@dataclass(frozen=True)
class VideoQualityReviewSource:
    label: str
    role: VideoSourceRole
    usage: VideoSourceUsage
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    image: ImageBinary
    source_id: str = ""
    identity_group: str | None = None
    is_primary_identity: bool = False


@dataclass(frozen=True)
class VideoVerificationObservation:
    observation_id: str
    stage: VideoVerificationStage
    category: str
    status: VideoVerificationStatus
    severity: VideoQualityIssueSeverity
    description: str
    confidence: float | None = None
    start_timestamp_milliseconds: int | None = None
    end_timestamp_milliseconds: int | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id or not self.category or not self.description:
            raise ValueError("Video verification observation requires identity and description")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Video verification confidence must be between 0 and 1")
        if (
            self.start_timestamp_milliseconds is not None
            and self.end_timestamp_milliseconds is not None
            and self.end_timestamp_milliseconds < self.start_timestamp_milliseconds
        ):
            raise ValueError("Video verification observation timestamps are invalid")


@dataclass(frozen=True)
class VideoVerificationStageResult:
    stage: VideoVerificationStage
    status: VideoVerificationStatus
    model: str
    model_version: str
    observations: tuple[VideoVerificationObservation, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class VideoVerificationStagePlan:
    stage: VideoVerificationStage
    reason: str


@dataclass(frozen=True)
class VideoVerificationReport:
    status: VideoVerificationStatus
    verifier_version: str
    config_hash: str
    stages: tuple[VideoVerificationStageResult, ...]
    request_hash: str = "0" * 64
    suspicious_timestamps_milliseconds: tuple[int, ...] = ()
    uncertainties: tuple[str, ...] = ()
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not self.verifier_version or not self.config_hash or len(self.request_hash) != 64:
            raise ValueError(
                "Video verification report requires version, config hash and request hash"
            )
        if not self.stages:
            raise ValueError("Video verification report requires at least one stage")
        if any(timestamp < 0 for timestamp in self.suspicious_timestamps_milliseconds):
            raise ValueError("Video verification timestamps cannot be negative")


@dataclass(frozen=True)
class VideoQualityReviewFrame:
    label: str
    timestamp_milliseconds: int
    image: ImageBinary


@dataclass(frozen=True)
class VideoTemporalEvidence:
    sampling_rate_fps: int
    duration_milliseconds: int
    frames: tuple[VideoQualityReviewFrame, ...]


@dataclass(frozen=True)
class VideoQualityReviewRequest:
    run_id: str
    user_request: str | None
    production_prompt: str
    candidate_evidence: VideoTemporalEvidence
    sources: tuple[VideoQualityReviewSource, ...]
    verification: VideoVerificationReport | None = None
    retry_memory: VideoRetryMemory | None = None


@dataclass(frozen=True)
class VideoOrchestrationTrace:
    user_request: str
    capability_id: str
    summary: str
    planner_model: str
    planner_prompt_version: str
    planner_prompt_hash: str
    planner_config_hash: str
    plan_hash: str


@dataclass(frozen=True)
class VideoOrchestrationPlan:
    state: VideoPlanningState
    summary: str
    questions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    capability_id: str | None
    production_prompt: str | None
    sources: tuple[VideoSourcePlan, ...]
    verification_plan: tuple[VideoVerificationStagePlan, ...]
    trace: VideoOrchestrationTrace


@dataclass(frozen=True)
class CreateVideoCommand:
    intent: VideoIntent
    prompt: str
    sources: tuple[VideoImageSourceInput, ...]
    duration_seconds: int
    seed: int | None = None
    orchestration: VideoOrchestrationTrace | None = None
    verification_plan: tuple[VideoVerificationStagePlan, ...] = ()
    output_preset_id: str | None = None
    output_format: VideoOutputFormat = VideoOutputFormat.MP4
    retry_memory: VideoRetryMemory | None = None
    technical_only: bool = False


@dataclass(frozen=True)
class VideoSource:
    source_id: str
    source_index: int
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int
    must_preserve: tuple[str, ...]
    allowed_changes: tuple[str, ...]
    source_origin: VideoSourceOrigin
    source_checksum_sha256: str
    artifact_ref: str
    content_type: str
    source_run_id: str | None = None
    identity_group: str | None = None
    is_primary_identity: bool = False
    asset_id: str | None = None


@dataclass(frozen=True)
class VideoOutputSpec:
    duration_seconds: int
    candidate_count: int = 1
    preset_id: str | None = None
    aspect_ratio: str | None = None
    megapixels: float | None = None
    output_format: VideoOutputFormat = VideoOutputFormat.MP4


@dataclass(frozen=True)
class VideoOutputPreset:
    preset_id: str
    label: str
    aspect_ratio: str
    selector_aspect_ratio: str
    megapixels: float


@dataclass(frozen=True)
class VideoRetryAttempt:
    run_id: str
    seed: int | None
    production_prompt: str
    output_asset_id: str | None
    output_checksum_sha256: str | None
    duration_seconds: int
    output_preset_id: str | None
    review_decision: VideoQualityDecision | None
    review_summary: str | None
    repair_instructions: tuple[str, ...]
    repair_prompt: str | None
    verifier_status: VideoVerificationStatus | None
    suspicious_timestamps_milliseconds: tuple[int, ...]


@dataclass(frozen=True)
class VideoRetryMemory:
    root_run_id: str
    attempts: tuple[VideoRetryAttempt, ...]


@dataclass(frozen=True)
class VideoCapability:
    capability_id: str
    intent: VideoIntent
    label: str
    description: str
    minimum_generation_images: int
    maximum_generation_images: int
    supported_duration_seconds: tuple[int, ...]
    candidate_count: int = 1
    output_presets: tuple[VideoOutputPreset, ...] = ()
    supported_output_formats: tuple[VideoOutputFormat, ...] = ()
    default_output_preset_id: str | None = None


@dataclass(frozen=True)
class VideoRun:
    run_id: str
    intent: VideoIntent
    prompt: str
    rendered_prompt: str
    sources: tuple[VideoSource, ...]
    verification_plan: tuple[VideoVerificationStagePlan, ...]
    output_spec: VideoOutputSpec
    seed: int | None
    generation_state: VideoGenerationState
    review_state: VideoReviewState
    model: str | None
    checkpoint_observation: str | None
    graph_template_hash: str | None
    backend_run_id: str | None
    provider_job_id: str | None
    orchestration: VideoOrchestrationTrace | None
    output_ref: str | None
    output_checksum_sha256: str | None
    output_content_type: str | None
    manifest_ref: str | None
    error_code: str | None
    quality_review_state: VideoQualityReviewState
    quality_review: VideoQualityReview | None
    quality_review_error_code: str | None
    regenerated_run_id: str | None
    retry_of_run_id: str | None
    regeneration_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    reviewed_at: datetime | None = None
    verification_state: VideoVerificationState = VideoVerificationState.NOT_REQUESTED
    verification: VideoVerificationReport | None = None
    verification_frames: tuple[VideoReviewFrame, ...] = ()
    verification_error_code: str | None = None
    output_asset_id: str | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    actual_duration_milliseconds: int | None = None
    retry_memory: VideoRetryMemory | None = None
    queue_wait_milliseconds: int | None = None
    provider_delay_milliseconds: int | None = None
    provider_execution_milliseconds: int | None = None


__all__ = [
    "CreateVideoCommand",
    "VideoCapability",
    "VideoGenerationState",
    "VideoImageSourceInput",
    "VideoIntent",
    "VideoOrchestrationPlan",
    "VideoOrchestrationTrace",
    "VideoOutputFormat",
    "VideoOutputPreset",
    "VideoOutputSpec",
    "VideoPlanningImageSource",
    "VideoPlanningState",
    "VideoQualityDecision",
    "VideoQualityIssue",
    "VideoQualityIssueSeverity",
    "VideoQualityReview",
    "VideoQualityReviewFrame",
    "VideoQualityReviewRequest",
    "VideoQualityReviewSource",
    "VideoQualityReviewState",
    "VideoVerificationObservation",
    "VideoVerificationReport",
    "VideoVerificationStagePlan",
    "VideoVerificationStage",
    "VideoVerificationStageResult",
    "VideoVerificationState",
    "VideoVerificationStatus",
    "VideoSource",
    "VideoSourcePlan",
    "VideoSourceRole",
    "VideoSourceUsage",
    "VideoReviewFrame",
    "VideoReviewState",
    "VideoRetryAttempt",
    "VideoRetryMemory",
    "VideoRun",
    "VideoSourceOrigin",
    "VideoTemporalEvidence",
]
