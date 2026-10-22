"""Ports for final video-project persistence and deterministic composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain.video_models import VideoRun
from ..domain.video_projects import VideoProject


class MediaLabVideoProjectError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int = 400, code: str = "invalid_video_project"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class VideoCompositionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "video_composition_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VideoCompositionShot:
    shot_id: str
    source_path: Path
    trim_start_seconds: float
    trim_end_seconds: float
    overlay_text: str | None = None


@dataclass(frozen=True)
class VideoCompositionRequest:
    project_id: str
    shots: tuple[VideoCompositionShot, ...]
    target_duration_seconds: float
    width: int
    height: int
    logo_path: Path | None = None
    cta_text: str | None = None


@dataclass(frozen=True)
class VideoCompositionResult:
    output_path: Path
    width: int
    height: int
    duration_milliseconds: int


class IVideoProjectRepository(Protocol):
    async def save(self, project: VideoProject) -> None: ...

    async def get(self, project_id: str) -> VideoProject | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> VideoProject | None: ...

    async def list(self) -> list[VideoProject]: ...

    def close(self) -> None: ...


class IVideoRunSource(Protocol):
    async def get(self, run_id: str) -> VideoRun: ...

    async def output_file(self, run_id: str) -> tuple[Path, str]: ...


class IVideoCompositor(Protocol):
    def compose(self, request: VideoCompositionRequest) -> VideoCompositionResult: ...


__all__ = [
    "IVideoCompositor",
    "IVideoProjectRepository",
    "IVideoRunSource",
    "MediaLabVideoProjectError",
    "VideoCompositionError",
    "VideoCompositionRequest",
    "VideoCompositionResult",
    "VideoCompositionShot",
]
