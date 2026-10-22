"""Canonical Media Lab APIs plus deprecated direct ComfyUI graph compatibility routes."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import secrets
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_content.domains.marketing.creative.adapters.image_files import inspect_image
from ai_content.domains.marketing.creative.ports.images import ImageGenerationError
from ai_content.domains.marketing.media_lab.application.assets import MediaAssetService
from ai_content.domains.marketing.media_lab.application.image_runs import MediaLabImageService
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
)
from ai_content.domains.marketing.media_lab.domain.assets import (
    MediaAsset,
    MediaAssetOrigin,
)
from ai_content.domains.marketing.media_lab.domain.models import (
    CreateImageCommand,
    ImageGenerationState,
    ImageIntent,
    ImageOrchestrationPlan,
    ImageOrchestrationTrace,
    ImageOutputFormat,
    ImagePlanningSource,
    ImageQualityDecision,
    ImageQualityIssueSeverity,
    ImageQualityReviewState,
    ImageReferenceInput,
    ImageReferenceRole,
    ImageRetryMemory,
    ImageReviewState,
    ImageRun,
    ImageSourceOrigin,
)
from ai_content.domains.marketing.media_lab.domain.planning_jobs import (
    PlanningJob,
    PlanningJobKind,
)
from ai_content.domains.marketing.media_lab.domain.video_ads import (
    CreateVideoAdCommand,
    VideoAdBrief,
    VideoAdJob,
    VideoAdJobState,
)
from ai_content.domains.marketing.media_lab.domain.video_models import (
    CreateVideoCommand,
    VideoGenerationState,
    VideoImageSourceInput,
    VideoIntent,
    VideoOrchestrationPlan,
    VideoOrchestrationTrace,
    VideoOutputFormat,
    VideoPlanningImageSource,
    VideoQualityDecision,
    VideoQualityIssueSeverity,
    VideoQualityReviewState,
    VideoRetryMemory,
    VideoReviewState,
    VideoRun,
    VideoSourceOrigin,
    VideoSourceRole,
    VideoSourceUsage,
    VideoVerificationStage,
    VideoVerificationStagePlan,
    VideoVerificationState,
)
from ai_content.domains.marketing.media_lab.domain.video_projects import (
    CreateVideoProjectCommand,
    VideoProject,
    VideoProjectShot,
    VideoProjectState,
)
from ai_content.domains.marketing.media_lab.ports.assets import MediaAssetError
from ai_content.domains.marketing.media_lab.ports.interfaces import (
    ImageBackendObserver,
    ImageBackendRun,
    ImageBackendUpdate,
    MediaLabImageError,
    MediaLabImageOrchestrationError,
    PinnedImageGeneration,
    PinnedImageGraph,
)
from ai_content.domains.marketing.media_lab.ports.planning_jobs import (
    MediaLabPlanningJobError,
)
from ai_content.domains.marketing.media_lab.ports.video_ads import MediaLabVideoAdError
from ai_content.domains.marketing.media_lab.ports.video_interfaces import (
    MediaLabVideoError,
    MediaLabVideoOrchestrationError,
    PinnedVideoGeneration,
    PinnedVideoGraph,
    VideoBackendObserver,
    VideoBackendRun,
    VideoBackendUpdate,
)
from ai_content.domains.marketing.media_lab.ports.video_projects import (
    MediaLabVideoProjectError,
)

router = APIRouter(prefix="/api/v1/media-lab", tags=["media-lab"])

_MAX_IMAGE_BYTES = 12_000_000
_MAX_IMAGE_SOURCES = 10
_MAX_VIDEO_IMAGE_SOURCES = 7
_MAX_VIDEO_INPUT_BASE64_CHARS = 144_000_000
_MAX_VIDEO_BYTES = 25_000_000
_MAX_SEED = 9_007_199_254_740_991
_MAX_POLL_TRANSPORT_ERRORS = 5
_MAX_RUNPOD_REQUEST_BYTES = 9_000_000
InputKind = Literal["image", "video"]


class LegacyMediaGraphMode(StrEnum):
    TEXT_TO_IMAGE = "text_to_image"
    PRODUCT_TO_IMAGE = "product_to_image"
    MULTI_REFERENCE_TO_IMAGE = "multi_reference_to_image"
    REVISE_IMAGE = "revise_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    REFERENCE_VIDEO_TO_VIDEO = "reference_video_to_video"


class LegacyMediaGraphRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class _WorkflowSpec:
    mode: LegacyMediaGraphMode
    label: str
    model: str
    media_type: str
    description: str
    workflow_file: str
    expected_nodes: dict[str, str]
    prompt_node: str
    seed_node: str
    output_node: str
    prompt_input: str = "text"
    input_kind: InputKind | None = None
    input_nodes: tuple[str, ...] = ()
    input_name: str = "image"
    size_nodes: tuple[str, ...] = ()
    resolution_selector_node: str | None = None
    duration_node: str | None = None
    timeout_seconds: int = 900


_SPECS: dict[LegacyMediaGraphMode, _WorkflowSpec] = {
    LegacyMediaGraphMode.TEXT_TO_IMAGE: _WorkflowSpec(
        mode=LegacyMediaGraphMode.TEXT_TO_IMAGE,
        label="Legacy graph: Text to image",
        model="FLUX.2 Dev · quality mode",
        media_type="image",
        description="Create one image from a text prompt.",
        workflow_file="media_lab/flux2_dev_text_to_image.json",
        expected_nodes={
            "9": "SaveImage",
            "98:6": "CLIPTextEncode",
            "98:25": "RandomNoise",
            "98:47": "EmptyFlux2LatentImage",
            "98:48": "Flux2Scheduler",
            "98:12": "UNETLoader",
        },
        prompt_node="98:6",
        seed_node="98:25",
        output_node="9",
        size_nodes=("98:47", "98:48"),
    ),
    LegacyMediaGraphMode.PRODUCT_TO_IMAGE: _WorkflowSpec(
        mode=LegacyMediaGraphMode.PRODUCT_TO_IMAGE,
        label="Legacy graph: Product image to image",
        model="FLUX.2 Dev · quality mode",
        media_type="image",
        description="Use one product image as the visual reference.",
        workflow_file="media_lab/flux2_dev_image_edit.json",
        expected_nodes={
            "140": "LoadImage",
            "141": "SaveImage",
            "139:123": "CLIPTextEncode",
            "139:125": "RandomNoise",
            "139:129": "UNETLoader",
        },
        prompt_node="139:123",
        seed_node="139:125",
        output_node="141",
        input_kind="image",
        input_nodes=("140",),
    ),
    LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE: _WorkflowSpec(
        mode=LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE,
        label="Legacy graph: Multiple references to image",
        model="FLUX.2 Dev · quality mode",
        media_type="image",
        description="Combine a product image and one or more visual references.",
        workflow_file="media_lab/flux2_dev_multi_reference.json",
        expected_nodes={
            "6": "CLIPTextEncode",
            "9": "SaveImage",
            "12": "UNETLoader",
            "25": "RandomNoise",
            "42": "LoadImage",
            "46": "LoadImage",
            "47": "EmptyFlux2LatentImage",
            "48": "Flux2Scheduler",
            "49": "ReferenceLatent",
            "50": "ReferenceLatent",
        },
        prompt_node="6",
        seed_node="25",
        output_node="9",
        input_kind="image",
        input_nodes=("46", "42"),
        size_nodes=("47", "48"),
    ),
    LegacyMediaGraphMode.REVISE_IMAGE: _WorkflowSpec(
        mode=LegacyMediaGraphMode.REVISE_IMAGE,
        label="Legacy graph: Previous output revision",
        model="FLUX.2 Dev · quality mode",
        media_type="image",
        description="Edit a previously generated image using a new instruction.",
        workflow_file="media_lab/flux2_dev_image_edit.json",
        expected_nodes={
            "140": "LoadImage",
            "141": "SaveImage",
            "139:123": "CLIPTextEncode",
            "139:125": "RandomNoise",
            "139:129": "UNETLoader",
        },
        prompt_node="139:123",
        seed_node="139:125",
        output_node="141",
        input_kind="image",
        input_nodes=("140",),
    ),
    LegacyMediaGraphMode.IMAGE_TO_VIDEO: _WorkflowSpec(
        mode=LegacyMediaGraphMode.IMAGE_TO_VIDEO,
        label="Legacy graph: Image to video",
        model="MiniMax H3 · image to video",
        media_type="video",
        description="Animate one supplied image with a text motion prompt.",
        workflow_file="media_lab/minimax_h3_image_to_video.json",
        expected_nodes={
            "92": "SaveVideo",
            "114": "LoadImage",
            "115": "ResolutionSelector",
            "105:15": "RandomNoise",
            "105:104": "MiniMaxH3ImageToVideo",
            "105:111": "PrimitiveFloat",
            "105:6": "UNETLoader",
            "105:13": "CLIPLoader",
        },
        prompt_node="105:104",
        seed_node="105:15",
        output_node="92",
        prompt_input="prompt",
        input_kind="image",
        input_nodes=("114",),
        resolution_selector_node="115",
        duration_node="105:111",
        timeout_seconds=1800,
    ),
    LegacyMediaGraphMode.TEXT_TO_VIDEO: _WorkflowSpec(
        mode=LegacyMediaGraphMode.TEXT_TO_VIDEO,
        label="Legacy graph: Text to video",
        model="MiniMax H3 · text to video",
        media_type="video",
        description="Create one video from a text prompt without a reference asset.",
        workflow_file="media_lab/minimax_h3_text_to_video.json",
        expected_nodes={
            "92": "SaveVideo",
            "115": "ResolutionSelector",
            "105:15": "RandomNoise",
            "105:104": "MiniMaxH3ImageToVideo",
            "105:111": "PrimitiveFloat",
            "105:6": "UNETLoader",
            "105:13": "CLIPLoader",
            "105:11": "VAELoader",
            "105:24": "VAELoader",
        },
        prompt_node="105:104",
        seed_node="105:15",
        output_node="92",
        prompt_input="prompt",
        resolution_selector_node="115",
        duration_node="105:111",
        timeout_seconds=1800,
    ),
    LegacyMediaGraphMode.REFERENCE_VIDEO_TO_VIDEO: _WorkflowSpec(
        mode=LegacyMediaGraphMode.REFERENCE_VIDEO_TO_VIDEO,
        label="Legacy graph: Text + reference video to video",
        model="MiniMax H3 · reference to video",
        media_type="video",
        description="Use one MP4 only for motion and camera reference while creating a new video.",
        workflow_file="media_lab/minimax_h3_reference_to_video.json",
        expected_nodes={
            "92": "SaveVideo",
            "115": "ResolutionSelector",
            "119": "VAELoader",
            "120": "VAELoader",
            "127": "UNETLoader",
            "128": "CLIPLoader",
            "129": "RandomNoise",
            "132": "PrimitiveFloat",
            "136": "MiniMaxH3ReferenceToVideo",
            "138": "PrimitiveStringMultiline",
            "141": "LoadVideo",
            "142": "GetVideoComponents",
        },
        prompt_node="138",
        seed_node="129",
        output_node="92",
        prompt_input="value",
        input_kind="video",
        input_nodes=("141",),
        input_name="file",
        resolution_selector_node="115",
        duration_node="132",
        timeout_seconds=1800,
    ),
}


class LegacyMediaGraphError(Exception):
    """Expected Media Lab failure that is safe to return to the browser."""

    def __init__(
        self, message: str, *, status_code: int = 400, code: str = "invalid_request"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class LegacyMediaGraphSettings(BaseModel):
    """Server-only settings for the ComfyUI Media Lab connector."""

    model_config = ConfigDict(extra="forbid")

    image_base_url: str | None = None
    video_base_url: str | None = None
    image_runpod_endpoint_id: str | None = None
    image_runpod_api_key: str | None = None
    video_runpod_endpoint_id: str | None = None
    video_runpod_api_key: str | None = None
    request_timeout_seconds: float = Field(default=30, gt=0, le=120)
    poll_interval_seconds: float = Field(default=3, gt=0, le=15)

    def configured(self) -> bool:
        return self.configured_for("image") or self.configured_for("video")

    def configured_for(self, media_type: str) -> bool:
        if media_type == "image" and self.runpod_image_configured():
            return True
        if media_type == "video" and self.runpod_video_configured():
            return True
        return self.base_url_for(media_type) is not None

    def runpod_image_configured(self) -> bool:
        return self.image_runpod_endpoint_id is not None and self.image_runpod_api_key is not None

    def runpod_video_configured(self) -> bool:
        return self.video_runpod_endpoint_id is not None and self.video_runpod_api_key is not None

    def runpod_credentials_for(self, media_type: str) -> tuple[str | None, str | None]:
        if media_type == "image":
            return self.image_runpod_endpoint_id, self.image_runpod_api_key
        return self.video_runpod_endpoint_id, self.video_runpod_api_key

    def base_url_for(self, media_type: str) -> str | None:
        return self.image_base_url if media_type == "image" else self.video_base_url


class LegacyMediaGraphModeInfo(BaseModel):
    id: LegacyMediaGraphMode
    label: str
    model: str
    media_type: str
    description: str
    input_count: int
    input_kind: InputKind | None
    supports_resolution: bool
    supports_duration: bool
    available: bool


class LegacyMediaGraphCatalog(BaseModel):
    enabled: bool
    items: list[LegacyMediaGraphModeInfo]
    notice: str | None = None


class LegacyMediaGraphInputImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=128)
    content_base64: str = Field(min_length=4, max_length=16_000_000)


class LegacyMediaGraphInputVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=128)
    content_base64: str = Field(min_length=16, max_length=34_000_000)


class LegacyMediaGraphRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: LegacyMediaGraphMode
    prompt: str = Field(min_length=1, max_length=6_000)
    images: list[LegacyMediaGraphInputImage] = Field(
        default_factory=list, max_length=_MAX_IMAGE_SOURCES
    )
    videos: list[LegacyMediaGraphInputVideo] = Field(default_factory=list, max_length=1)
    seed: int | None = Field(default=None, ge=0, le=_MAX_SEED)
    width: int | None = Field(default=None, ge=64, le=2048)
    height: int | None = Field(default=None, ge=64, le=2048)
    duration_seconds: int | None = Field(default=None, ge=4, le=15)


class LegacyMediaGraphRunResponse(BaseModel):
    run_id: str
    mode: LegacyMediaGraphMode
    status: LegacyMediaGraphRunStatus
    model: str
    media_type: str
    seed: int
    width: int | None
    height: int | None
    duration_seconds: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    output_url: str | None
    queue_position: int | None
    queue_wait_milliseconds: int | None
    provider_delay_milliseconds: int | None
    provider_execution_milliseconds: int | None
    error_code: str | None


class MediaLabAssetReference(BaseModel):
    """Bind a persistent ML1 or ML2 source to one immutable media asset."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["media_asset"]
    asset_id: str = Field(min_length=1, max_length=128)


MediaLabImageSourceRequest = MediaLabAssetReference


class MediaLabImagePlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_request: str = Field(min_length=1, max_length=6_000)
    sources: list[MediaLabImageSourceRequest] = Field(
        default_factory=list, max_length=_MAX_IMAGE_SOURCES
    )


class MediaLabImageOrchestrationTraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_request: str = Field(min_length=1, max_length=6_000)
    capability_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=4_000)
    planner_model: str = Field(min_length=1, max_length=256)
    planner_prompt_version: str = Field(min_length=1, max_length=256)
    planner_prompt_hash: str = Field(min_length=1, max_length=128)
    planner_config_hash: str = Field(min_length=1, max_length=128)
    plan_hash: str = Field(min_length=1, max_length=128)


class MediaLabImageReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ImageReferenceRole
    priority: int = Field(ge=1, le=100)
    must_preserve: list[str] = Field(default_factory=list, max_length=10)
    allowed_changes: list[str] = Field(default_factory=list, max_length=10)
    identity_group: str | None = Field(default=None, min_length=1, max_length=128)
    source: MediaLabImageSourceRequest


class MediaLabImageRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: ImageIntent
    prompt: str = Field(min_length=1, max_length=6_000)
    references: list[MediaLabImageReferenceRequest] = Field(
        default_factory=list, max_length=_MAX_IMAGE_SOURCES
    )
    seed: int | None = Field(default=None, ge=0, le=_MAX_SEED)
    width: int | None = Field(default=None, ge=64, le=2048)
    height: int | None = Field(default=None, ge=64, le=2048)
    output_preset_id: str | None = Field(default=None, min_length=1, max_length=128)
    output_format: ImageOutputFormat = ImageOutputFormat.PNG
    orchestration: MediaLabImageOrchestrationTraceRequest | None = None


class MediaLabImageOrchestrationStatusResponse(BaseModel):
    enabled: bool
    model: str | None
    max_image_sources: int = Field(ge=0, le=_MAX_IMAGE_SOURCES)
    quality_review_enabled: bool
    max_regenerations: int = Field(ge=0, le=2)
    notice: str | None


class MediaLabImagePlanReferenceResponse(BaseModel):
    source_index: int
    role: ImageReferenceRole
    priority: int
    must_preserve: list[str]
    allowed_changes: list[str]
    identity_group: str | None


class MediaLabImageOrchestrationTraceResponse(BaseModel):
    user_request: str
    capability_id: str
    summary: str
    planner_model: str
    planner_prompt_version: str
    planner_prompt_hash: str
    planner_config_hash: str
    plan_hash: str


class MediaLabImagePlanResponse(BaseModel):
    state: Literal["ready", "needs_input"]
    summary: str
    questions: list[str]
    uncertainties: list[str]
    capability_id: str | None
    intent: ImageIntent | None
    production_prompt: str | None
    references: list[MediaLabImagePlanReferenceResponse]
    orchestration: MediaLabImageOrchestrationTraceResponse


class MediaLabImagePlanningJobRequest(MediaLabImagePlanningRequest):
    source_run_id: str = Field(min_length=1, max_length=128)


class MediaLabImagePlanningJobResponse(BaseModel):
    job_id: str
    source_run_id: str
    state: Literal["planning", "ready", "needs_input", "failed"]
    source_asset_ids: list[str]
    user_request: str
    plan: MediaLabImagePlanResponse | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class MediaLabImageOutputPresetResponse(BaseModel):
    preset_id: str
    label: str
    aspect_ratio: str
    width: int
    height: int


class MediaLabImageCapabilityResponse(BaseModel):
    capability_id: str
    intent: ImageIntent
    label: str
    description: str
    required_roles: list[ImageReferenceRole]
    minimum_style_reference_count: int
    maximum_style_reference_count: int
    supports_output_size: bool
    candidate_count: int
    output_presets: list[MediaLabImageOutputPresetResponse]
    supported_output_formats: list[ImageOutputFormat]
    available: bool


class MediaLabImageCapabilitiesResponse(BaseModel):
    enabled: bool
    items: list[MediaLabImageCapabilityResponse]
    notice: str | None = None


class MediaLabImageReferenceResponse(BaseModel):
    reference_id: str
    role: ImageReferenceRole
    priority: int
    must_preserve: list[str]
    allowed_changes: list[str]
    source_origin: ImageSourceOrigin
    source_checksum_sha256: str
    source_run_id: str | None
    asset_id: str | None
    identity_group: str | None
    preview_url: str | None
    url: str


class MediaLabImageQualityIssueResponse(BaseModel):
    category: str
    severity: ImageQualityIssueSeverity
    description: str


class MediaLabImageQualityReviewResponse(BaseModel):
    decision: ImageQualityDecision
    summary: str
    issues: list[MediaLabImageQualityIssueResponse]
    repair_instructions: list[str]
    uncertainties: list[str]
    reviewer_model: str
    reviewer_prompt_version: str
    reviewer_prompt_hash: str
    reviewer_config_hash: str
    review_hash: str
    repair_prompt: str | None
    repair_prompt_version: str | None
    repair_prompt_hash: str | None


class MediaLabImageRetryAttemptResponse(BaseModel):
    run_id: str
    seed: int | None
    production_prompt: str
    output_asset_id: str | None
    output_checksum_sha256: str | None
    review_decision: ImageQualityDecision | None
    review_summary: str | None
    repair_instructions: list[str]
    repair_prompt: str | None


class MediaLabImageRetryMemoryResponse(BaseModel):
    root_run_id: str
    attempts: list[MediaLabImageRetryAttemptResponse]


class MediaLabImageRunResponse(BaseModel):
    run_id: str
    intent: ImageIntent
    production_prompt: str
    generation_state: ImageGenerationState
    review_state: ImageReviewState
    quality_review_state: ImageQualityReviewState
    quality_review: MediaLabImageQualityReviewResponse | None
    quality_review_error_code: str | None
    regenerated_run_id: str | None
    retry_of_run_id: str | None
    regeneration_count: int = Field(ge=0, le=2)
    model: str | None
    checkpoint_observation: str | None
    graph_template_hash: str | None
    seed: int | None
    references: list[MediaLabImageReferenceResponse]
    width: int | None
    height: int | None
    candidate_count: int
    output_preset_id: str | None
    aspect_ratio: str | None
    output_format: ImageOutputFormat
    parent_run_id: str | None
    orchestration: MediaLabImageOrchestrationTraceResponse | None
    provider_job_id: str | None
    queue_position: int | None
    queue_wait_milliseconds: int | None
    provider_delay_milliseconds: int | None
    provider_execution_milliseconds: int | None
    output_asset_id: str | None
    output_checksum_sha256: str | None
    output_url: str | None
    master_output_url: str | None
    retry_memory: MediaLabImageRetryMemoryResponse | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    reviewed_at: datetime | None


class MediaLabImageRunListResponse(BaseModel):
    items: list[MediaLabImageRunResponse]
    total: int


class MediaLabImageComparisonResponse(BaseModel):
    root_run_id: str
    candidates: list[MediaLabImageRunResponse]


class MediaLabImageReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


MediaLabVideoImageSourceRequest = MediaLabAssetReference


class MediaLabVideoPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_request: str = Field(min_length=1, max_length=6_000)
    sources: list[MediaLabVideoImageSourceRequest] = Field(
        default_factory=list, max_length=_MAX_VIDEO_IMAGE_SOURCES
    )


class MediaLabVideoOrchestrationTraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_request: str = Field(min_length=1, max_length=6_000)
    capability_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=4_000)
    planner_model: str = Field(min_length=1, max_length=256)
    planner_prompt_version: str = Field(min_length=1, max_length=256)
    planner_prompt_hash: str = Field(min_length=1, max_length=128)
    planner_config_hash: str = Field(min_length=1, max_length=128)
    plan_hash: str = Field(min_length=1, max_length=128)


class MediaLabVideoSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_index: int = Field(ge=0, lt=_MAX_VIDEO_IMAGE_SOURCES)
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int = Field(ge=1, le=100)
    must_preserve: list[str] = Field(default_factory=list, max_length=10)
    allowed_changes: list[str] = Field(default_factory=list, max_length=10)
    identity_group: str | None = Field(default=None, min_length=1, max_length=128)
    is_primary_identity: bool = False
    source: MediaLabVideoImageSourceRequest


class MediaLabVideoVerificationStagePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: VideoVerificationStage
    reason: str = Field(min_length=1, max_length=1_000)


class MediaLabVideoRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: VideoIntent
    prompt: str = Field(min_length=1, max_length=6_000)
    sources: list[MediaLabVideoSourceRequest] = Field(
        default_factory=list, max_length=_MAX_VIDEO_IMAGE_SOURCES
    )
    verification_plan: list[MediaLabVideoVerificationStagePlanRequest] = Field(
        min_length=1, max_length=3
    )
    duration_seconds: int = Field(ge=4, le=15)
    seed: int | None = Field(default=None, ge=0, le=_MAX_SEED)
    output_preset_id: str | None = Field(default=None, min_length=1, max_length=128)
    output_format: VideoOutputFormat = VideoOutputFormat.MP4
    orchestration: MediaLabVideoOrchestrationTraceRequest


class MediaLabVideoOrchestrationStatusResponse(BaseModel):
    enabled: bool
    model: str | None
    max_image_sources: int = Field(ge=0, le=_MAX_VIDEO_IMAGE_SOURCES)
    max_generation_image_sources: int = Field(ge=0, le=_MAX_VIDEO_IMAGE_SOURCES)
    quality_review_enabled: bool
    max_regenerations: int = Field(ge=0, le=1)
    notice: str | None


class MediaLabVideoPlanSourceResponse(BaseModel):
    source_index: int
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int
    must_preserve: list[str]
    allowed_changes: list[str]
    identity_group: str | None
    is_primary_identity: bool


class MediaLabVideoVerificationStagePlanResponse(BaseModel):
    stage: VideoVerificationStage
    reason: str


class MediaLabVideoOrchestrationTraceResponse(BaseModel):
    user_request: str
    capability_id: str
    summary: str
    planner_model: str
    planner_prompt_version: str
    planner_prompt_hash: str
    planner_config_hash: str
    plan_hash: str


class MediaLabVideoPlanResponse(BaseModel):
    state: Literal["ready", "needs_input"]
    summary: str
    questions: list[str]
    uncertainties: list[str]
    capability_id: str | None
    intent: VideoIntent | None
    production_prompt: str | None
    sources: list[MediaLabVideoPlanSourceResponse]
    verification_plan: list[MediaLabVideoVerificationStagePlanResponse]
    orchestration: MediaLabVideoOrchestrationTraceResponse


class MediaLabVideoPlanningJobRequest(MediaLabVideoPlanningRequest):
    source_run_id: str = Field(min_length=1, max_length=128)


class MediaLabVideoPlanningJobResponse(BaseModel):
    job_id: str
    source_run_id: str
    state: Literal["planning", "ready", "needs_input", "failed"]
    source_asset_ids: list[str]
    user_request: str
    plan: MediaLabVideoPlanResponse | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class MediaLabVideoOutputPresetResponse(BaseModel):
    preset_id: str
    label: str
    aspect_ratio: str
    megapixels: float


class MediaLabVideoCapabilityResponse(BaseModel):
    capability_id: str
    intent: VideoIntent
    label: str
    description: str
    minimum_generation_images: int
    maximum_generation_images: int
    supported_duration_seconds: list[int]
    candidate_count: int
    output_presets: list[MediaLabVideoOutputPresetResponse]
    supported_output_formats: list[VideoOutputFormat]
    default_output_preset_id: str | None
    available: bool


class MediaLabVideoCapabilitiesResponse(BaseModel):
    enabled: bool
    items: list[MediaLabVideoCapabilityResponse]
    notice: str | None = None


class MediaLabVideoSourceResponse(BaseModel):
    source_id: str
    source_index: int
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int
    must_preserve: list[str]
    allowed_changes: list[str]
    identity_group: str | None
    is_primary_identity: bool
    source_origin: VideoSourceOrigin
    source_checksum_sha256: str
    source_run_id: str | None
    asset_id: str | None
    preview_url: str | None
    url: str


class MediaLabVideoQualityIssueResponse(BaseModel):
    category: str
    severity: VideoQualityIssueSeverity
    description: str


class MediaLabVideoReviewFrameResponse(BaseModel):
    label: str
    timestamp_milliseconds: int
    checksum_sha256: str
    url: str


class MediaLabVideoVerificationObservationResponse(BaseModel):
    observation_id: str
    stage: str
    category: str
    status: str
    severity: VideoQualityIssueSeverity
    description: str
    confidence: float | None
    start_timestamp_milliseconds: int | None
    end_timestamp_milliseconds: int | None
    evidence_refs: list[str]


class MediaLabVideoVerificationStageResponse(BaseModel):
    stage: str
    status: str
    model: str
    model_version: str
    observations: list[MediaLabVideoVerificationObservationResponse]
    metadata: dict[str, str]


class MediaLabVideoVerificationResponse(BaseModel):
    status: str
    verifier_version: str
    config_hash: str
    request_hash: str
    stages: list[MediaLabVideoVerificationStageResponse]
    suspicious_timestamps_milliseconds: list[int]
    uncertainties: list[str]
    report_hash: str


class MediaLabVideoQualityReviewResponse(BaseModel):
    decision: VideoQualityDecision
    summary: str
    issues: list[MediaLabVideoQualityIssueResponse]
    repair_instructions: list[str]
    uncertainties: list[str]
    reviewer_model: str
    reviewer_prompt_version: str
    reviewer_prompt_hash: str
    reviewer_config_hash: str
    review_hash: str
    sampled_frames: list[MediaLabVideoReviewFrameResponse]
    temporal_sampling_rate_fps: int | None
    temporal_duration_milliseconds: int | None
    repair_prompt: str | None
    repair_prompt_version: str | None
    repair_prompt_hash: str | None
    verification: MediaLabVideoVerificationResponse | None


class MediaLabVideoRetryAttemptResponse(BaseModel):
    run_id: str
    seed: int | None
    production_prompt: str
    output_asset_id: str | None
    output_checksum_sha256: str | None
    duration_seconds: int
    output_preset_id: str | None
    review_decision: VideoQualityDecision | None
    review_summary: str | None
    repair_instructions: list[str]
    repair_prompt: str | None
    verifier_status: str | None
    suspicious_timestamps_milliseconds: list[int]


class MediaLabVideoRetryMemoryResponse(BaseModel):
    root_run_id: str
    attempts: list[MediaLabVideoRetryAttemptResponse]


class MediaLabVideoRunResponse(BaseModel):
    run_id: str
    intent: VideoIntent
    production_prompt: str
    generation_state: VideoGenerationState
    review_state: VideoReviewState
    quality_review_state: VideoQualityReviewState
    quality_review: MediaLabVideoQualityReviewResponse | None
    quality_review_error_code: str | None
    verification_state: VideoVerificationState
    verification: MediaLabVideoVerificationResponse | None
    verification_frames: list[MediaLabVideoReviewFrameResponse]
    verification_error_code: str | None
    regenerated_run_id: str | None
    retry_of_run_id: str | None
    regeneration_count: int = Field(ge=0, le=1)
    model: str | None
    checkpoint_observation: str | None
    graph_template_hash: str | None
    seed: int | None
    sources: list[MediaLabVideoSourceResponse]
    verification_plan: list[MediaLabVideoVerificationStagePlanResponse]
    duration_seconds: int
    candidate_count: int
    output_preset_id: str | None
    aspect_ratio: str | None
    megapixels: float | None
    output_format: VideoOutputFormat
    actual_width: int | None
    actual_height: int | None
    actual_duration_milliseconds: int | None
    orchestration: MediaLabVideoOrchestrationTraceResponse | None
    provider_job_id: str | None
    queue_position: int | None
    queue_wait_milliseconds: int | None
    provider_delay_milliseconds: int | None
    provider_execution_milliseconds: int | None
    output_asset_id: str | None
    output_checksum_sha256: str | None
    output_url: str | None
    retry_memory: MediaLabVideoRetryMemoryResponse | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    reviewed_at: datetime | None


class MediaLabVideoRunListResponse(BaseModel):
    items: list[MediaLabVideoRunResponse]
    total: int


class MediaLabVideoComparisonResponse(BaseModel):
    root_run_id: str
    candidates: list[MediaLabVideoRunResponse]


class MediaLabVideoReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class MediaLabVideoProjectShotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(min_length=1, max_length=128)
    source_run_id: str = Field(min_length=1, max_length=128)
    trim_start_seconds: float = Field(ge=0)
    trim_end_seconds: float = Field(gt=0)


class MediaLabVideoProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=256)
    shots: list[MediaLabVideoProjectShotRequest] = Field(min_length=2, max_length=8)
    target_duration_seconds: float = Field(ge=20, le=25)


class MediaLabVideoProjectShotResponse(BaseModel):
    shot_id: str
    source_run_id: str
    trim_start_seconds: float
    trim_end_seconds: float
    duration_seconds: float


