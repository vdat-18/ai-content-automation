"""Ports for autonomous final Video Ad planning, persistence and selection."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..domain.models import ImageBinary
from ..domain.video_ads import VideoAdJob, VideoAdTimelinePlan, VideoUsableSegment


class MediaLabVideoAdError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int = 400, code: str = "invalid_video_ad"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class IVideoAdPlanner(Protocol):
    @property
    def model(self) -> str: ...

    async def plan_video_ad(
        self,
        user_request: str,
        *,
        brand: str,
        sku: str,
        angle: str,
        target_duration_seconds: float,
        aspect_ratio: str,
        cta_text: str | None,
        sources: tuple[ImageBinary, ...],
    ) -> VideoAdTimelinePlan: ...


class IVideoAdRepository(Protocol):
    async def save(self, job: VideoAdJob) -> None: ...

    async def get(self, job_id: str) -> VideoAdJob | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> VideoAdJob | None: ...

    async def list(self) -> list[VideoAdJob]: ...

    async def list_active(self) -> list[VideoAdJob]: ...

    async def delete(self, job_id: str) -> bool: ...

    def close(self) -> None: ...


class IVideoCandidateSelector(Protocol):
    def select(
        self,
        shot_id: str,
        candidates: tuple[tuple[int, str, Path], ...],
        usable_duration_seconds: float,
    ) -> VideoUsableSegment: ...


__all__ = [
    "IVideoAdPlanner",
    "IVideoAdRepository",
    "IVideoCandidateSelector",
    "MediaLabVideoAdError",
]
