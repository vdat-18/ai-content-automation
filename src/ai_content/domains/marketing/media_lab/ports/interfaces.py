"""Ports for Media Lab image generation, planning, persistence and artifacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..domain.models import (
    ImageBinary,
    ImageCapability,
    ImageGenerationState,
    ImageOrchestrationPlan,
    ImageOutputFormat,
    ImagePlanningSource,
    ImageQualityReview,
    ImageQualityReviewRequest,
    ImageRun,
)


class MediaLabImageError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int = 400, code: str = "invalid_request"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class MediaLabImageOrchestrationError(RuntimeError):
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


class MediaLabImageQualityReviewError(RuntimeError):
    def __init__(self, message: str, *, code: str = "quality_review_failed") -> None:
        super().__init__(message)
        self.code = code


class PinnedImageGraph(str):
    TEXT_TO_IMAGE = "text_to_image"
    PRODUCT_IMAGE_EDIT = "product_image_edit"
    MULTI_REFERENCE = "multi_reference"


@dataclass(frozen=True)
class PinnedImageGeneration:
    graph: str
    prompt: str
    images: tuple[ImageBinary, ...]
    width: int | None
    height: int | None
    seed: int | None


@dataclass(frozen=True)
class ImageBackendRun:
    backend_run_id: str
    model: str
    checkpoint_observation: str
    graph_template_hash: str
    seed: int


@dataclass(frozen=True)
class ImageBackendUpdate:
    backend_run_id: str
    state: ImageGenerationState
    provider_job_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    output_path: Path | None
    output_content_type: str | None
    error_code: str | None
    queue_wait_milliseconds: int | None = None
    provider_delay_milliseconds: int | None = None
    provider_execution_milliseconds: int | None = None


ImageBackendObserver = Callable[[ImageBackendUpdate], Awaitable[None]]


class IImageGenerationBackend(Protocol):
    def image_generation_available(self) -> bool: ...

    def image_generation_notice(self) -> str | None: ...

    def pinned_image_input_capacity(self, graph: PinnedImageGraph) -> int: ...

    def add_image_observer(self, observer: ImageBackendObserver) -> None: ...

    async def submit_pinned_image(self, generation: PinnedImageGeneration) -> ImageBackendRun: ...


class IImageOrchestrator(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def max_images(self) -> int: ...

    async def plan(
        self,
        user_request: str,
        sources: tuple[ImagePlanningSource, ...],
        capabilities: tuple[ImageCapability, ...],
    ) -> ImageOrchestrationPlan: ...


class IImageQualityReviewer(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def max_regenerations(self) -> int: ...

    async def review(self, request: ImageQualityReviewRequest) -> ImageQualityReview: ...

    async def repair_prompt(
        self,
        request: ImageQualityReviewRequest,
        review: ImageQualityReview,
    ) -> ImageQualityReview: ...


class IImageRunRepository(Protocol):
    async def save(self, run: ImageRun) -> None: ...

    async def get(self, run_id: str) -> ImageRun | None: ...

    async def list(self) -> list[ImageRun]: ...

    async def delete(self, run_id: str) -> bool: ...

    async def mark_inflight_interrupted(self) -> int: ...

    def close(self) -> None: ...


class IImageArtifactStore(Protocol):
    def write_source(
        self,
        run_id: str,
        reference_id: str,
        image: ImageBinary,
    ) -> tuple[str, str]: ...

    def write_output(self, run_id: str, content: bytes, extension: str) -> tuple[str, str]: ...

    def write_delivery(
        self,
        run_id: str,
        content: bytes,
        content_type: str,
        output_format: ImageOutputFormat,
    ) -> tuple[str, str, str]: ...

    def write_manifest(self, run: ImageRun) -> str: ...

    def read(self, artifact_ref: str) -> bytes: ...

    def output_path(self, artifact_ref: str) -> Path: ...


__all__ = [
    "IImageArtifactStore",
    "IImageGenerationBackend",
    "IImageOrchestrator",
    "IImageQualityReviewer",
    "IImageRunRepository",
    "ImageBackendObserver",
    "ImageBackendRun",
    "ImageBackendUpdate",
    "MediaLabImageError",
    "MediaLabImageOrchestrationError",
    "MediaLabImageQualityReviewError",
    "PinnedImageGeneration",
    "PinnedImageGraph",
]
