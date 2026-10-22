"""Provider-neutral boundary for one short generated video clip."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

VideoMode = Literal["text_to_video", "image_to_video", "video_edit", "video_extend"]


@dataclass(frozen=True)
class VideoGenerationRequest:
    prompt: str
    seconds: int
    size: str
    quality: str | None = None
    mode: VideoMode = "text_to_video"
    input_path: Path | None = None
    seed: int | None = None


@dataclass(frozen=True)
class GeneratedVideo:
    content: bytes
    model: str
    model_revision: str
    runtime_version: str
    service_job_id: str
    prompt: str
    seconds: int
    size: str
    quality: str
    elapsed_seconds: float
    seed: int | None = None
    workflow_hash: str | None = None


class IVideoBackend(Protocol):
    async def generate(self, request: VideoGenerationRequest) -> GeneratedVideo: ...


class VideoGenerationError(Exception):
    """Expected provider or output failure safe to include in run reports."""


__all__ = [
    "GeneratedVideo",
    "IVideoBackend",
    "VideoGenerationError",
    "VideoGenerationRequest",
    "VideoMode",
]
