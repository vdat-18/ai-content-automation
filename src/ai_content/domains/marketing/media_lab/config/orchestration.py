"""Typed configuration for the Media Lab Terra image orchestration boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaLabImageOrchestratorPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    text: str = Field(min_length=1)


class MediaLabImageQualityReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: MediaLabImageOrchestratorPrompt
    repair_prompt: MediaLabImageOrchestratorPrompt
    request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_total_image_bytes: int = Field(default=28_000_000, gt=0, le=36_000_000)
    max_regenerations: int = Field(default=2, ge=0, le=2)


class MediaLabImageOrchestratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["baml"]
    model: str = Field(min_length=1)
    base_url: str
    api_key_env: Literal["ROUTER_API_KEY"] | None = None
    prompt: MediaLabImageOrchestratorPrompt
    quality_review: MediaLabImageQualityReviewConfig | None = None
    request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_images: int = Field(default=10, ge=0, le=10)
    max_total_image_bytes: int = Field(default=16_000_000, gt=0, le=24_000_000)
    max_context_bytes: int = Field(default=32_768, gt=0, le=131_072)

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
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
        return self

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_media_lab_image_orchestrator_config(path: Path) -> MediaLabImageOrchestratorConfig:
    raw = _MediaLabImageOrchestratorConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    prompt_path = path.resolve().parent / raw.prompt
    prompt = MediaLabImageOrchestratorPrompt.model_validate_json(
        prompt_path.read_text(encoding="utf-8")
    )
    quality_review = None
    if raw.quality_review is not None:
        quality_root = path.resolve().parent
        quality_review = MediaLabImageQualityReviewConfig(
            **raw.quality_review.model_dump(exclude={"prompt", "repair_prompt"}),
            prompt=MediaLabImageOrchestratorPrompt.model_validate_json(
                (quality_root / raw.quality_review.prompt).read_text(encoding="utf-8")
            ),
            repair_prompt=MediaLabImageOrchestratorPrompt.model_validate_json(
                (quality_root / raw.quality_review.repair_prompt).read_text(encoding="utf-8")
            ),
        )
    return MediaLabImageOrchestratorConfig(
        **raw.model_dump(exclude={"prompt", "quality_review"}),
        prompt=prompt,
        quality_review=quality_review,
    )


class _MediaLabImageQualityReviewConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    prompt: Path
    repair_prompt: Path
    request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_total_image_bytes: int = Field(default=28_000_000, gt=0, le=36_000_000)
    max_regenerations: int = Field(default=2, ge=0, le=2)


class _MediaLabImageOrchestratorConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["baml"]
    model: str = Field(min_length=1)
    base_url: str
    api_key_env: Literal["ROUTER_API_KEY"] | None = None
    prompt: Path
    quality_review: _MediaLabImageQualityReviewConfigFile | None = None
    request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_images: int = Field(default=10, ge=0, le=10)
    max_total_image_bytes: int = Field(default=16_000_000, gt=0, le=24_000_000)
    max_context_bytes: int = Field(default=32_768, gt=0, le=131_072)


__all__ = [
    "MediaLabImageOrchestratorConfig",
    "MediaLabImageOrchestratorPrompt",
    "MediaLabImageQualityReviewConfig",
    "load_media_lab_image_orchestrator_config",
    "MediaLabVideoOrchestratorConfig",
    "MediaLabVideoVerifierConfig",
    "load_media_lab_video_verifier_config",
    "MediaLabVideoOrchestratorPrompt",
    "MediaLabVideoQualityReviewConfig",
    "load_media_lab_video_orchestrator_config",
]


class MediaLabVideoVerifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    base_url: str
    request_timeout_seconds: float = Field(default=900, gt=0, le=900)
    max_video_bytes: int = Field(default=100_000_000, gt=0, le=500_000_000)
    max_source_image_bytes: int = Field(default=24_000_000, gt=0, le=100_000_000)
    max_total_source_image_bytes: int = Field(default=108_000_000, gt=0, le=120_000_000)
    temporal_sampling_rate_fps: int = Field(default=2, ge=1, le=2)
    temporal_max_frame_edge_pixels: int = Field(default=1_280, ge=320, le=2_048)
    temporal_jpeg_quality: int = Field(default=88, ge=60, le=95)
    verifier_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
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
        return self

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _MediaLabVideoVerifierConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    base_url: str
    request_timeout_seconds: float = Field(default=900, gt=0, le=900)
    max_video_bytes: int = Field(default=100_000_000, gt=0, le=500_000_000)
    max_source_image_bytes: int = Field(default=24_000_000, gt=0, le=100_000_000)
    max_total_source_image_bytes: int = Field(default=108_000_000, gt=0, le=120_000_000)
    temporal_sampling_rate_fps: int = Field(default=2, ge=1, le=2)
    temporal_max_frame_edge_pixels: int = Field(default=1_280, ge=320, le=2_048)
    temporal_jpeg_quality: int = Field(default=88, ge=60, le=95)
    verifier_version: str = Field(min_length=1)


def load_media_lab_video_verifier_config(path: Path) -> MediaLabVideoVerifierConfig:
    return MediaLabVideoVerifierConfig.model_validate_json(path.read_text(encoding="utf-8"))


class MediaLabVideoOrchestratorPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    text: str = Field(min_length=1)


class MediaLabVideoQualityReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: MediaLabVideoOrchestratorPrompt
    repair_prompt: MediaLabVideoOrchestratorPrompt
    request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_total_image_bytes: int = Field(default=140_000_000, gt=0, le=160_000_000)
    max_regenerations: int = Field(default=1, ge=0, le=1)


class MediaLabVideoOrchestratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["baml"]
    model: str = Field(min_length=1)
    base_url: str
    api_key_env: Literal["ROUTER_API_KEY"] | None = None
    prompt: MediaLabVideoOrchestratorPrompt
    video_ad_prompt: MediaLabVideoOrchestratorPrompt | None = None
    quality_review: MediaLabVideoQualityReviewConfig | None = None
    request_timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_source_images: int = Field(default=7, ge=0, le=7)
    max_total_image_bytes: int = Field(default=108_000_000, gt=0, le=120_000_000)
    max_context_bytes: int = Field(default=32_768, gt=0, le=131_072)

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
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
        return self

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _MediaLabVideoQualityReviewConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    prompt: Path
    repair_prompt: Path
    request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_total_image_bytes: int = Field(default=140_000_000, gt=0, le=160_000_000)
    max_regenerations: int = Field(default=1, ge=0, le=1)


class _MediaLabVideoOrchestratorConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["baml"]
    model: str = Field(min_length=1)
    base_url: str
    api_key_env: Literal["ROUTER_API_KEY"] | None = None
    prompt: Path
    video_ad_prompt: Path | None = None
    quality_review: _MediaLabVideoQualityReviewConfigFile | None = None
    request_timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_source_images: int = Field(default=7, ge=0, le=7)
    max_total_image_bytes: int = Field(default=108_000_000, gt=0, le=120_000_000)
    max_context_bytes: int = Field(default=32_768, gt=0, le=131_072)


def load_media_lab_video_orchestrator_config(path: Path) -> MediaLabVideoOrchestratorConfig:
    raw = _MediaLabVideoOrchestratorConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    root = path.resolve().parent
    prompt = MediaLabVideoOrchestratorPrompt.model_validate_json(
        (root / raw.prompt).read_text(encoding="utf-8")
    )
    video_ad_prompt = (
        MediaLabVideoOrchestratorPrompt.model_validate_json(
            (root / raw.video_ad_prompt).read_text(encoding="utf-8")
        )
        if raw.video_ad_prompt is not None
        else None
    )
    quality_review = None
    if raw.quality_review is not None:
        quality_review = MediaLabVideoQualityReviewConfig(
            **raw.quality_review.model_dump(exclude={"prompt", "repair_prompt"}),
            prompt=MediaLabVideoOrchestratorPrompt.model_validate_json(
                (root / raw.quality_review.prompt).read_text(encoding="utf-8")
            ),
            repair_prompt=MediaLabVideoOrchestratorPrompt.model_validate_json(
                (root / raw.quality_review.repair_prompt).read_text(encoding="utf-8")
            ),
        )
    return MediaLabVideoOrchestratorConfig(
        **raw.model_dump(exclude={"prompt", "video_ad_prompt", "quality_review"}),
        prompt=prompt,
        video_ad_prompt=video_ad_prompt,
        quality_review=quality_review,
    )