class MediaLabVideoProjectResponse(BaseModel):
    project_id: str
    source_run_id: str
    state: VideoProjectState
    shots: list[MediaLabVideoProjectShotResponse]
    target_duration_seconds: float
    source_asset_ids: list[str]
    output_asset_id: str | None
    output_checksum_sha256: str | None
    output_url: str | None
    actual_width: int | None
    actual_height: int | None
    actual_duration_milliseconds: int | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    reviewed_at: datetime | None


class MediaLabVideoProjectListResponse(BaseModel):
    items: list[MediaLabVideoProjectResponse]
    total: int


class MediaLabVideoProjectReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class MediaLabVideoAdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=256)
    user_request: str = Field(min_length=1, max_length=12_000)
    brand: str = Field(min_length=1, max_length=256)
    sku: str = Field(min_length=1, max_length=256)
    angle: str = Field(min_length=1, max_length=1_000)
    source_asset_ids: list[str] = Field(default_factory=list, max_length=8)
    target_duration_seconds: float = Field(default=22, ge=20, le=25)
    aspect_ratio: Literal["1:1", "9:16", "16:9"] = "9:16"
    candidate_count: int = Field(default=1, ge=1, le=3)
    cta_text: str | None = Field(default=None, max_length=500)
    logo_asset_id: str | None = Field(default=None, max_length=128)


class MediaLabVideoAdCandidateResponse(BaseModel):
    shot_id: str
    candidate_index: int
    run_id: str
    seed: int | None


class MediaLabVideoAdSegmentResponse(BaseModel):
    shot_id: str
    candidate_index: int
    run_id: str
    trim_start_seconds: float
    trim_end_seconds: float
    score: float
    observations: list[str]


class MediaLabVideoAdSourceResponse(BaseModel):
    source_index: int
    role: VideoSourceRole
    usage: VideoSourceUsage
    priority: int
    must_preserve: list[str]
    allowed_changes: list[str]
    identity_group: str | None
    is_primary_identity: bool


class MediaLabVideoAdShotResponse(BaseModel):
    shot_id: str
    purpose: str
    prompt: str
    intent: VideoIntent
    source_indexes: list[int]
    generation_duration_seconds: int
    usable_duration_seconds: float
    on_screen_text: str | None


class MediaLabVideoAdResponse(BaseModel):
    job_id: str
    source_run_id: str
    state: VideoAdJobState
    user_request: str
    brand: str
    sku: str
    angle: str
    target_duration_seconds: float
    aspect_ratio: str
    candidate_count: int
    cta_text: str | None
    summary: str | None
    planner_prompt_version: str | None
    plan_hash: str | None
    questions: list[str]
    uncertainties: list[str]
    sources: list[MediaLabVideoAdSourceResponse]
    shots: list[MediaLabVideoAdShotResponse]
    candidates: list[MediaLabVideoAdCandidateResponse]
    selected_segments: list[MediaLabVideoAdSegmentResponse]
    output_asset_id: str | None
    output_checksum_sha256: str | None
    output_url: str | None
    actual_width: int | None
    actual_height: int | None
    actual_duration_milliseconds: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class MediaLabVideoAdListResponse(BaseModel):
    items: list[MediaLabVideoAdResponse]
    total: int


class _UploadResponse(BaseModel):
    name: str = Field(min_length=1)


class _SubmitResponse(BaseModel):
    prompt_id: str = Field(pattern=r"^[A-Za-z0-9-]+$")


class _OutputMedia(BaseModel):
    filename: str = Field(min_length=1)
    subfolder: str = ""
    type: str = "output"


class _JobResponse(BaseModel):
    status: str = Field(min_length=1)
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class _RunpodSubmitResponse(BaseModel):
    id: str = Field(min_length=1)


class _RunpodOutputMedia(BaseModel):
    filename: str = Field(min_length=1)
    type: str = Field(min_length=1)
    data: str = Field(min_length=1)


class _RunpodOutput(BaseModel):
    images: list[_RunpodOutputMedia] = Field(default_factory=list)
    videos: list[_RunpodOutputMedia] = Field(default_factory=list)


class _RunpodJobResponse(BaseModel):
    status: str = Field(min_length=1)
    output: _RunpodOutput | None = None
    delay_time: int | None = Field(default=None, alias="delayTime", ge=0)
    execution_time: int | None = Field(default=None, alias="executionTime", ge=0)


@dataclass(frozen=True)
class _UploadedMedia:
    content: bytes
    extension: str
    content_type: str


@dataclass(frozen=True)
class _PreparedRun:
    prompt: str
    seed: int
    inputs: tuple[_UploadedMedia, ...]
    input_nodes: tuple[str, ...]
    width: int | None
    height: int | None
    duration_seconds: int | None
    selector_aspect_ratio: str | None = None
    megapixels: float | None = None


@dataclass
class _Run:
    run_id: str
    spec: _WorkflowSpec
    seed: int
    width: int | None
    height: int | None
    duration_seconds: int | None
    created_at: datetime
    status: LegacyMediaGraphRunStatus = LegacyMediaGraphRunStatus.QUEUED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_path: Path | None = None
    output_media_type: str | None = None
    provider_job_id: str | None = None
    queue_wait_milliseconds: int | None = None
    provider_delay_milliseconds: int | None = None
    provider_execution_milliseconds: int | None = None
    error_code: str | None = None


