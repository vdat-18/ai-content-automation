"""Typed configuration for asynchronous video generation services."""

from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VideoBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    backend: Literal["openai_compatible", "comfyui"]
    model: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    base_url: str
    api_key_env: str | None = None
    workflow_path: Path | None = None
    megapixels: float | None = Field(default=None, gt=0, le=2)
    prompt_enhance: bool = False
    request_timeout_seconds: float = Field(default=30, gt=0)
    generation_timeout_seconds: float = Field(default=900, gt=0)
    poll_interval_seconds: float = Field(default=5, gt=0)
    max_video_bytes: int = Field(default=200_000_000, gt=0)
    supported_seconds: tuple[int, ...] = Field(default=(4, 6, 8), min_length=1)
    supported_sizes: tuple[str, ...] = Field(default=("1280x720", "720x1280"), min_length=1)
    default_quality: str = Field(default="standard", min_length=1)

    @model_validator(mode="after")
    def validate_service(self) -> Self:
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url must be an HTTP endpoint without credentials or query")
        if self.api_key_env is not None and not self.api_key_env.isidentifier():
            raise ValueError("api_key_env must be an environment variable name")
        if any(seconds <= 0 for seconds in self.supported_seconds):
            raise ValueError("supported_seconds values must be positive")
        if len(set(self.supported_seconds)) != len(self.supported_seconds):
            raise ValueError("supported_seconds values must be unique")
        if len(set(self.supported_sizes)) != len(self.supported_sizes):
            raise ValueError("supported_sizes values must be unique")
        for size in self.supported_sizes:
            width, separator, height = size.partition("x")
            if separator != "x" or not width.isdigit() or not height.isdigit():
                raise ValueError("supported_sizes values must use WIDTHxHEIGHT")
        if self.backend == "comfyui":
            if self.workflow_path is None or self.megapixels is None:
                raise ValueError("ComfyUI needs workflow_path and megapixels")
            if url.path not in {"", "/"}:
                raise ValueError("ComfyUI base_url must be an HTTP origin")
            if self.api_key_env is not None:
                raise ValueError("ComfyUI backend does not support API credentials")
        return self


def load_video_config(path: Path) -> VideoBackendConfig:
    config = VideoBackendConfig.model_validate_json(path.read_text(encoding="utf-8"))
    if config.workflow_path is not None:
        config = config.model_copy(
            update={"workflow_path": (path.resolve().parent / config.workflow_path).resolve()}
        )
    return config


__all__ = ["VideoBackendConfig", "load_video_config"]
