"""Ports for Media Lab video generation, review, persistence and artifacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..domain.models import ImageBinary
from ..domain.video_models import (
    VideoCapability,
    VideoGenerationState,
    VideoOrchestrationPlan,
    VideoPlanningImageSource,
    VideoQualityReview,
    VideoQualityReviewRequest,
    VideoRun,
    VideoSourceOrigin,
    VideoSourceRole,
    VideoTemporalEvidence,
    VideoVerificationReport,
    VideoVerificationStage,
)


class MediaLabVideoError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int = 400, code: str = "invalid_request"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class MediaLabVideoOrchestrationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str = "orchestration_failed",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class MediaLabVideoQualityReviewError(RuntimeError):
    def __init__(self, message: str, *, code: str = "quality_review_failed") -> None:
        super().__init__(message)
        self.code = code


class PinnedVideoGraph(str):
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"


@dataclass(frozen=True)
class PinnedVideoGeneration:
    graph: str
    prompt: str
    images: tuple[ImageBinary, ...]
    duration_seconds: int
    seed: int | None
    selector_aspect_ratio: str | None = None
    megapixels: float | None = None


@dataclass(frozen=True)
class VideoBackendRun:
    backend_run_id: str
    model: str
    checkpoint_observation: str
    graph_template_hash: str
    seed: int


@dataclass(frozen=True)
class VideoBackendUpdate:
    backend_run_id: str
    state: VideoGenerationState
    provider_job_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    output_path: Path | None
    output_content_type: str | None
    error_code: str | None
    queue_wait_milliseconds: int | None = None
    provider_delay_milliseconds: int | None = None
    provider_execution_milliseconds: int | None = None


VideoBackendObserver = Callable[[VideoBackendUpdate], Awaitable[None]]


class IVideoGenerationBackend(Protocol):
    def video_generation_available(self) -> bool: ...

    def video_generation_notice(self) -> str | None: ...

    def pinned_video_image_input_capacity(self, graph: PinnedVideoGraph) -> int: ...

    def add_video_observer(self, observer: VideoBackendObserver) -> None: ...

    async def submit_pinned_video(self, generation: PinnedVideoGeneration) -> VideoBackendRun: ...


class IVideoOrchestrator(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def max_source_images(self) -> int: ...

    async def plan(
        self,
        user_request: str,
        sources: tuple[VideoPlanningImageSource, ...],
        capabilities: tuple[VideoCapability, ...],
    ) -> VideoOrchestrationPlan: ...


@dataclass(frozen=True)
class VideoVerificationImage:
    source_id: str
    role: VideoSourceRole
    image: ImageBinary
    checksum_sha256: str
    must_preserve: tuple[str, ...]
    artifact_ref: str
    source_origin: VideoSourceOrigin
    identity_group: str | None = None
    is_primary_identity: bool = False


@dataclass(frozen=True)
class VideoEvidenceVerificationRequest:
    run_id: str
    video_path: Path
    video_checksum_sha256: str
    production_prompt: str
    expected_duration_seconds: int
    sources: tuple[VideoVerificationImage, ...]
    selected_stages: tuple[VideoVerificationStage, ...]


class IVideoEvidenceVerifier(Protocol):
    @property
    def verifier_version(self) -> str: ...

    async def verify(
        self, request: VideoEvidenceVerificationRequest
    ) -> VideoVerificationReport: ...


class IVideoQualityReviewer(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def max_regenerations(self) -> int: ...

    async def review(self, request: VideoQualityReviewRequest) -> VideoQualityReview: ...

    async def repair_prompt(
        self,
        request: VideoQualityReviewRequest,
        review: VideoQualityReview,
    ) -> VideoQualityReview: ...


class IVideoFrameSampler(Protocol):
    def sample(self, path: Path) -> VideoTemporalEvidence: ...

    def sample_at(self, path: Path, positions: tuple[float, ...]) -> VideoTemporalEvidence: ...


class IVideoRunRepository(Protocol):
    async def save(self, run: VideoRun) -> None: ...

    async def get(self, run_id: str) -> VideoRun | None: ...

    async def list(self) -> list[VideoRun]: ...

    async def delete(self, run_id: str) -> bool: ...

    async def mark_inflight_interrupted(self) -> int: ...

    def close(self) -> None: ...


class IVideoArtifactStore(Protocol):
    def write_source(
        self,
        run_id: str,
        reference_id: str,
        image: ImageBinary,
    ) -> tuple[str, str]: ...

    def write_output(self, run_id: str, content: bytes) -> tuple[str, str]: ...

    def write_review_frame(
        self,
        run_id: str,
        frame_index: int,
        image: ImageBinary,
    ) -> tuple[str, str]: ...

    def write_manifest(self, run: VideoRun) -> str: ...

    def read(self, artifact_ref: str) -> bytes: ...

    def output_path(self, artifact_ref: str) -> Path: ...


class IImageOutputSource(Protocol):
    async def output_file(self, run_id: str) -> tuple[Path, str]: ...


__all__ = [
    "IImageOutputSource",
    "IVideoArtifactStore",
    "IVideoEvidenceVerifier",
    "IVideoFrameSampler",
    "IVideoGenerationBackend",
    "IVideoOrchestrator",
    "IVideoQualityReviewer",
    "IVideoRunRepository",
    "MediaLabVideoError",
    "MediaLabVideoOrchestrationError",
    "MediaLabVideoQualityReviewError",
    "VideoEvidenceVerificationRequest",
    "VideoVerificationImage",
    "PinnedVideoGeneration",
    "PinnedVideoGraph",
    "VideoBackendObserver",
    "VideoBackendRun",
    "VideoBackendUpdate",
]