def build_legacy_media_graph_service(
    config_dir: Path,
    artifacts_root: Path,
    comfyui_url: str | None,
    *,
    video_comfyui_url: str | None = None,
    image_runpod_endpoint_id: str | None = None,
    image_runpod_api_key: str | None = None,
    video_runpod_endpoint_id: str | None = None,
    video_runpod_api_key: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LegacyMediaGraphService:
    """Build the opt-in lab service from server configuration only."""
    if comfyui_url:
        _validate_base_url(comfyui_url)
    if video_comfyui_url:
        _validate_base_url(video_comfyui_url)
    return LegacyMediaGraphService(
        config_dir=config_dir,
        output_dir=artifacts_root / "media-lab",
        settings=LegacyMediaGraphSettings(
            image_base_url=comfyui_url,
            video_base_url=video_comfyui_url or comfyui_url,
            image_runpod_endpoint_id=image_runpod_endpoint_id,
            image_runpod_api_key=image_runpod_api_key,
            video_runpod_endpoint_id=video_runpod_endpoint_id,
            video_runpod_api_key=video_runpod_api_key,
        ),
        transport=transport,
    )


class LegacyMediaGraphService:
    """Dispatch Serverless jobs immediately and serialize Pod jobs per media type."""

    def __init__(
        self,
        config_dir: Path,
        output_dir: Path,
        settings: LegacyMediaGraphSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.image_base_url:
            _validate_base_url(settings.image_base_url)
        if settings.video_base_url:
            _validate_base_url(settings.video_base_url)
        self._config_dir = config_dir
        self._output_dir = output_dir
        self._settings = settings
        self._transport = transport
        self._runs: dict[str, _Run] = {}
        self._queues: dict[
            str, asyncio.Queue[tuple[_Run, dict[str, dict[str, Any]], _PreparedRun]]
        ] = {"image": asyncio.Queue(), "video": asyncio.Queue()}
        self._worker_tasks: dict[str, asyncio.Task[None] | None] = {
            "image": None,
            "video": None,
        }
        self._active_run_ids: dict[str, str | None] = {"image": None, "video": None}
        self._provider_run_tasks: set[asyncio.Task[None]] = set()
        self._image_observers: list[ImageBackendObserver] = []
        self._video_observers: list[VideoBackendObserver] = []

    def catalog(self) -> LegacyMediaGraphCatalog:
        workflows_valid = self._workflows_are_valid()
        enabled = self._settings.configured() and workflows_valid
        notice = None
        if not self._settings.configured():
            notice = "Set AIC_MEDIA_LAB_COMFYUI_URL on the API to enable this lab."
        elif not workflows_valid:
            notice = "Pinned Media Lab workflow files are unavailable or invalid."
        return LegacyMediaGraphCatalog(
            enabled=enabled,
            notice=notice,
            items=[
                LegacyMediaGraphModeInfo(
                    id=spec.mode,
                    label=spec.label,
                    model=spec.model,
                    media_type=spec.media_type,
                    description=spec.description,
                    input_count=_input_capacity(spec),
                    input_kind=spec.input_kind,
                    supports_resolution=bool(spec.size_nodes),
                    supports_duration=spec.duration_node is not None,
                    available=(self._settings.configured_for(spec.media_type) and workflows_valid),
                )
                for spec in _SPECS.values()
            ],
        )

    def image_generation_available(self) -> bool:
        return self._settings.configured_for("image") and self._image_workflows_are_valid()

    def image_generation_notice(self) -> str | None:
        if not self._settings.configured_for("image"):
            return "Configure an image ComfyUI URL or Runpod Serverless endpoint on the API."
        if not self._image_workflows_are_valid():
            return "Pinned FLUX.2 Dev image workflow files are unavailable or invalid."
        return None

    def video_generation_available(self) -> bool:
        return self._settings.configured_for("video") and self._video_workflows_are_valid()

    def video_generation_notice(self) -> str | None:
        if not self._settings.configured_for("video"):
            return "Configure a video ComfyUI URL or Runpod Serverless endpoint on the API."
        if not self._video_workflows_are_valid():
            return "Pinned MiniMax H3 video workflow files are unavailable or invalid."
        return None

    def pinned_image_input_capacity(self, graph: PinnedImageGraph) -> int:
        mode_by_graph = {
            PinnedImageGraph.TEXT_TO_IMAGE: LegacyMediaGraphMode.TEXT_TO_IMAGE,
            PinnedImageGraph.PRODUCT_IMAGE_EDIT: LegacyMediaGraphMode.PRODUCT_TO_IMAGE,
            PinnedImageGraph.MULTI_REFERENCE: LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE,
        }
        mode = mode_by_graph.get(graph)
        if mode is None:
            raise LegacyMediaGraphError("Pinned image graph is invalid", code="invalid_workflow")
        return _input_capacity(_SPECS[mode])

    def add_image_observer(self, observer: ImageBackendObserver) -> None:
        self._image_observers.append(observer)

    def pinned_video_image_input_capacity(self, graph: PinnedVideoGraph) -> int:
        mode_by_graph = {
            PinnedVideoGraph.TEXT_TO_VIDEO: LegacyMediaGraphMode.TEXT_TO_VIDEO,
            PinnedVideoGraph.IMAGE_TO_VIDEO: LegacyMediaGraphMode.IMAGE_TO_VIDEO,
        }
        mode = mode_by_graph.get(graph)
        if mode is None:
            raise LegacyMediaGraphError("Pinned video graph is invalid", code="invalid_workflow")
        spec = _SPECS[mode]
        try:
            workflow = self._load_workflow(spec)
        except LegacyMediaGraphError:
            return 0
        return len(_video_input_nodes(spec, workflow))

    def add_video_observer(self, observer: VideoBackendObserver) -> None:
        self._video_observers.append(observer)

    async def submit(self, request: LegacyMediaGraphRunRequest) -> LegacyMediaGraphRunResponse:
        spec = _SPECS[request.mode]
        if not self._settings.configured_for(spec.media_type):
            raise LegacyMediaGraphError(
                "Media Lab is not configured", status_code=503, code="not_configured"
            )
        workflow = self._load_workflow(spec)
        prepared = self._prepare_request(request, spec)
        workflow, input_nodes = _bind_dynamic_image_inputs(spec, workflow, len(prepared.inputs))
        prepared = replace(prepared, input_nodes=input_nodes)
        run = self._enqueue(spec, workflow, prepared)
        return self._response(run)

    async def submit_pinned_image(self, generation: PinnedImageGeneration) -> ImageBackendRun:
        if not self.image_generation_available():
            raise LegacyMediaGraphError(
                "Media Lab is not configured", status_code=503, code="not_configured"
            )
        mode_by_graph = {
            PinnedImageGraph.TEXT_TO_IMAGE: LegacyMediaGraphMode.TEXT_TO_IMAGE,
            PinnedImageGraph.PRODUCT_IMAGE_EDIT: LegacyMediaGraphMode.PRODUCT_TO_IMAGE,
            PinnedImageGraph.MULTI_REFERENCE: LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE,
        }
        mode = mode_by_graph.get(generation.graph)
        if mode is None:
            raise LegacyMediaGraphError("Pinned image graph is invalid", code="invalid_workflow")
        spec = _SPECS[mode]
        if not _accepts_input_count(spec, len(generation.images)):
            raise LegacyMediaGraphError(
                "Pinned image graph received an invalid input count", code="invalid_input_count"
            )
        if not spec.size_nodes and (generation.width is not None or generation.height is not None):
            raise LegacyMediaGraphError(
                "This pinned graph uses source image dimensions", code="size_not_supported"
            )
        if spec.size_nodes and (generation.width is None or generation.height is None):
            raise LegacyMediaGraphError(
                "Pinned image graph requires dimensions", code="invalid_dimensions"
            )
        workflow = self._load_workflow(spec)
        workflow, input_nodes = _bind_dynamic_image_inputs(spec, workflow, len(generation.images))
        prepared = _PreparedRun(
            prompt=generation.prompt.strip(),
            seed=(generation.seed if generation.seed is not None else secrets.randbelow(_MAX_SEED)),
            inputs=tuple(
                _UploadedMedia(image.content, image.extension, image.content_type)
                for image in generation.images
            ),
            input_nodes=input_nodes,
            width=generation.width,
            height=generation.height,
            duration_seconds=None,
        )
        run = self._enqueue(spec, workflow, prepared)
        return ImageBackendRun(
            backend_run_id=run.run_id,
            model="FLUX.2 Dev",
            checkpoint_observation="UNET: flux2_dev_fp8mixed.safetensors",
            graph_template_hash=_workflow_hash(workflow),
            seed=run.seed,
        )

    async def submit_pinned_video(self, generation: PinnedVideoGeneration) -> VideoBackendRun:
        if not self.video_generation_available():
            raise LegacyMediaGraphError(
                "Media Lab is not configured", status_code=503, code="not_configured"
            )
        mode_by_graph = {
            PinnedVideoGraph.TEXT_TO_VIDEO: LegacyMediaGraphMode.TEXT_TO_VIDEO,
            PinnedVideoGraph.IMAGE_TO_VIDEO: LegacyMediaGraphMode.IMAGE_TO_VIDEO,
        }
        mode = mode_by_graph.get(generation.graph)
        if mode is None:
            raise LegacyMediaGraphError("Pinned video graph is invalid", code="invalid_workflow")
        spec = _SPECS[mode]
        workflow = self._load_workflow(spec)
        available_input_nodes = _video_input_nodes(spec, workflow)
        if mode == LegacyMediaGraphMode.TEXT_TO_VIDEO:
            valid_input_count = not generation.images and not available_input_nodes
        else:
            valid_input_count = 1 <= len(generation.images) <= len(available_input_nodes)
        if not valid_input_count:
            raise LegacyMediaGraphError(
                "Pinned video graph received an invalid input count", code="invalid_input_count"
            )
        prepared = _PreparedRun(
            prompt=generation.prompt.strip(),
            seed=(generation.seed if generation.seed is not None else secrets.randbelow(_MAX_SEED)),
            inputs=tuple(
                _UploadedMedia(image.content, image.extension, image.content_type)
                for image in generation.images
            ),
            input_nodes=available_input_nodes[: len(generation.images)],
            width=None,
            height=None,
            duration_seconds=generation.duration_seconds,
            selector_aspect_ratio=generation.selector_aspect_ratio,
            megapixels=generation.megapixels,
        )
        run = self._enqueue(spec, workflow, prepared)
        return VideoBackendRun(
            backend_run_id=run.run_id,
            model="MiniMax H3",
            checkpoint_observation="Pinned MiniMax H3 ComfyUI graph",
            graph_template_hash=_workflow_hash(workflow),
            seed=run.seed,
        )

    def _enqueue(
        self,
        spec: _WorkflowSpec,
        workflow: dict[str, dict[str, Any]],
        prepared: _PreparedRun,
    ) -> _Run:
        run = _Run(
            run_id=uuid4().hex,
            spec=spec,
            seed=prepared.seed,
            width=prepared.width,
            height=prepared.height,
            duration_seconds=prepared.duration_seconds,
            created_at=datetime.now(UTC),
        )
        self._runs[run.run_id] = run
        media_type = spec.media_type
        if self._runpod_configured_for(media_type):
            task = asyncio.create_task(self._execute(run, workflow, prepared))
            self._provider_run_tasks.add(task)
            task.add_done_callback(self._provider_run_task_done)
        else:
            self._queues[media_type].put_nowait((run, workflow, prepared))
            worker_task = self._worker_tasks[media_type]
            if worker_task is None or worker_task.done():
                self._worker_tasks[media_type] = asyncio.create_task(self._run_queue(media_type))
        return run

    def _runpod_configured_for(self, media_type: str) -> bool:
        if media_type == "image":
            return self._settings.runpod_image_configured()
        return self._settings.runpod_video_configured()

    def _provider_run_task_done(self, task: asyncio.Task[None]) -> None:
        self._provider_run_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.opt(exception=error).error("Unhandled Media Lab provider task failure")

    def queue_position(self, run_id: str) -> int | None:
        """Return the one-based position among queued jobs of the same media type."""
        run = self._runs.get(run_id)
        if (
            run is None
            or run.status != LegacyMediaGraphRunStatus.QUEUED
            or self._runpod_configured_for(run.spec.media_type)
        ):
            return None
        queued = sorted(
            (
                candidate
                for candidate in self._runs.values()
                if candidate.spec.media_type == run.spec.media_type
                and candidate.status == LegacyMediaGraphRunStatus.QUEUED
            ),
            key=lambda candidate: (candidate.created_at, candidate.run_id),
        )
        return next(
            (
                index
                for index, candidate in enumerate(queued, start=1)
                if candidate.run_id == run_id
            ),
            None,
        )

    def get_run(self, run_id: str) -> LegacyMediaGraphRunResponse:
        run = self._runs.get(run_id)
        if run is None:
            raise LegacyMediaGraphError(
                "Media Lab run was not found", status_code=404, code="not_found"
            )
        return self._response(run)

    def output_file(self, run_id: str) -> tuple[Path, str]:
        run = self._runs.get(run_id)
        if run is None:
            raise LegacyMediaGraphError(
                "Media Lab run was not found", status_code=404, code="not_found"
            )
        if run.status != LegacyMediaGraphRunStatus.SUCCEEDED or run.output_path is None:
            raise LegacyMediaGraphError(
                "Media output is not ready", status_code=409, code="output_not_ready"
            )
        if not run.output_path.is_file() or run.output_media_type is None:
            raise LegacyMediaGraphError(
                "Media output is unavailable", status_code=404, code="output_missing"
            )
        return run.output_path, run.output_media_type

    async def close(self) -> None:
        """Cancel active ad-hoc lab jobs during API shutdown."""
        worker_tasks = [task for task in self._worker_tasks.values() if task is not None]
        active_tasks = [*worker_tasks, *self._provider_run_tasks]
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        for queue in self._queues.values():
            while not queue.empty():
                run, _, _ = queue.get_nowait()
                run.status = LegacyMediaGraphRunStatus.CANCELLED
                run.completed_at = datetime.now(UTC)
                run.error_code = "cancelled"
                await self._notify_image_observers(run)
                await self._notify_video_observers(run)
                queue.task_done()

    async def _run_queue(self, media_type: str) -> None:
        queue = self._queues[media_type]
        try:
            while True:
                try:
                    run, workflow, prepared = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                self._active_run_ids[media_type] = run.run_id
                try:
                    await self._execute(run, workflow, prepared)
                finally:
                    queue.task_done()
        finally:
            self._active_run_ids[media_type] = None

    async def _execute(
        self,
        run: _Run,
        workflow: dict[str, dict[str, Any]],
        prepared: _PreparedRun,
    ) -> None:
        run.status = LegacyMediaGraphRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        run.queue_wait_milliseconds = max(
            0, int((run.started_at - run.created_at).total_seconds() * 1_000)
        )
        await self._notify_image_observers(run)
        await self._notify_video_observers(run)
        started = monotonic()
        try:
            workflow[run.spec.prompt_node]["inputs"][run.spec.prompt_input] = prepared.prompt
            workflow[run.spec.seed_node]["inputs"]["noise_seed"] = prepared.seed
            if prepared.width is not None and prepared.height is not None:
                for node_id in run.spec.size_nodes:
                    workflow[node_id]["inputs"]["width"] = prepared.width
                    workflow[node_id]["inputs"]["height"] = prepared.height
            if run.spec.duration_node is not None and prepared.duration_seconds is not None:
                workflow[run.spec.duration_node]["inputs"]["value"] = prepared.duration_seconds
            if (
                run.spec.resolution_selector_node is not None
                and prepared.selector_aspect_ratio is not None
                and prepared.megapixels is not None
            ):
                selector_inputs = workflow[run.spec.resolution_selector_node]["inputs"]
                if "aspect_ratio" not in selector_inputs or "megapixels" not in selector_inputs:
                    raise LegacyMediaGraphError(
                        "Pinned video resolution selector is invalid",
                        code="invalid_workflow",
                    )
                selector_inputs["aspect_ratio"] = prepared.selector_aspect_ratio
                selector_inputs["megapixels"] = prepared.megapixels

            if (run.spec.media_type == "image" and self._settings.runpod_image_configured()) or (
                run.spec.media_type == "video" and self._settings.runpod_video_configured()
            ):
                content, filename = await self._execute_runpod(run, workflow, prepared)
            else:
                content, filename = await self._execute_comfyui(run, workflow, prepared)

            extension, media_type = _validate_output(content, filename, run.spec.media_type)
            self._output_dir.mkdir(parents=True, exist_ok=True)
            target = self._output_dir / f"{run.run_id}{extension}"
            await asyncio.to_thread(target.write_bytes, content)
            run.output_path = target
            run.output_media_type = media_type
            run.status = LegacyMediaGraphRunStatus.SUCCEEDED
            logger.info(
                "Media Lab run {} completed: mode={}, job={}, queue_wait_ms={}, "
                "provider_delay_ms={}, provider_execution_ms={}, elapsed={:.2f}s",
                run.run_id,
                run.spec.mode,
                run.provider_job_id,
                run.queue_wait_milliseconds,
                run.provider_delay_milliseconds,
                run.provider_execution_milliseconds,
                monotonic() - started,
            )
        except asyncio.CancelledError:
            run.status = LegacyMediaGraphRunStatus.CANCELLED
            run.error_code = "cancelled"
            raise
        except TimeoutError:
            run.status = LegacyMediaGraphRunStatus.FAILED
            run.error_code = "timeout"
            logger.warning(
                "Media Lab run {} timed out after submission={}",
                run.run_id,
                run.provider_job_id is not None,
            )
        except (
            httpx.HTTPError,
            OSError,
            ValidationError,
            ValueError,
            LegacyMediaGraphError,
        ) as exc:
            run.status = LegacyMediaGraphRunStatus.FAILED
            run.error_code = "generation_failed"
            logger.warning(
                "Media Lab run {} failed: type={}, submitted={}, job={}",
                run.run_id,
                type(exc).__name__,
                run.provider_job_id is not None,
                run.provider_job_id,
            )
        finally:
            run.completed_at = datetime.now(UTC)
            await self._notify_image_observers(run)
            await self._notify_video_observers(run)

    async def _execute_comfyui(
        self,
        run: _Run,
        workflow: dict[str, dict[str, Any]],
        prepared: _PreparedRun,
    ) -> tuple[bytes, str]:
        base_url = self._settings.base_url_for(run.spec.media_type)
        if base_url is None:
            raise LegacyMediaGraphError(
                "Media Lab provider is not configured",
                status_code=503,
                code="not_configured",
            )
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(self._settings.request_timeout_seconds, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        ) as client:
            async with asyncio.timeout(run.spec.timeout_seconds):
                for index, (node_id, media) in enumerate(
                    zip(prepared.input_nodes, prepared.inputs, strict=True)
                ):
                    workflow[node_id]["inputs"][run.spec.input_name] = await self._upload(
                        client, run.run_id, index, media
                    )
                response = await client.post("/api/prompt", json={"prompt": workflow})
                response.raise_for_status()
                prompt_id = _SubmitResponse.model_validate_json(response.content).prompt_id
                run.provider_job_id = prompt_id
                await self._notify_image_observers(run)
                await self._notify_video_observers(run)
                job = await self._wait_for_completion(client, prompt_id)
                media = _select_output(job, run.spec)
                content = await self._download(client, media)
        return content, media.filename

    async def _execute_runpod(
        self,
        run: _Run,
        workflow: dict[str, dict[str, Any]],
        prepared: _PreparedRun,
    ) -> tuple[bytes, str]:
        endpoint_id, api_key = self._settings.runpod_credentials_for(run.spec.media_type)
        if endpoint_id is None or api_key is None:
            raise LegacyMediaGraphError(
                f"Runpod Serverless {run.spec.media_type} provider is not configured",
                status_code=503,
                code="not_configured",
            )
        images = []
        for index, (node_id, media) in enumerate(
            zip(prepared.input_nodes, prepared.inputs, strict=True)
        ):
            name = f"media-lab-{run.run_id}-{index}{media.extension}"
            workflow[node_id]["inputs"][run.spec.input_name] = name
            encoded = base64.b64encode(media.content).decode("ascii")
            images.append(
                {
                    "name": name,
                    "image": f"data:{media.content_type};base64,{encoded}",
                }
            )
        provider_input: dict[str, Any] = {"workflow": workflow}
        if images:
            provider_input["images"] = images
        payload = {"input": provider_input}
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > _MAX_RUNPOD_REQUEST_BYTES:
            raise LegacyMediaGraphError(
                f"Runpod Serverless {run.spec.media_type} request exceeds the 9 MB safety limit",
                code="request_too_large",
            )
        async with httpx.AsyncClient(
            base_url=f"https://api.runpod.ai/v2/{endpoint_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(self._settings.request_timeout_seconds, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        ) as client:
            async with asyncio.timeout(run.spec.timeout_seconds):
                response = await client.post(
                    "/run",
                    content=payload_bytes,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                job_id = _RunpodSubmitResponse.model_validate_json(response.content).id
                run.provider_job_id = job_id
                await self._notify_image_observers(run)
                await self._notify_video_observers(run)
                job = await self._wait_for_runpod_completion(
                    client, job_id, media_type=run.spec.media_type
                )
                run.provider_delay_milliseconds = job.delay_time
                run.provider_execution_milliseconds = job.execution_time
        return _decode_runpod_media(job, run.spec.media_type)

    async def _wait_for_runpod_completion(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        *,
        media_type: str,
    ) -> _RunpodJobResponse:
        consecutive_transport_errors = 0
        while True:
            try:
                response = await client.get(f"/status/{job_id}")
            except httpx.TransportError as error:
                consecutive_transport_errors += 1
                if consecutive_transport_errors >= _MAX_POLL_TRANSPORT_ERRORS:
                    raise
                logger.warning(
                    "Runpod {} job {} poll transport error {}/{}: {}",
                    media_type,
                    job_id,
                    consecutive_transport_errors,
                    _MAX_POLL_TRANSPORT_ERRORS,
                    type(error).__name__,
                )
                await asyncio.sleep(self._settings.poll_interval_seconds)
                continue
            consecutive_transport_errors = 0
            response.raise_for_status()
            job = _RunpodJobResponse.model_validate_json(response.content)
            status = job.status.upper()
            if status == "COMPLETED":
                return job
            if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                raise LegacyMediaGraphError(
                    f"Runpod Serverless {media_type} generation failed",
                    code="provider_job_failed",
                )
            if status not in {"IN_QUEUE", "IN_PROGRESS"}:
                raise LegacyMediaGraphError(
                    "Runpod Serverless returned an unknown job status",
                    code="invalid_response",
                )
            await asyncio.sleep(self._settings.poll_interval_seconds)

    def _prepare_request(
        self, request: LegacyMediaGraphRunRequest, spec: _WorkflowSpec
    ) -> _PreparedRun:
        if spec.input_kind == "image":
            if request.videos:
                raise LegacyMediaGraphError(
                    "This workflow does not accept video inputs", code="invalid_input"
                )
            inputs = tuple(_decode_image(item) for item in request.images)
        elif spec.input_kind == "video":
            if request.images:
                raise LegacyMediaGraphError(
                    "This workflow does not accept image inputs", code="invalid_input"
                )
            inputs = tuple(_decode_video(item) for item in request.videos)
        else:
            if request.images or request.videos:
                raise LegacyMediaGraphError(
                    "This workflow does not accept reference inputs", code="invalid_input"
                )
            inputs = ()
        if not _accepts_input_count(spec, len(inputs)):
            input_label = spec.input_kind or "reference"
            required = (
                f"between 2 and {_MAX_IMAGE_SOURCES}"
                if spec.mode == LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE
                else f"exactly {len(spec.input_nodes)}"
            )
            raise LegacyMediaGraphError(
                f"{spec.label} requires {required} {input_label} input(s)",
                code="invalid_input_count",
            )
        width, height = _resolve_dimensions(request, spec)
        if spec.duration_node is None and request.duration_seconds is not None:
            raise LegacyMediaGraphError(
                "This workflow does not accept a duration", code="duration_not_supported"
            )
        duration = request.duration_seconds if spec.duration_node is not None else None
        if spec.duration_node is not None:
            duration = duration or 10
        return _PreparedRun(
            prompt=request.prompt.strip(),
            seed=request.seed if request.seed is not None else secrets.randbelow(_MAX_SEED),
            inputs=inputs,
            input_nodes=spec.input_nodes,
            width=width,
            height=height,
            duration_seconds=duration,
        )

    def _load_workflow(self, spec: _WorkflowSpec) -> dict[str, dict[str, Any]]:
        path = self._config_dir / spec.workflow_file
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LegacyMediaGraphError(
                "Pinned Media Lab workflow is unavailable",
                status_code=503,
                code="invalid_workflow",
            ) from exc
        if not isinstance(workflow, dict) or "nodes" in workflow:
            raise LegacyMediaGraphError(
                "Pinned Media Lab workflow is invalid", status_code=503, code="invalid_workflow"
            )
        for node_id, class_type in spec.expected_nodes.items():
            node = workflow.get(node_id)
            if not isinstance(node, dict) or node.get("class_type") != class_type:
                raise LegacyMediaGraphError(
                    "Pinned Media Lab workflow is invalid",
                    status_code=503,
                    code="invalid_workflow",
                )
            if not isinstance(node.get("inputs"), dict):
                raise LegacyMediaGraphError(
                    "Pinned Media Lab workflow is invalid",
                    status_code=503,
                    code="invalid_workflow",
                )
        return deepcopy(workflow)

    def _workflows_are_valid(self) -> bool:
        try:
            for spec in _SPECS.values():
                self._load_workflow(spec)
        except LegacyMediaGraphError:
            return False
        return True

    def _image_workflows_are_valid(self) -> bool:
        try:
            for spec in _SPECS.values():
                if spec.media_type == "image":
                    self._load_workflow(spec)
        except LegacyMediaGraphError:
            return False
        return True

    def _video_workflows_are_valid(self) -> bool:
        try:
            for spec in _SPECS.values():
                if spec.media_type == "video":
                    self._load_workflow(spec)
        except LegacyMediaGraphError:
            return False
        return True

    async def _notify_image_observers(self, run: _Run) -> None:
        if run.spec.media_type != "image" or not self._image_observers:
            return
        state = (
            ImageGenerationState.INTERRUPTED
            if run.status == LegacyMediaGraphRunStatus.CANCELLED
            else ImageGenerationState(run.status)
        )
        update = ImageBackendUpdate(
            backend_run_id=run.run_id,
            state=state,
            provider_job_id=run.provider_job_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            output_path=run.output_path,
            output_content_type=run.output_media_type,
            error_code=run.error_code,
            queue_wait_milliseconds=run.queue_wait_milliseconds,
            provider_delay_milliseconds=run.provider_delay_milliseconds,
            provider_execution_milliseconds=run.provider_execution_milliseconds,
        )
        for observer in tuple(self._image_observers):
            try:
                await observer(update)
            except Exception as exc:
                logger.exception(
                    "Media Lab image persistence observer failed for {}: {}",
                    run.run_id,
                    type(exc).__name__,
                )

    async def _notify_video_observers(self, run: _Run) -> None:
        if run.spec.media_type != "video" or not self._video_observers:
            return
        state = (
            VideoGenerationState.INTERRUPTED
            if run.status == LegacyMediaGraphRunStatus.CANCELLED
            else VideoGenerationState(run.status)
        )
        update = VideoBackendUpdate(
            backend_run_id=run.run_id,
            state=state,
            provider_job_id=run.provider_job_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            output_path=run.output_path,
            output_content_type=run.output_media_type,
            error_code=run.error_code,
            queue_wait_milliseconds=run.queue_wait_milliseconds,
            provider_delay_milliseconds=run.provider_delay_milliseconds,
            provider_execution_milliseconds=run.provider_execution_milliseconds,
        )
        for observer in tuple(self._video_observers):
            try:
                await observer(update)
            except Exception as exc:
                logger.exception(
                    "Media Lab video persistence observer failed for {}: {}",
                    run.run_id,
                    type(exc).__name__,
                )

    async def _upload(
        self,
        client: httpx.AsyncClient,
        run_id: str,
        index: int,
        media: _UploadedMedia,
    ) -> str:
        response = await client.post(
            "/upload/image",
            files={
                "image": (
                    f"media-lab-{run_id}-{index}{media.extension}",
                    media.content,
                    media.content_type,
                )
            },
            data={"type": "input", "overwrite": "false"},
        )
        response.raise_for_status()
        return _UploadResponse.model_validate_json(response.content).name

    async def _wait_for_completion(self, client: httpx.AsyncClient, prompt_id: str) -> _JobResponse:
        consecutive_transport_errors = 0
        while True:
            try:
                response = await client.get(f"/api/jobs/{prompt_id}")
            except httpx.TransportError as error:
                consecutive_transport_errors += 1
                if consecutive_transport_errors >= _MAX_POLL_TRANSPORT_ERRORS:
                    raise
                logger.warning(
                    "Media Lab job {} poll transport error {}/{}: {}",
                    prompt_id,
                    consecutive_transport_errors,
                    _MAX_POLL_TRANSPORT_ERRORS,
                    type(error).__name__,
                )
                await asyncio.sleep(self._settings.poll_interval_seconds)
                continue
            consecutive_transport_errors = 0
            response.raise_for_status()
            job = _JobResponse.model_validate_json(response.content)
            if job.status == "completed":
                return job
            if job.status in {"failed", "cancelled", "error"}:
                raise LegacyMediaGraphError("ComfyUI generation failed", code="provider_job_failed")
            if job.status not in {"pending", "running", "queued", "in_progress"}:
                raise LegacyMediaGraphError(
                    "ComfyUI returned an unknown job status", code="invalid_response"
                )
            await asyncio.sleep(self._settings.poll_interval_seconds)

    async def _download(self, client: httpx.AsyncClient, media: _OutputMedia) -> bytes:
        content = bytearray()
        async with client.stream(
            "GET",
            "/api/view",
            params={"filename": media.filename, "subfolder": media.subfolder, "type": media.type},
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 100_000_000:
                    raise LegacyMediaGraphError("Generated media exceeds the Media Lab byte limit")
        return bytes(content)

    def _response(self, run: _Run) -> LegacyMediaGraphRunResponse:
        return LegacyMediaGraphRunResponse(
            run_id=run.run_id,
            mode=run.spec.mode,
            status=run.status,
            model=run.spec.model,
            media_type=run.spec.media_type,
            seed=run.seed,
            width=run.width,
            height=run.height,
            duration_seconds=run.duration_seconds,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            output_url=(f"/api/v1/media-lab/runs/{run.run_id}/output" if run.output_path else None),
            queue_position=self.queue_position(run.run_id),
            queue_wait_milliseconds=run.queue_wait_milliseconds,
            provider_delay_milliseconds=run.provider_delay_milliseconds,
            provider_execution_milliseconds=run.provider_execution_milliseconds,
            error_code=run.error_code,
        )


def _input_capacity(spec: _WorkflowSpec) -> int:
    if spec.mode == LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE:
        return _MAX_IMAGE_SOURCES
    return len(spec.input_nodes)


def _accepts_input_count(spec: _WorkflowSpec, count: int) -> bool:
    if spec.mode == LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE:
        return 2 <= count <= _MAX_IMAGE_SOURCES
    return count == len(spec.input_nodes)


def _bind_dynamic_image_inputs(
    spec: _WorkflowSpec,
    workflow: dict[str, dict[str, Any]],
    input_count: int,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    if spec.mode != LegacyMediaGraphMode.MULTI_REFERENCE_TO_IMAGE:
        return workflow, spec.input_nodes
    if not _accepts_input_count(spec, input_count):
        raise LegacyMediaGraphError(
            f"Multiple references to image requires between 2 and {_MAX_IMAGE_SOURCES} images",
            code="invalid_input_count",
        )

    dynamic_node_ids = {
        node_id
        for node_id, node in workflow.items()
        if node.get("_meta", {}).get("dynamic_multi_reference") is True
    }
    for node_id in dynamic_node_ids:
        workflow.pop(node_id, None)

    branches = [
        ("46", "45", "44", "49"),
        ("42", "41", "40", "50"),
    ]
    input_nodes: list[str] = []
    conditioning: list[Any] = [spec.prompt_node, 0]
    for index in range(input_count):
        if index < len(branches):
            load_node, scale_node, encode_node, reference_node = branches[index]
        else:
            prefix = f"dynamic_ref_{index + 1}"
            load_node = f"{prefix}_load"
            scale_node = f"{prefix}_scale"
            encode_node = f"{prefix}_encode"
            reference_node = f"{prefix}_condition"
        metadata = {
            "title": f"Reference {index + 1}",
            "dynamic_multi_reference": True,
        }
        workflow[load_node] = {
            "inputs": {"image": f"reference-{index + 1}.png"},
            "class_type": "LoadImage",
            "_meta": metadata,
        }
        workflow[scale_node] = {
            "inputs": {
                "upscale_method": "area",
                "megapixels": 1,
                "resolution_steps": 1,
                "image": [load_node, 0],
            },
            "class_type": "ImageScaleToTotalPixels",
            "_meta": metadata,
        }
        workflow[encode_node] = {
            "inputs": {"pixels": [scale_node, 0], "vae": ["10", 0]},
            "class_type": "VAEEncode",
            "_meta": metadata,
        }
        workflow[reference_node] = {
            "inputs": {"conditioning": conditioning, "latent": [encode_node, 0]},
            "class_type": "ReferenceLatent",
            "_meta": metadata,
        }
        input_nodes.append(load_node)
        conditioning = [reference_node, 0]
    workflow["26"]["inputs"]["conditioning"] = conditioning
    return workflow, tuple(input_nodes)


def _video_input_nodes(
    spec: _WorkflowSpec,
    workflow: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    if spec.mode != LegacyMediaGraphMode.IMAGE_TO_VIDEO:
        return spec.input_nodes
    indexed_nodes: list[tuple[int, str]] = []
    for node_id, node in workflow.items():
        index = node.get("_meta", {}).get("media_lab_video_source_index")
        if isinstance(index, int) and index >= 0 and node.get("class_type") == "LoadImage":
            indexed_nodes.append((index, node_id))
    if not indexed_nodes:
        return spec.input_nodes
    indexed_nodes.sort()
    if [index for index, _ in indexed_nodes] != list(range(len(indexed_nodes))):
        raise LegacyMediaGraphError(
            "Pinned video source indexes must be consecutive", code="invalid_workflow"
        )
    return tuple(node_id for _, node_id in indexed_nodes)


def _workflow_hash(workflow: dict[str, dict[str, Any]]) -> str:
    payload = json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decode_image(image: LegacyMediaGraphInputImage) -> _UploadedMedia:
    try:
        content = base64.b64decode(image.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LegacyMediaGraphError(
            "Image upload is not valid base64", code="invalid_image"
        ) from exc
    if len(content) > _MAX_IMAGE_BYTES:
        raise LegacyMediaGraphError("Each image must be 12 MB or smaller", code="image_too_large")
    try:
        _, _, image_format = inspect_image(content)
    except (ImageGenerationError, SyntaxError) as exc:
        raise LegacyMediaGraphError(
            "Image must be a valid PNG or JPEG", code="invalid_image"
        ) from exc
    return _UploadedMedia(
        content=content,
        extension=".jpg" if image_format == "jpeg" else ".png",
        content_type="image/jpeg" if image_format == "jpeg" else "image/png",
    )


def _decode_video(video: LegacyMediaGraphInputVideo) -> _UploadedMedia:
    try:
        content = base64.b64decode(video.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LegacyMediaGraphError(
            "Video upload is not valid base64", code="invalid_video"
        ) from exc
    if len(content) > _MAX_VIDEO_BYTES:
        raise LegacyMediaGraphError(
            "Reference video must be 25 MB or smaller", code="video_too_large"
        )
    if len(content) < 12 or content[4:8] != b"ftyp":
        raise LegacyMediaGraphError("Reference video must be a valid MP4", code="invalid_video")
    return _UploadedMedia(content=content, extension=".mp4", content_type="video/mp4")


def _resolve_dimensions(
    request: LegacyMediaGraphRunRequest, spec: _WorkflowSpec
) -> tuple[int | None, int | None]:
    if not spec.size_nodes:
        if request.width is not None or request.height is not None:
            raise LegacyMediaGraphError(
                "This workflow uses the dimensions pinned in its graph", code="size_not_supported"
            )
        return None, None
    width = request.width or 1024
    height = request.height or (1024 if spec.mode == LegacyMediaGraphMode.TEXT_TO_IMAGE else 1536)
    if (request.width is None) != (request.height is None):
        raise LegacyMediaGraphError(
            "Width and height must be provided together", code="invalid_dimensions"
        )
    if width % 16 or height % 16 or width * height > 4_194_304:
        raise LegacyMediaGraphError(
            "Width and height must be multiples of 16 and no more than 4 megapixels",
            code="invalid_dimensions",
        )
    return width, height


def _decode_runpod_media(job: _RunpodJobResponse, media_type: str) -> tuple[bytes, str]:
    if job.output is None:
        candidates = []
    elif media_type == "image":
        candidates = job.output.images
    else:
        candidates = job.output.videos
    if len(candidates) != 1:
        raise LegacyMediaGraphError(
            f"Runpod Serverless did not return exactly one {media_type}",
            code="invalid_response",
        )
    media = candidates[0]
    if media.type != "base64":
        raise LegacyMediaGraphError(
            f"Runpod Serverless {media_type} output must use base64",
            code="invalid_response",
        )
    try:
        content = base64.b64decode(media.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LegacyMediaGraphError(
            f"Runpod Serverless returned invalid {media_type} data",
            code="invalid_response",
        ) from exc
    if len(content) > 100_000_000:
        raise LegacyMediaGraphError("Generated media exceeds the Media Lab byte limit")
    return content, media.filename


def _select_output(job: _JobResponse, spec: _WorkflowSpec) -> _OutputMedia:
    output = job.outputs.get(spec.output_node, {})
    candidates = []
    for values in output.values():
        if not isinstance(values, list):
            continue
        for value in values:
            try:
                candidate = _OutputMedia.model_validate(value)
            except ValidationError:
                continue
            suffix = Path(candidate.filename).suffix.lower()
            if spec.media_type == "image" and suffix in {".png", ".jpg", ".jpeg"}:
                candidates.append(candidate)
            if spec.media_type == "video" and suffix == ".mp4":
                candidates.append(candidate)
    if len(candidates) != 1:
        raise LegacyMediaGraphError(
            "ComfyUI did not return exactly one final media file", code="invalid_response"
        )
    return candidates[0]


def _validate_output(content: bytes, filename: str, media_type: str) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if media_type == "video":
        if suffix != ".mp4" or len(content) < 12 or content[4:8] != b"ftyp":
            raise LegacyMediaGraphError(
                "ComfyUI output is not a valid MP4", code="invalid_response"
            )
        return ".mp4", "video/mp4"
    try:
        _, _, image_format = inspect_image(content)
    except (ImageGenerationError, SyntaxError) as exc:
        raise LegacyMediaGraphError(
            "ComfyUI output is not a valid image", code="invalid_response"
        ) from exc
    if image_format == "png":
        return ".png", "image/png"
    return ".jpg", "image/jpeg"


def _validate_base_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AIC_MEDIA_LAB_COMFYUI_URL must be an HTTP URL without credentials")


def get_media_lab_image_orchestration_service(
    request: Request,
) -> MediaLabImageOrchestrationService:
    service = getattr(request.app.state, "media_lab_image_orchestration_service", None)
    if not isinstance(service, MediaLabImageOrchestrationService):
        raise HTTPException(
            status_code=503,
            detail="Media Lab image orchestration is not configured",
        )
    return service


def get_media_lab_image_service(request: Request) -> MediaLabImageService:
    service = getattr(request.app.state, "media_lab_image_service", None)
    if not isinstance(service, MediaLabImageService):
        raise HTTPException(status_code=503, detail="Media Lab image workflow is unavailable")
    return service


def get_media_asset_service(request: Request) -> MediaAssetService:
    service = getattr(request.app.state, "media_asset_service", None)
    if not isinstance(service, MediaAssetService):
        raise HTTPException(status_code=503, detail="Media asset storage is unavailable")
    return service


def get_media_lab_planning_job_service(request: Request) -> MediaLabPlanningJobService:
    service = getattr(request.app.state, "media_lab_planning_job_service", None)
    if not isinstance(service, MediaLabPlanningJobService):
        raise HTTPException(status_code=503, detail="Media Lab planning is unavailable")
    return service


def get_media_lab_video_orchestration_service(
    request: Request,
) -> MediaLabVideoOrchestrationService:
    service = getattr(request.app.state, "media_lab_video_orchestration_service", None)
    if not isinstance(service, MediaLabVideoOrchestrationService):
        raise HTTPException(
            status_code=503,
            detail="Media Lab video orchestration is not configured",
        )
    return service


def get_media_lab_video_service(request: Request) -> MediaLabVideoService:
    service = getattr(request.app.state, "media_lab_video_service", None)
    if not isinstance(service, MediaLabVideoService):
        raise HTTPException(status_code=503, detail="Media Lab video workflow is unavailable")
    return service


def get_media_lab_video_ad_service(request: Request) -> MediaLabVideoAdService:
    service = getattr(request.app.state, "media_lab_video_ad_service", None)
    if not isinstance(service, MediaLabVideoAdService):
        raise HTTPException(
            status_code=503, detail="Autonomous final Video Ad workflow is unavailable"
        )
    return service


def get_media_lab_video_project_service(request: Request) -> MediaLabVideoProjectService:
    service = getattr(request.app.state, "media_lab_video_project_service", None)
    if not isinstance(service, MediaLabVideoProjectService):
        raise HTTPException(status_code=503, detail="Media Lab final video assembly is unavailable")
    return service


def get_legacy_media_graph_service(request: Request) -> LegacyMediaGraphService:
    service = getattr(request.app.state, "legacy_media_graph_service", None)
    if not isinstance(service, LegacyMediaGraphService):
        raise HTTPException(status_code=503, detail="Media Lab is unavailable")
    return service


@router.get("/modes", response_model=LegacyMediaGraphCatalog, deprecated=True)
async def list_media_modes(
    service: LegacyMediaGraphService = Depends(get_legacy_media_graph_service),
) -> LegacyMediaGraphCatalog:
    return service.catalog()


@router.post("/runs", response_model=LegacyMediaGraphRunResponse, status_code=202, deprecated=True)
async def create_media_run(
    payload: LegacyMediaGraphRunRequest,
    service: LegacyMediaGraphService = Depends(get_legacy_media_graph_service),
) -> LegacyMediaGraphRunResponse:
    try:
        return await service.submit(payload)
    except LegacyMediaGraphError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=LegacyMediaGraphRunResponse, deprecated=True)
async def get_media_run(
    run_id: str,
    service: LegacyMediaGraphService = Depends(get_legacy_media_graph_service),
) -> LegacyMediaGraphRunResponse:
    try:
        return service.get_run(run_id)
    except LegacyMediaGraphError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/runs/{run_id}/output", response_class=FileResponse, deprecated=True)
async def get_media_output(
    run_id: str,
    service: LegacyMediaGraphService = Depends(get_legacy_media_graph_service),
) -> FileResponse:
    try:
        path, media_type = service.output_file(run_id)
    except LegacyMediaGraphError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get(
    "/image-orchestration",
    response_model=MediaLabImageOrchestrationStatusResponse,
)
async def get_image_orchestration_status(
    request: Request,
) -> MediaLabImageOrchestrationStatusResponse:
    service = getattr(request.app.state, "media_lab_image_orchestration_service", None)
    if not isinstance(service, MediaLabImageOrchestrationService):
        return MediaLabImageOrchestrationStatusResponse(
            enabled=False,
            model=None,
            max_image_sources=0,
            quality_review_enabled=False,
            max_regenerations=0,
            notice="Set AIC_MEDIA_LAB_ORCHESTRATOR_CONFIG to enable image orchestration.",
        )
    image_service = getattr(request.app.state, "media_lab_image_service", None)
    quality_review_enabled = (
        image_service.quality_review_enabled()
        if isinstance(image_service, MediaLabImageService)
        else False
    )
    return MediaLabImageOrchestrationStatusResponse(
        enabled=True,
        model=service.model(),
        max_image_sources=service.maximum_source_count(),
        quality_review_enabled=quality_review_enabled,
        max_regenerations=(image_service.max_regenerations() if quality_review_enabled else 0),
        notice=None,
    )


@router.post("/image-plans", response_model=MediaLabImagePlanResponse)
async def plan_image_run(
    payload: MediaLabImagePlanningRequest,
    image_service: MediaLabImageService = Depends(get_media_lab_image_service),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
    orchestration_service: MediaLabImageOrchestrationService = Depends(
        get_media_lab_image_orchestration_service
    ),
) -> MediaLabImagePlanResponse:
    try:
        sources = await _to_image_planning_sources(payload.sources, media_assets)
        plan = await orchestration_service.plan(payload.user_request, sources)
    except (MediaAssetError, MediaLabImageError, MediaLabImageOrchestrationError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _image_plan_response(plan, image_service)


@router.post(
    "/image-plan-jobs",
    response_model=MediaLabImagePlanningJobResponse,
    status_code=202,
)
async def create_image_planning_job(
    payload: MediaLabImagePlanningJobRequest,
    image_service: MediaLabImageService = Depends(get_media_lab_image_service),
    service: MediaLabPlanningJobService = Depends(get_media_lab_planning_job_service),
) -> MediaLabImagePlanningJobResponse:
    try:
        job = await service.create(
            source_run_id=payload.source_run_id,
            kind=PlanningJobKind.IMAGE,
            user_request=payload.user_request,
            source_asset_ids=tuple(source.asset_id for source in payload.sources),
        )
    except MediaLabPlanningJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _image_planning_job_response(job, image_service)


@router.get("/image-plan-jobs/{job_id}", response_model=MediaLabImagePlanningJobResponse)
async def get_image_planning_job(
    job_id: str,
    image_service: MediaLabImageService = Depends(get_media_lab_image_service),
    service: MediaLabPlanningJobService = Depends(get_media_lab_planning_job_service),
) -> MediaLabImagePlanningJobResponse:
    try:
        job = await service.get(job_id)
    except MediaLabPlanningJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if job.kind != PlanningJobKind.IMAGE:
        raise HTTPException(status_code=404, detail="Image planning job was not found")
    return _image_planning_job_response(job, image_service)


@router.post(
    "/image-plan-jobs/{job_id}/draft",
    response_model=MediaLabImagePlanningJobResponse,
)
async def accept_image_planning_draft(
    job_id: str,
    image_service: MediaLabImageService = Depends(get_media_lab_image_service),
    service: MediaLabPlanningJobService = Depends(get_media_lab_planning_job_service),
) -> MediaLabImagePlanningJobResponse:
    try:
        job = await service.accept_image_draft(job_id)
    except (MediaAssetError, MediaLabImageOrchestrationError, MediaLabPlanningJobError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _image_planning_job_response(job, image_service)


@router.get("/image-capabilities", response_model=MediaLabImageCapabilitiesResponse)
async def list_image_capabilities(
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> MediaLabImageCapabilitiesResponse:
    enabled = service.enabled()
    return MediaLabImageCapabilitiesResponse(
        enabled=enabled,
        notice=service.notice(),
        items=[
            MediaLabImageCapabilityResponse(
                capability_id=item.capability_id,
                intent=item.intent,
                label=item.label,
                description=item.description,
                required_roles=list(item.required_roles),
                minimum_style_reference_count=item.minimum_style_reference_count,
                maximum_style_reference_count=item.maximum_style_reference_count,
                supports_output_size=item.supports_output_size,
                candidate_count=item.candidate_count,
                output_presets=[
                    MediaLabImageOutputPresetResponse(
                        preset_id=preset.preset_id,
                        label=preset.label,
                        aspect_ratio=preset.aspect_ratio,
                        width=preset.width,
                        height=preset.height,
                    )
                    for preset in item.output_presets
                ],
                supported_output_formats=list(item.supported_output_formats),
                available=enabled,
            )
            for item in service.capabilities()
        ],
    )


@router.post("/image-runs", response_model=MediaLabImageRunResponse, status_code=202)
async def create_image_run(
    payload: MediaLabImageRunRequest,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
) -> MediaLabImageRunResponse:
    try:
        run = await service.create(await _to_create_image_command(payload, media_assets))
    except (MediaAssetError, MediaLabImageError, LegacyMediaGraphError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _image_run_response(run, queue_position=service.queue_position(run.backend_run_id))


@router.get("/image-runs", response_model=MediaLabImageRunListResponse)
async def list_image_runs(
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> MediaLabImageRunListResponse:
    runs = await service.list()
    return MediaLabImageRunListResponse(
        items=[
            _image_run_response(run, queue_position=service.queue_position(run.backend_run_id))
            for run in runs
        ],
        total=len(runs),
    )


@router.get("/image-runs/{run_id}", response_model=MediaLabImageRunResponse)
async def get_image_run(
    run_id: str,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> MediaLabImageRunResponse:
    try:
        run = await service.get(run_id)
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _image_run_response(run, queue_position=service.queue_position(run.backend_run_id))


@router.delete("/image-runs/{run_id}", status_code=204, response_class=Response)
async def delete_image_run(
    run_id: str,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> Response:
    try:
        await service.delete(run_id)
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/image-runs/{run_id}/output", response_class=FileResponse)
async def get_image_run_output(
    run_id: str,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> FileResponse:
    try:
        path, media_type = await service.output_file(run_id)
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get("/image-runs/{run_id}/output-master", response_class=FileResponse)
async def get_image_run_master_output(
    run_id: str,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> FileResponse:
    try:
        path, media_type = await service.review_master_file(run_id)
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get("/image-runs/{run_id}/sources/{source_index}", response_class=FileResponse)
async def get_image_run_source(
    run_id: str,
    source_index: int,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> FileResponse:
    try:
        path, media_type = await service.source_file(run_id, source_index)
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get("/image-runs/{run_id}/comparison", response_model=MediaLabImageComparisonResponse)
async def get_image_run_comparison(
    run_id: str,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> MediaLabImageComparisonResponse:
    try:
        lineage = await service.retry_lineage(run_id)
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return MediaLabImageComparisonResponse(
        root_run_id=lineage[0].run_id,
        candidates=[
            _image_run_response(item, queue_position=service.queue_position(item.backend_run_id))
            for item in lineage
        ],
    )


@router.post("/image-runs/{run_id}/review", response_model=MediaLabImageRunResponse)
async def review_image_run(
    run_id: str,
    payload: MediaLabImageReviewRequest,
    service: MediaLabImageService = Depends(get_media_lab_image_service),
) -> MediaLabImageRunResponse:
    try:
        run = await service.review(run_id, ImageReviewState(payload.decision))
    except MediaLabImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _image_run_response(run, queue_position=service.queue_position(run.backend_run_id))


@router.get(
    "/video-orchestration",
    response_model=MediaLabVideoOrchestrationStatusResponse,
)
async def get_video_orchestration_status(
    request: Request,
) -> MediaLabVideoOrchestrationStatusResponse:
    service = getattr(request.app.state, "media_lab_video_orchestration_service", None)
    if not isinstance(service, MediaLabVideoOrchestrationService):
        return MediaLabVideoOrchestrationStatusResponse(
            enabled=False,
            model=None,
            max_image_sources=0,
            max_generation_image_sources=0,
            quality_review_enabled=False,
            max_regenerations=0,
            notice=("Set AIC_MEDIA_LAB_VIDEO_ORCHESTRATOR_CONFIG to enable video orchestration."),
        )
    video_service = getattr(request.app.state, "media_lab_video_service", None)
    quality_review_enabled = (
        video_service.quality_review_enabled()
        if isinstance(video_service, MediaLabVideoService)
        else False
    )
    return MediaLabVideoOrchestrationStatusResponse(
        enabled=True,
        model=service.model(),
        max_image_sources=service.maximum_source_count(),
        max_generation_image_sources=service.maximum_generation_source_count(),
        quality_review_enabled=quality_review_enabled,
        max_regenerations=(video_service.max_regenerations() if quality_review_enabled else 0),
        notice=None,
    )


@router.post("/video-plans", response_model=MediaLabVideoPlanResponse)
async def plan_video_run(
    payload: MediaLabVideoPlanningRequest,
    video_service: MediaLabVideoService = Depends(get_media_lab_video_service),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
    orchestration_service: MediaLabVideoOrchestrationService = Depends(
        get_media_lab_video_orchestration_service
    ),
) -> MediaLabVideoPlanResponse:
    try:
        sources = await _to_video_planning_sources(payload.sources, media_assets)
        plan = await orchestration_service.plan(payload.user_request, sources)
    except (MediaAssetError, MediaLabVideoError, MediaLabVideoOrchestrationError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_plan_response(plan, video_service)


@router.post(
    "/video-plan-jobs",
    response_model=MediaLabVideoPlanningJobResponse,
    status_code=202,
)
async def create_video_planning_job(
    payload: MediaLabVideoPlanningJobRequest,
    video_service: MediaLabVideoService = Depends(get_media_lab_video_service),
    service: MediaLabPlanningJobService = Depends(get_media_lab_planning_job_service),
) -> MediaLabVideoPlanningJobResponse:
    try:
        job = await service.create(
            source_run_id=payload.source_run_id,
            kind=PlanningJobKind.VIDEO,
            user_request=payload.user_request,
            source_asset_ids=tuple(source.asset_id for source in payload.sources),
        )
    except MediaLabPlanningJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_planning_job_response(job, video_service)


@router.get("/video-plan-jobs/{job_id}", response_model=MediaLabVideoPlanningJobResponse)
async def get_video_planning_job(
    job_id: str,
    video_service: MediaLabVideoService = Depends(get_media_lab_video_service),
    service: MediaLabPlanningJobService = Depends(get_media_lab_planning_job_service),
) -> MediaLabVideoPlanningJobResponse:
    try:
        job = await service.get(job_id)
    except MediaLabPlanningJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if job.kind != PlanningJobKind.VIDEO:
        raise HTTPException(status_code=404, detail="Video planning job was not found")
    return _video_planning_job_response(job, video_service)


@router.get("/video-capabilities", response_model=MediaLabVideoCapabilitiesResponse)
async def list_video_capabilities(
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> MediaLabVideoCapabilitiesResponse:
    enabled = service.enabled()
    return MediaLabVideoCapabilitiesResponse(
        enabled=enabled,
        notice=service.notice(),
        items=[
            MediaLabVideoCapabilityResponse(
                capability_id=item.capability_id,
                intent=item.intent,
                label=item.label,
                description=item.description,
                minimum_generation_images=item.minimum_generation_images,
                maximum_generation_images=item.maximum_generation_images,
                supported_duration_seconds=list(item.supported_duration_seconds),
                candidate_count=item.candidate_count,
                output_presets=[
                    MediaLabVideoOutputPresetResponse(
                        preset_id=preset.preset_id,
                        label=preset.label,
                        aspect_ratio=preset.aspect_ratio,
                        megapixels=preset.megapixels,
                    )
                    for preset in item.output_presets
                ],
                supported_output_formats=list(item.supported_output_formats),
                default_output_preset_id=item.default_output_preset_id,
                available=enabled,
            )
            for item in service.capabilities()
        ],
    )


@router.post("/video-runs", response_model=MediaLabVideoRunResponse, status_code=202)
async def create_video_run(
    payload: MediaLabVideoRunRequest,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
) -> MediaLabVideoRunResponse:
    try:
        run = await service.create(await _to_create_video_command(payload, media_assets))
    except (MediaAssetError, LegacyMediaGraphError, MediaLabVideoError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_run_response(run, queue_position=service.queue_position(run.backend_run_id))


@router.get("/video-runs", response_model=MediaLabVideoRunListResponse)
async def list_video_runs(
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> MediaLabVideoRunListResponse:
    runs = await service.list()
    return MediaLabVideoRunListResponse(
        items=[
            _video_run_response(run, queue_position=service.queue_position(run.backend_run_id))
            for run in runs
        ],
        total=len(runs),
    )


@router.get("/video-runs/{run_id}", response_model=MediaLabVideoRunResponse)
async def get_video_run(
    run_id: str,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> MediaLabVideoRunResponse:
    try:
        run = await service.get(run_id)
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_run_response(run, queue_position=service.queue_position(run.backend_run_id))


@router.delete("/video-runs/{run_id}", status_code=204, response_class=Response)
async def delete_video_run(
    run_id: str,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> Response:
    try:
        await service.delete(run_id)
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/video-runs/{run_id}/output", response_class=FileResponse)
async def get_video_run_output(
    run_id: str,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> FileResponse:
    try:
        path, media_type = await service.output_file(run_id)
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get("/video-runs/{run_id}/review-frames/{frame_index}", response_class=FileResponse)
async def get_video_review_frame(
    run_id: str,
    frame_index: int,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> FileResponse:
    try:
        path, media_type = await service.review_frame_file(run_id, frame_index)
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get(
    "/video-runs/{run_id}/sources/{source_index}",
    response_class=FileResponse,
)
async def get_video_source(
    run_id: str,
    source_index: int,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> FileResponse:
    try:
        path, media_type = await service.source_file(run_id, source_index)
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@router.get("/video-runs/{run_id}/comparison", response_model=MediaLabVideoComparisonResponse)
async def get_video_run_comparison(
    run_id: str,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> MediaLabVideoComparisonResponse:
    try:
        lineage = await service.retry_lineage(run_id)
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return MediaLabVideoComparisonResponse(
        root_run_id=lineage[0].run_id,
        candidates=[
            _video_run_response(item, queue_position=service.queue_position(item.backend_run_id))
            for item in lineage
        ],
    )


@router.post("/video-runs/{run_id}/review", response_model=MediaLabVideoRunResponse)
async def review_video_run(
    run_id: str,
    payload: MediaLabVideoReviewRequest,
    service: MediaLabVideoService = Depends(get_media_lab_video_service),
) -> MediaLabVideoRunResponse:
    try:
        run = await service.review(run_id, VideoReviewState(payload.decision))
    except MediaLabVideoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_run_response(run, queue_position=service.queue_position(run.backend_run_id))


@router.post(
    "/video-ads",
    response_model=MediaLabVideoAdResponse,
    status_code=202,
)
async def create_video_ad(
    payload: MediaLabVideoAdRequest,
    service: MediaLabVideoAdService = Depends(get_media_lab_video_ad_service),
) -> MediaLabVideoAdResponse:
    try:
        job = await service.create(
            CreateVideoAdCommand(
                source_run_id=payload.source_run_id,
                brief=VideoAdBrief(
                    user_request=payload.user_request,
                    brand=payload.brand,
                    sku=payload.sku,
                    angle=payload.angle,
                    source_asset_ids=tuple(payload.source_asset_ids),
                    target_duration_seconds=payload.target_duration_seconds,
                    aspect_ratio=payload.aspect_ratio,
                    candidate_count=payload.candidate_count,
                    cta_text=payload.cta_text,
                    logo_asset_id=payload.logo_asset_id,
                ),
            )
        )
    except (MediaLabVideoAdError, MediaAssetError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_ad_response(job)


@router.get("/video-ads", response_model=MediaLabVideoAdListResponse)
async def list_video_ads(
    service: MediaLabVideoAdService = Depends(get_media_lab_video_ad_service),
) -> MediaLabVideoAdListResponse:
    jobs = await service.list()
    return MediaLabVideoAdListResponse(
        items=[_video_ad_response(job) for job in jobs], total=len(jobs)
    )


@router.get("/video-ads/{job_id}", response_model=MediaLabVideoAdResponse)
async def get_video_ad(
    job_id: str,
    service: MediaLabVideoAdService = Depends(get_media_lab_video_ad_service),
) -> MediaLabVideoAdResponse:
    try:
        return _video_ad_response(await service.get(job_id))
    except MediaLabVideoAdError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/video-ads/{job_id}", status_code=204, response_class=Response)
async def delete_video_ad(
    job_id: str,
    service: MediaLabVideoAdService = Depends(get_media_lab_video_ad_service),
) -> Response:
    try:
        await service.delete(job_id)
    except MediaLabVideoAdError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/video-ads/{job_id}/output")
async def get_video_ad_output(
    job_id: str,
    service: MediaLabVideoAdService = Depends(get_media_lab_video_ad_service),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
) -> Response:
    try:
        job = await service.get(job_id)
        if job.output_asset_id is None:
            raise MediaLabVideoAdError(
                "Final Video Ad output is not ready", status_code=409, code="output_not_ready"
            )
        content, content_type = await media_assets.read_original(job.output_asset_id)
    except (MediaLabVideoAdError, MediaAssetError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=content, media_type=content_type)


@router.post("/video-ads/{job_id}/cancel", response_model=MediaLabVideoAdResponse)
async def cancel_video_ad(
    job_id: str,
    service: MediaLabVideoAdService = Depends(get_media_lab_video_ad_service),
) -> MediaLabVideoAdResponse:
    try:
        return _video_ad_response(await service.cancel(job_id))
    except MediaLabVideoAdError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/video-projects",
    response_model=MediaLabVideoProjectResponse,
    status_code=201,
)
async def create_video_project(
    payload: MediaLabVideoProjectRequest,
    service: MediaLabVideoProjectService = Depends(get_media_lab_video_project_service),
) -> MediaLabVideoProjectResponse:
    command = CreateVideoProjectCommand(
        source_run_id=payload.source_run_id,
        shots=tuple(
            VideoProjectShot(
                shot_id=item.shot_id,
                source_run_id=item.source_run_id,
                trim_start_seconds=item.trim_start_seconds,
                trim_end_seconds=item.trim_end_seconds,
            )
            for item in payload.shots
        ),
        target_duration_seconds=payload.target_duration_seconds,
    )
    try:
        project = await service.create(command)
    except MediaLabVideoProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_project_response(project)


@router.get("/video-projects", response_model=MediaLabVideoProjectListResponse)
async def list_video_projects(
    service: MediaLabVideoProjectService = Depends(get_media_lab_video_project_service),
) -> MediaLabVideoProjectListResponse:
    projects = await service.list()
    return MediaLabVideoProjectListResponse(
        items=[_video_project_response(project) for project in projects],
        total=len(projects),
    )


@router.get("/video-projects/{project_id}", response_model=MediaLabVideoProjectResponse)
async def get_video_project(
    project_id: str,
    service: MediaLabVideoProjectService = Depends(get_media_lab_video_project_service),
) -> MediaLabVideoProjectResponse:
    try:
        project = await service.get(project_id)
    except MediaLabVideoProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_project_response(project)


@router.get("/video-projects/{project_id}/output")
async def get_video_project_output(
    project_id: str,
    service: MediaLabVideoProjectService = Depends(get_media_lab_video_project_service),
    media_assets: MediaAssetService = Depends(get_media_asset_service),
) -> Response:
    try:
        project = await service.get(project_id)
        if project.output_asset_id is None:
            raise MediaLabVideoProjectError(
                "Final video output is not ready", status_code=409, code="output_not_ready"
            )
        content, content_type = await media_assets.read_original(project.output_asset_id)
    except (MediaLabVideoProjectError, MediaAssetError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=content, media_type=content_type)


@router.post(
    "/video-projects/{project_id}/review",
    response_model=MediaLabVideoProjectResponse,
)
async def review_video_project(
    project_id: str,
    payload: MediaLabVideoProjectReviewRequest,
    service: MediaLabVideoProjectService = Depends(get_media_lab_video_project_service),
) -> MediaLabVideoProjectResponse:
    try:
        project = await service.review(project_id, VideoProjectState(payload.decision))
    except MediaLabVideoProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _video_project_response(project)


async def _to_image_planning_sources(
    sources: list[MediaLabImageSourceRequest],
    media_assets: MediaAssetService,
) -> tuple[ImagePlanningSource, ...]:
    resolved: list[ImagePlanningSource] = []
    for source_index, source in enumerate(sources):
        asset, binary = await media_assets.image_binary(source.asset_id)
        origin, source_run_id = _image_asset_origin(asset)
        resolved.append(
            ImagePlanningSource(
                source_index=source_index,
                image=binary,
                source_origin=origin,
                source_run_id=source_run_id,
            )
        )
    return tuple(resolved)


async def _to_create_image_command(
    payload: MediaLabImageRunRequest,
    media_assets: MediaAssetService,
) -> CreateImageCommand:
    references: list[ImageReferenceInput] = []
    for item in payload.references:
        asset, binary = await media_assets.image_binary(item.source.asset_id)
        origin, source_run_id = _image_asset_origin(asset)
        references.append(
            ImageReferenceInput(
                role=item.role,
                priority=item.priority,
                must_preserve=tuple(item.must_preserve),
                allowed_changes=tuple(item.allowed_changes),
                source_origin=origin,
                binary=binary,
                source_run_id=source_run_id,
                asset_id=asset.asset_id,
                identity_group=item.identity_group,
            )
        )
    return CreateImageCommand(
        intent=payload.intent,
        prompt=payload.prompt,
        references=tuple(references),
        width=payload.width,
        height=payload.height,
        seed=payload.seed,
        output_preset_id=payload.output_preset_id,
        output_format=payload.output_format,
        orchestration=(
            ImageOrchestrationTrace(
                user_request=payload.orchestration.user_request,
                capability_id=payload.orchestration.capability_id,
                summary=payload.orchestration.summary,
                planner_model=payload.orchestration.planner_model,
                planner_prompt_version=payload.orchestration.planner_prompt_version,
                planner_prompt_hash=payload.orchestration.planner_prompt_hash,
                planner_config_hash=payload.orchestration.planner_config_hash,
                plan_hash=payload.orchestration.plan_hash,
            )
            if payload.orchestration is not None
            else None
        ),
    )


async def _to_video_planning_sources(
    sources: list[MediaLabVideoImageSourceRequest],
    media_assets: MediaAssetService,
) -> tuple[VideoPlanningImageSource, ...]:
    resolved: list[VideoPlanningImageSource] = []
    for source_index, source in enumerate(sources):
        asset, binary = await media_assets.image_binary(source.asset_id)
        origin, source_run_id = _video_asset_origin(asset)
        resolved.append(
            VideoPlanningImageSource(
                source_index=source_index,
                image=binary,
                source_origin=origin,
                source_run_id=source_run_id,
            )
        )
    return tuple(resolved)


async def _to_create_video_command(
    payload: MediaLabVideoRunRequest,
    media_assets: MediaAssetService,
) -> CreateVideoCommand:
    sources: list[VideoImageSourceInput] = []
    for item in payload.sources:
        asset, binary = await media_assets.image_binary(item.source.asset_id)
        origin, source_run_id = _video_asset_origin(asset)
        sources.append(
            VideoImageSourceInput(
                source_index=item.source_index,
                role=item.role,
                usage=item.usage,
                priority=item.priority,
                must_preserve=tuple(item.must_preserve),
                allowed_changes=tuple(item.allowed_changes),
                source_origin=origin,
                binary=binary,
                source_run_id=source_run_id,
                identity_group=item.identity_group,
                is_primary_identity=item.is_primary_identity,
                asset_id=asset.asset_id,
            )
        )
    return CreateVideoCommand(
        intent=payload.intent,
        prompt=payload.prompt,
        sources=tuple(sources),
        verification_plan=tuple(
            VideoVerificationStagePlan(stage=item.stage, reason=item.reason)
            for item in payload.verification_plan
        ),
        duration_seconds=payload.duration_seconds,
        seed=payload.seed,
        output_preset_id=payload.output_preset_id,
        output_format=payload.output_format,
        orchestration=VideoOrchestrationTrace(
            user_request=payload.orchestration.user_request,
            capability_id=payload.orchestration.capability_id,
            summary=payload.orchestration.summary,
            planner_model=payload.orchestration.planner_model,
            planner_prompt_version=payload.orchestration.planner_prompt_version,
            planner_prompt_hash=payload.orchestration.planner_prompt_hash,
            planner_config_hash=payload.orchestration.planner_config_hash,
            plan_hash=payload.orchestration.plan_hash,
        ),
    )


def _image_asset_origin(asset: MediaAsset) -> tuple[ImageSourceOrigin, str | None]:
    if asset.origin == MediaAssetOrigin.UPLOAD:
        return ImageSourceOrigin.UPLOAD, None
    if asset.origin == MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT and asset.source_run_id is not None:
        return ImageSourceOrigin.MEDIA_LAB_OUTPUT, asset.source_run_id
    raise MediaAssetError(
        "This asset cannot be used as an image source in the requested Media Lab flow",
        code="unsupported_image_asset_origin",
    )


def _video_asset_origin(asset: MediaAsset) -> tuple[VideoSourceOrigin, str | None]:
    if asset.origin == MediaAssetOrigin.UPLOAD:
        return VideoSourceOrigin.UPLOAD, None
    if asset.origin == MediaAssetOrigin.MEDIA_LAB_IMAGE_OUTPUT and asset.source_run_id is not None:
        return VideoSourceOrigin.MEDIA_LAB_IMAGE_OUTPUT, asset.source_run_id
    raise MediaAssetError(
        "This asset cannot be used as an image source in the requested video flow",
        code="unsupported_video_asset_origin",
    )


def _video_plan_response(
    plan: VideoOrchestrationPlan,
    service: MediaLabVideoService,
) -> MediaLabVideoPlanResponse:
    return MediaLabVideoPlanResponse(
        state=plan.state.value,
        summary=plan.summary,
        questions=list(plan.questions),
        uncertainties=list(plan.uncertainties),
        capability_id=plan.capability_id,
        intent=(
            service.capability(plan.capability_id).intent
            if plan.capability_id is not None
            else None
        ),
        production_prompt=plan.production_prompt,
        sources=[
            MediaLabVideoPlanSourceResponse(
                source_index=item.source_index,
                role=item.role,
                usage=item.usage,
                priority=item.priority,
                must_preserve=list(item.must_preserve),
                allowed_changes=list(item.allowed_changes),
                identity_group=item.identity_group,
                is_primary_identity=item.is_primary_identity,
            )
            for item in sorted(plan.sources, key=lambda item: item.source_index)
        ],
        verification_plan=[
            MediaLabVideoVerificationStagePlanResponse(stage=item.stage, reason=item.reason)
            for item in plan.verification_plan
        ],
        orchestration=MediaLabVideoOrchestrationTraceResponse(
            user_request=plan.trace.user_request,
            capability_id=plan.trace.capability_id,
            summary=plan.trace.summary,
            planner_model=plan.trace.planner_model,
            planner_prompt_version=plan.trace.planner_prompt_version,
            planner_prompt_hash=plan.trace.planner_prompt_hash,
            planner_config_hash=plan.trace.planner_config_hash,
            plan_hash=plan.trace.plan_hash,
        ),
    )


def _video_verification_response(report):
    if report is None:
        return None
    return MediaLabVideoVerificationResponse(
        status=report.status.value,
        verifier_version=report.verifier_version,
        config_hash=report.config_hash,
        request_hash=report.request_hash,
        stages=[
            MediaLabVideoVerificationStageResponse(
                stage=stage.stage.value,
                status=stage.status.value,
                model=stage.model,
                model_version=stage.model_version,
                observations=[
                    MediaLabVideoVerificationObservationResponse(
                        observation_id=observation.observation_id,
                        stage=observation.stage.value,
                        category=observation.category,
                        status=observation.status.value,
                        severity=observation.severity,
                        description=observation.description,
                        confidence=observation.confidence,
                        start_timestamp_milliseconds=observation.start_timestamp_milliseconds,
                        end_timestamp_milliseconds=observation.end_timestamp_milliseconds,
                        evidence_refs=list(observation.evidence_refs),
                    )
                    for observation in stage.observations
                ],
                metadata=dict(stage.metadata),
            )
            for stage in report.stages
        ],
        suspicious_timestamps_milliseconds=list(report.suspicious_timestamps_milliseconds),
        uncertainties=list(report.uncertainties),
        report_hash=report.report_hash,
    )


def _video_ad_response(job: VideoAdJob) -> MediaLabVideoAdResponse:
    plan = job.plan
    return MediaLabVideoAdResponse(
        job_id=job.job_id,
        source_run_id=job.source_run_id,
        state=job.state,
        user_request=job.brief.user_request,
        brand=job.brief.brand,
        sku=job.brief.sku,
        angle=job.brief.angle,
        target_duration_seconds=job.brief.target_duration_seconds,
        aspect_ratio=job.brief.aspect_ratio,
        candidate_count=job.brief.candidate_count,
        cta_text=job.brief.cta_text,
        summary=plan.summary if plan else None,
        planner_prompt_version=plan.planner_prompt_version if plan else None,
        plan_hash=plan.plan_hash if plan else None,
        questions=list(plan.questions) if plan else [],
        uncertainties=list(plan.uncertainties) if plan else [],
        sources=[
            MediaLabVideoAdSourceResponse(
                source_index=source.source_index,
                role=source.role,
                usage=source.usage,
                priority=source.priority,
                must_preserve=list(source.must_preserve),
                allowed_changes=list(source.allowed_changes),
                identity_group=source.identity_group,
                is_primary_identity=source.is_primary_identity,
            )
            for source in (plan.sources if plan else ())
        ],
        shots=[
            MediaLabVideoAdShotResponse(
                shot_id=shot.shot_id,
                purpose=shot.purpose,
                prompt=shot.prompt,
                intent=shot.intent,
                source_indexes=list(shot.source_indexes),
                generation_duration_seconds=shot.generation_duration_seconds,
                usable_duration_seconds=shot.usable_duration_seconds,
                on_screen_text=shot.on_screen_text,
            )
            for shot in (plan.shots if plan else ())
        ],
        candidates=[MediaLabVideoAdCandidateResponse(**item.__dict__) for item in job.candidates],
        selected_segments=[
            MediaLabVideoAdSegmentResponse(
                shot_id=item.shot_id,
                candidate_index=item.candidate_index,
                run_id=item.run_id,
                trim_start_seconds=item.trim_start_seconds,
                trim_end_seconds=item.trim_end_seconds,
                score=item.score,
                observations=list(item.observations),
            )
            for item in job.selected_segments
        ],
        output_asset_id=job.output_asset_id,
        output_checksum_sha256=job.output_checksum_sha256,
        output_url=(
            f"/api/v1/media-lab/video-ads/{job.job_id}/output"
            if job.output_asset_id is not None
            else None
        ),
        actual_width=job.actual_width,
        actual_height=job.actual_height,
        actual_duration_milliseconds=job.actual_duration_milliseconds,
        error_code=job.error_code,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def _video_project_response(project: VideoProject) -> MediaLabVideoProjectResponse:
    return MediaLabVideoProjectResponse(
        project_id=project.project_id,
        source_run_id=project.source_run_id,
        state=project.state,
        shots=[
            MediaLabVideoProjectShotResponse(
                shot_id=shot.shot_id,
                source_run_id=shot.source_run_id,
                trim_start_seconds=shot.trim_start_seconds,
                trim_end_seconds=shot.trim_end_seconds,
                duration_seconds=shot.duration_seconds,
            )
            for shot in project.shots
        ],
        target_duration_seconds=project.target_duration_seconds,
        source_asset_ids=list(project.source_asset_ids),
        output_asset_id=project.output_asset_id,
        output_checksum_sha256=project.output_checksum_sha256,
        output_url=(
            f"/api/v1/media-lab/video-projects/{project.project_id}/output"
            if project.output_asset_id is not None
            else None
        ),
        actual_width=project.actual_width,
        actual_height=project.actual_height,
        actual_duration_milliseconds=project.actual_duration_milliseconds,
        error_code=project.error_code,
        created_at=project.created_at,
        completed_at=project.completed_at,
        reviewed_at=project.reviewed_at,
    )


def _video_run_response(
    run: VideoRun, *, queue_position: int | None = None
) -> MediaLabVideoRunResponse:
    return MediaLabVideoRunResponse(
        run_id=run.run_id,
        intent=run.intent,
        production_prompt=run.prompt,
        generation_state=run.generation_state,
        review_state=run.review_state,
        quality_review_state=run.quality_review_state,
        quality_review=(
            MediaLabVideoQualityReviewResponse(
                decision=run.quality_review.decision,
                summary=run.quality_review.summary,
                issues=[
                    MediaLabVideoQualityIssueResponse(
                        category=issue.category,
                        severity=issue.severity,
                        description=issue.description,
                    )
                    for issue in run.quality_review.issues
                ],
                repair_instructions=list(run.quality_review.repair_instructions),
                uncertainties=list(run.quality_review.uncertainties),
                reviewer_model=run.quality_review.reviewer_model,
                reviewer_prompt_version=run.quality_review.reviewer_prompt_version,
                reviewer_prompt_hash=run.quality_review.reviewer_prompt_hash,
                reviewer_config_hash=run.quality_review.reviewer_config_hash,
                review_hash=run.quality_review.review_hash,
                sampled_frames=[
                    MediaLabVideoReviewFrameResponse(
                        label=frame.label,
                        timestamp_milliseconds=frame.timestamp_milliseconds,
                        checksum_sha256=frame.checksum_sha256,
                        url=(f"/api/v1/media-lab/video-runs/{run.run_id}/review-frames/{index}"),
                    )
                    for index, frame in enumerate(run.quality_review.sampled_frames, start=1)
                ],
                temporal_sampling_rate_fps=run.quality_review.temporal_sampling_rate_fps,
                temporal_duration_milliseconds=run.quality_review.temporal_duration_milliseconds,
                repair_prompt=run.quality_review.repair_prompt,
                repair_prompt_version=run.quality_review.repair_prompt_version,
                repair_prompt_hash=run.quality_review.repair_prompt_hash,
                verification=_video_verification_response(
                    run.verification or run.quality_review.verification
                ),
            )
            if run.quality_review is not None
            else None
        ),
        quality_review_error_code=run.quality_review_error_code,
        verification_state=run.verification_state,
        verification=_video_verification_response(run.verification),
        verification_frames=[
            MediaLabVideoReviewFrameResponse(
                label=frame.label,
                timestamp_milliseconds=frame.timestamp_milliseconds,
                checksum_sha256=frame.checksum_sha256,
                url=(f"/api/v1/media-lab/video-runs/{run.run_id}/review-frames/{index}"),
            )
            for index, frame in enumerate(
                run.verification_frames
                or (run.quality_review.sampled_frames if run.quality_review is not None else ()),
                start=1,
            )
        ],
        verification_error_code=run.verification_error_code,
        regenerated_run_id=run.regenerated_run_id,
        retry_of_run_id=run.retry_of_run_id,
        regeneration_count=run.regeneration_count,
        model=run.model,
        checkpoint_observation=run.checkpoint_observation,
        graph_template_hash=run.graph_template_hash,
        seed=run.seed,
        sources=[
            MediaLabVideoSourceResponse(
                source_id=item.source_id,
                source_index=item.source_index,
                role=item.role,
                usage=item.usage,
                priority=item.priority,
                must_preserve=list(item.must_preserve),
                allowed_changes=list(item.allowed_changes),
                identity_group=item.identity_group,
                is_primary_identity=item.is_primary_identity,
                source_origin=item.source_origin,
                source_checksum_sha256=item.source_checksum_sha256,
                source_run_id=item.source_run_id,
                asset_id=item.asset_id,
                preview_url=(
                    f"/api/v1/media-assets/{item.asset_id}/preview"
                    if item.asset_id is not None
                    else None
                ),
                url=f"/api/v1/media-lab/video-runs/{run.run_id}/sources/{index}",
            )
            for index, item in enumerate(run.sources, start=1)
        ],
        verification_plan=[
            MediaLabVideoVerificationStagePlanResponse(stage=item.stage, reason=item.reason)
            for item in run.verification_plan
        ],
        duration_seconds=run.output_spec.duration_seconds,
        candidate_count=run.output_spec.candidate_count,
        output_preset_id=run.output_spec.preset_id,
        aspect_ratio=run.output_spec.aspect_ratio,
        megapixels=run.output_spec.megapixels,
        output_format=run.output_spec.output_format,
        actual_width=run.actual_width,
        actual_height=run.actual_height,
        actual_duration_milliseconds=run.actual_duration_milliseconds,
        orchestration=(
            MediaLabVideoOrchestrationTraceResponse(
                user_request=run.orchestration.user_request,
                capability_id=run.orchestration.capability_id,
                summary=run.orchestration.summary,
                planner_model=run.orchestration.planner_model,
                planner_prompt_version=run.orchestration.planner_prompt_version,
                planner_prompt_hash=run.orchestration.planner_prompt_hash,
                planner_config_hash=run.orchestration.planner_config_hash,
                plan_hash=run.orchestration.plan_hash,
            )
            if run.orchestration is not None
            else None
        ),
        provider_job_id=run.provider_job_id,
        queue_position=queue_position,
        queue_wait_milliseconds=run.queue_wait_milliseconds,
        provider_delay_milliseconds=run.provider_delay_milliseconds,
        provider_execution_milliseconds=run.provider_execution_milliseconds,
        output_asset_id=run.output_asset_id,
        output_checksum_sha256=run.output_checksum_sha256,
        output_url=(
            f"/api/v1/media-lab/video-runs/{run.run_id}/output"
            if run.output_ref is not None
            else None
        ),
        retry_memory=_video_retry_memory_response(run.retry_memory),
        error_code=run.error_code,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        reviewed_at=run.reviewed_at,
    )


def _image_plan_response(
    plan: ImageOrchestrationPlan,
    service: MediaLabImageService,
) -> MediaLabImagePlanResponse:
    return MediaLabImagePlanResponse(
        state=plan.state.value,
        summary=plan.summary,
        questions=list(plan.questions),
        uncertainties=list(plan.uncertainties),
        capability_id=plan.capability_id,
        intent=(
            service.capability(plan.capability_id).intent
            if plan.capability_id is not None
            else None
        ),
        production_prompt=plan.production_prompt,
        references=[
            MediaLabImagePlanReferenceResponse(
                source_index=item.source_index,
                role=item.role,
                priority=item.priority,
                must_preserve=list(item.must_preserve),
                allowed_changes=list(item.allowed_changes),
                identity_group=item.identity_group,
            )
            for item in sorted(plan.references, key=lambda item: item.source_index)
        ],
        orchestration=MediaLabImageOrchestrationTraceResponse(
            user_request=plan.trace.user_request,
            capability_id=plan.trace.capability_id,
            summary=plan.trace.summary,
            planner_model=plan.trace.planner_model,
            planner_prompt_version=plan.trace.planner_prompt_version,
            planner_prompt_hash=plan.trace.planner_prompt_hash,
            planner_config_hash=plan.trace.planner_config_hash,
            plan_hash=plan.trace.plan_hash,
        ),
    )


def _image_planning_job_response(
    job: PlanningJob, service: MediaLabImageService
) -> MediaLabImagePlanningJobResponse:
    plan = job.plan
    if plan is not None and not isinstance(plan, ImageOrchestrationPlan):
        raise RuntimeError("Image planning job contains a video plan")
    return MediaLabImagePlanningJobResponse(
        job_id=job.job_id,
        source_run_id=job.source_run_id,
        state=job.state.value,
        source_asset_ids=list(job.source_asset_ids),
        user_request=job.user_request,
        plan=_image_plan_response(plan, service) if plan is not None else None,
        error_code=job.error_code,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _video_planning_job_response(
    job: PlanningJob, service: MediaLabVideoService
) -> MediaLabVideoPlanningJobResponse:
    plan = job.plan
    if plan is not None and not isinstance(plan, VideoOrchestrationPlan):
        raise RuntimeError("Video planning job contains an image plan")
    return MediaLabVideoPlanningJobResponse(
        job_id=job.job_id,
        source_run_id=job.source_run_id,
        state=job.state.value,
        source_asset_ids=list(job.source_asset_ids),
        user_request=job.user_request,
        plan=_video_plan_response(plan, service) if plan is not None else None,
        error_code=job.error_code,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _image_run_response(
    run: ImageRun, *, queue_position: int | None = None
) -> MediaLabImageRunResponse:
    return MediaLabImageRunResponse(
        run_id=run.run_id,
        intent=run.intent,
        production_prompt=run.prompt,
        generation_state=run.generation_state,
        review_state=run.review_state,
        quality_review_state=run.quality_review_state,
        quality_review=(
            MediaLabImageQualityReviewResponse(
                decision=run.quality_review.decision,
                summary=run.quality_review.summary,
                issues=[
                    MediaLabImageQualityIssueResponse(
                        category=issue.category,
                        severity=issue.severity,
                        description=issue.description,
                    )
                    for issue in run.quality_review.issues
                ],
                repair_instructions=list(run.quality_review.repair_instructions),
                uncertainties=list(run.quality_review.uncertainties),
                reviewer_model=run.quality_review.reviewer_model,
                reviewer_prompt_version=run.quality_review.reviewer_prompt_version,
                reviewer_prompt_hash=run.quality_review.reviewer_prompt_hash,
                reviewer_config_hash=run.quality_review.reviewer_config_hash,
                review_hash=run.quality_review.review_hash,
                repair_prompt=run.quality_review.repair_prompt,
                repair_prompt_version=run.quality_review.repair_prompt_version,
                repair_prompt_hash=run.quality_review.repair_prompt_hash,
            )
            if run.quality_review is not None
            else None
        ),
        quality_review_error_code=run.quality_review_error_code,
        regenerated_run_id=run.regenerated_run_id,
        retry_of_run_id=run.retry_of_run_id,
        regeneration_count=run.regeneration_count,
        model=run.model,
        checkpoint_observation=run.checkpoint_observation,
        graph_template_hash=run.graph_template_hash,
        seed=run.seed,
        references=[
            MediaLabImageReferenceResponse(
                reference_id=item.reference_id,
                role=item.role,
                priority=item.priority,
                must_preserve=list(item.must_preserve),
                allowed_changes=list(item.allowed_changes),
                source_origin=item.source_origin,
                source_checksum_sha256=item.source_checksum_sha256,
                source_run_id=item.source_run_id,
                asset_id=item.asset_id,
                identity_group=item.identity_group,
                preview_url=(
                    f"/api/v1/media-assets/{item.asset_id}/preview"
                    if item.asset_id is not None
                    else None
                ),
                url=f"/api/v1/media-lab/image-runs/{run.run_id}/sources/{index}",
            )
            for index, item in enumerate(run.references, start=1)
        ],
        width=run.output_spec.width,
        height=run.output_spec.height,
        candidate_count=run.output_spec.candidate_count,
        output_preset_id=run.output_spec.preset_id,
        aspect_ratio=run.output_spec.aspect_ratio,
        output_format=run.output_spec.delivery_format,
        parent_run_id=run.parent_run_id,
        orchestration=(
            MediaLabImageOrchestrationTraceResponse(
                user_request=run.orchestration.user_request,
                capability_id=run.orchestration.capability_id,
                summary=run.orchestration.summary,
                planner_model=run.orchestration.planner_model,
                planner_prompt_version=run.orchestration.planner_prompt_version,
                planner_prompt_hash=run.orchestration.planner_prompt_hash,
                planner_config_hash=run.orchestration.planner_config_hash,
                plan_hash=run.orchestration.plan_hash,
            )
            if run.orchestration is not None
            else None
        ),
        provider_job_id=run.provider_job_id,
        queue_position=queue_position,
        queue_wait_milliseconds=run.queue_wait_milliseconds,
        provider_delay_milliseconds=run.provider_delay_milliseconds,
        provider_execution_milliseconds=run.provider_execution_milliseconds,
        output_asset_id=run.output_asset_id,
        output_checksum_sha256=run.output_checksum_sha256,
        output_url=(
            f"/api/v1/media-lab/image-runs/{run.run_id}/output"
            if run.output_ref is not None
            else None
        ),
        master_output_url=(
            f"/api/v1/media-lab/image-runs/{run.run_id}/output-master"
            if run.output_ref is not None
            else None
        ),
        retry_memory=_image_retry_memory_response(run.retry_memory),
        error_code=run.error_code,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        reviewed_at=run.reviewed_at,
    )


def _image_retry_memory_response(
    memory: ImageRetryMemory | None,
) -> MediaLabImageRetryMemoryResponse | None:
    if memory is None:
        return None
    return MediaLabImageRetryMemoryResponse(
        root_run_id=memory.root_run_id,
        attempts=[
            MediaLabImageRetryAttemptResponse(
                run_id=item.run_id,
                seed=item.seed,
                production_prompt=item.production_prompt,
                output_asset_id=item.output_asset_id,
                output_checksum_sha256=item.output_checksum_sha256,
                review_decision=item.review_decision,
                review_summary=item.review_summary,
                repair_instructions=list(item.repair_instructions),
                repair_prompt=item.repair_prompt,
            )
            for item in memory.attempts
        ],
    )


def _video_retry_memory_response(
    memory: VideoRetryMemory | None,
) -> MediaLabVideoRetryMemoryResponse | None:
    if memory is None:
        return None
    return MediaLabVideoRetryMemoryResponse(
        root_run_id=memory.root_run_id,
        attempts=[
            MediaLabVideoRetryAttemptResponse(
                run_id=item.run_id,
                seed=item.seed,
                production_prompt=item.production_prompt,
                output_asset_id=item.output_asset_id,
                output_checksum_sha256=item.output_checksum_sha256,
                duration_seconds=item.duration_seconds,
                output_preset_id=item.output_preset_id,
                review_decision=item.review_decision,
                review_summary=item.review_summary,
                repair_instructions=list(item.repair_instructions),
                repair_prompt=item.repair_prompt,
                verifier_status=(
                    item.verifier_status.value if item.verifier_status is not None else None
                ),
                suspicious_timestamps_milliseconds=list(item.suspicious_timestamps_milliseconds),
            )
            for item in memory.attempts
        ],
    )


__all__ = [
    "LegacyMediaGraphCatalog",
    "LegacyMediaGraphError",
    "LegacyMediaGraphInputImage",
    "LegacyMediaGraphInputVideo",
    "LegacyMediaGraphMode",
    "LegacyMediaGraphModeInfo",
    "LegacyMediaGraphRunRequest",
    "LegacyMediaGraphRunResponse",
    "LegacyMediaGraphRunStatus",
    "LegacyMediaGraphService",
    "LegacyMediaGraphSettings",
    "build_legacy_media_graph_service",
    "get_legacy_media_graph_service",
    "router",
]
