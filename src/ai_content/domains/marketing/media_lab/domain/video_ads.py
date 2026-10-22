"""Domain contracts for autonomous final marketing video Ads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .video_models import VideoIntent, VideoSourcePlan


class VideoAdJobState(StrEnum):
    PLANNING = "planning"
    NEEDS_INPUT = "needs_input"
    GENERATING_SHOTS = "generating_shots"
    SELECTING_SEGMENTS = "selecting_segments"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class VideoAdBrief:
    user_request: str
    brand: str
    sku: str
    angle: str
    source_asset_ids: tuple[str, ...]
    target_duration_seconds: float = 22.0
    aspect_ratio: str = "9:16"
    candidate_count: int = 1
    cta_text: str | None = None
    logo_asset_id: str | None = None


@dataclass(frozen=True)
class VideoAdShotPlan:
    shot_id: str
    purpose: str
    prompt: str
    intent: VideoIntent
    source_indexes: tuple[int, ...]
    generation_duration_seconds: int
    usable_duration_seconds: float
    on_screen_text: str | None = None


@dataclass(frozen=True)
class VideoAdTimelinePlan:
    summary: str
    questions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    target_duration_seconds: float
    aspect_ratio: str
    sources: tuple[VideoSourcePlan, ...]
    shots: tuple[VideoAdShotPlan, ...]
    planner_model: str
    planner_prompt_version: str
    planner_prompt_hash: str
    planner_config_hash: str
    plan_hash: str


@dataclass(frozen=True)
class VideoAdCandidate:
    shot_id: str
    candidate_index: int
    run_id: str
    seed: int | None


@dataclass(frozen=True)
class VideoUsableSegment:
    shot_id: str
    candidate_index: int
    run_id: str
    trim_start_seconds: float
    trim_end_seconds: float
    score: float
    observations: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreateVideoAdCommand:
    source_run_id: str
    brief: VideoAdBrief


@dataclass(frozen=True)
class VideoAdJob:
    job_id: str
    source_run_id: str
    input_hash: str
    brief: VideoAdBrief
    state: VideoAdJobState
    plan: VideoAdTimelinePlan | None
    candidates: tuple[VideoAdCandidate, ...]
    selected_segments: tuple[VideoUsableSegment, ...]
    output_asset_id: str | None
    output_checksum_sha256: str | None
    actual_width: int | None
    actual_height: int | None
    actual_duration_milliseconds: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


__all__ = [
    "CreateVideoAdCommand",
    "VideoAdBrief",
    "VideoAdCandidate",
    "VideoAdJob",
    "VideoAdJobState",
    "VideoAdShotPlan",
    "VideoAdTimelinePlan",
    "VideoUsableSegment",
]
