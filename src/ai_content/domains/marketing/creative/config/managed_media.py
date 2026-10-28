"""Typed configuration for approved managed Creative media production."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

AspectRatio = Literal["1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"]


class ManagedImageModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    display_name: str | None = Field(default=None, min_length=1)
    supported_aspect_ratios: tuple[AspectRatio, ...] = ("1:1", "4:5", "9:16", "16:9")
    supported_formats: tuple[Literal["png", "jpeg", "webp"], ...] = ("png",)
    supported_image_sizes: tuple[str, ...] = ()
    supported_resolutions: tuple[Literal["1k", "1.5k", "2k"], ...] = ("1k",)
    supported_qualities: tuple[Literal["auto", "low", "medium", "high", "xhigh", "max"], ...] = ()
    supported_backgrounds: tuple[Literal["auto", "opaque", "transparent"], ...] = ()
    supported_moderation: tuple[Literal["auto", "low"], ...] = ()
    supported_input_fidelities: tuple[Literal["low", "high"], ...] = ()
    supports_output_compression: bool = False
    supported_modes: tuple[Literal["single_image_edit", "multi_image_edit"], ...] = (
        "single_image_edit",
    )
    max_reference_images: int = Field(default=1, ge=1)
    supports_text_rendering: bool = True
    supports_logo_input: bool = True
    reference_field: Literal["image", "images"] = "image"
    request_mode: Literal["json_generation", "json_edit", "multipart_edit"] = "json_generation"
    # Gemini through 9Router reads plain data-URL strings instead of {"image_url": ...} entries.
    reference_encoding: Literal["image_url_entry", "data_url"] = "image_url_entry"
    # Quality used when a request names none; some providers default to their lowest tier.
    default_quality: Literal["auto", "low", "medium", "high", "xhigh", "max"] | None = None
    # Send the resolution tier to the provider instead of only using it for pricing.
    send_resolution: bool = False
    cost_per_output: Decimal | None = Field(default=None, gt=0)
    cost_per_output_by_setting: dict[str, Decimal] = Field(default_factory=dict)
    input_image_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_sizes(self) -> Self:
        for value in self.supported_image_sizes:
            width, separator, height = value.lower().partition("x")
            if (
                not separator
                or not width.isdigit()
                or not height.isdigit()
                or int(width) <= 0
                or int(height) <= 0
            ):
                raise ValueError("Supported image sizes must be positive WIDTHxHEIGHT strings")
        if len(set(self.supported_image_sizes)) != len(self.supported_image_sizes):
            raise ValueError("Supported image sizes must be unique")
        if not self.supported_resolutions:
            raise ValueError("Image model must declare at least one resolution")
        if len(set(self.supported_resolutions)) != len(self.supported_resolutions):
            raise ValueError("Image resolutions must be unique")
        if len(set(self.supported_qualities)) != len(self.supported_qualities):
            raise ValueError("Image qualities must be unique")
        if (
            self.default_quality is not None
            and self.default_quality not in self.supported_qualities
        ):
            raise ValueError("Default image quality must be a supported quality")
        if len(set(self.supported_input_fidelities)) != len(self.supported_input_fidelities):
            raise ValueError("Image input fidelities must be unique")
        if not self.supported_modes or len(set(self.supported_modes)) != len(self.supported_modes):
            raise ValueError("Image modes must be non-empty and unique")
        valid_settings = {
            f"{quality}:{resolution}"
            for quality in self.supported_qualities
            for resolution in self.supported_resolutions
        }
        if not set(self.cost_per_output_by_setting).issubset(valid_settings):
            raise ValueError("Image cost rates must use declared quality and resolution")
        if any(value <= 0 for value in self.cost_per_output_by_setting.values()):
            raise ValueError("Image cost rates must be positive")
        return self

    def cost_rate(self, resolution: str, quality: str | None) -> Decimal:
        if quality is not None:
            rate = self.cost_per_output_by_setting.get(f"{quality}:{resolution}")
            if rate is not None:
                return rate
        if self.cost_per_output is not None:
            return self.cost_per_output
        raise ValueError(f"Image model has no cost rate for {quality or 'default'}:{resolution}")


class ManagedVideoModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    display_name: str | None = Field(default=None, min_length=1)
    supported_aspect_ratios: tuple[AspectRatio, ...] = ("1:1", "9:16", "16:9")
    supported_generation_durations_seconds: tuple[int, ...] = (5, 10, 15)
    max_reference_images: int = Field(default=1, ge=1)
    max_product_images: int = Field(default=1, ge=1)
    reference_to_video_resolutions: tuple[Literal["480p", "720p"], ...] = ()
    resolution: str = Field(default="720p", min_length=1)
    supported_resolutions: tuple[str, ...] = ()
    supports_native_voice: bool = True
    supports_native_music: bool = True
    cost_per_generated_second: Decimal | None = Field(default=None, gt=0)
    cost_per_generated_second_by_resolution: dict[str, Decimal] = Field(default_factory=dict)
    input_image_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @property
    def resolved_resolutions(self) -> tuple[str, ...]:
        return self.supported_resolutions or (self.resolution,)

    def cost_rate(self, resolution: str) -> Decimal:
        if resolution in self.cost_per_generated_second_by_resolution:
            return self.cost_per_generated_second_by_resolution[resolution]
        if self.cost_per_generated_second is not None:
            return self.cost_per_generated_second
        raise ValueError(f"Video model has no cost rate for {resolution}")

    @model_validator(mode="after")
    def validate_durations(self) -> Self:
        if not self.supported_generation_durations_seconds:
            raise ValueError("Video model must declare generation durations")
        if any(value <= 0 for value in self.supported_generation_durations_seconds):
            raise ValueError("Video generation durations must be positive")
        if len(set(self.supported_generation_durations_seconds)) != len(
            self.supported_generation_durations_seconds
        ):
            raise ValueError("Video generation durations must be unique")
        if not self.resolved_resolutions:
            raise ValueError("Video model must declare at least one resolution")
        if len(set(self.resolved_resolutions)) != len(self.resolved_resolutions):
            raise ValueError("Video resolutions must be unique")
        if any(value not in {"480p", "720p", "1080p"} for value in self.resolved_resolutions):
            raise ValueError("Unsupported managed video resolution")
        if any(value <= 0 for value in self.cost_per_generated_second_by_resolution.values()):
            raise ValueError("Video cost rates must be positive")
        if self.max_product_images > self.max_reference_images:
            raise ValueError("Video product image limit cannot exceed the total image limit")
        if not set(self.reference_to_video_resolutions).issubset(self.resolved_resolutions):
            raise ValueError("Reference-to-video resolutions must be supported by the model")
        if self.reference_to_video_resolutions and self.max_reference_images < 2:
            raise ValueError("Reference-to-video models must accept at least two images")
        if self.cost_per_generated_second is None and set(
            self.cost_per_generated_second_by_resolution
        ) != set(self.resolved_resolutions):
            raise ValueError("Every video resolution requires an explicit cost rate")
        return self


class ManagedMediaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str = Field(min_length=1)
    backend: Literal["nine_router", "direct_api"] = "nine_router"
    approved: bool = False
    configuration_version: str = Field(min_length=1)
    base_url: str
    api_key_env: str = "ROUTER_API_KEY"
    image_base_url: str | None = None
    image_api_key_env: str | None = None
    video_base_url: str | None = None
    video_api_key_env: str | None = None
    allow_insecure_http: bool = False
    selected_sku_enabled: bool = False
    image: ManagedImageModelConfig | None = None
    image_models: tuple[ManagedImageModelConfig, ...] = ()
    video: ManagedVideoModelConfig | None = None
    video_models: tuple[ManagedVideoModelConfig, ...] = ()
    request_timeout_seconds: float = Field(default=120, gt=0)
    generation_timeout_seconds: int = Field(default=900, gt=0)
    poll_interval_seconds: float = Field(default=5, gt=0)
    max_source_bytes: int | None = Field(default=None, gt=0)
    max_image_output_bytes: int | None = Field(default=None, gt=0)
    max_video_output_bytes: int | None = Field(default=None, gt=0)
    allowed_source_hosts: tuple[str, ...] = ()
    allowed_output_hosts: tuple[str, ...] = ()
    max_concurrency: int = Field(default=10, ge=1)
    # Vision model that compares each generated image with the frozen product packshot.
    fidelity_check_model: str | None = None
    max_image_attempts: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        for base_url in {self.base_url, self.resolved_image_base_url, self.resolved_video_base_url}:
            parsed = urlsplit(base_url)
            loopback_http = parsed.scheme == "http" and parsed.hostname in {
                "127.0.0.1",
                "localhost",
                "::1",
            }
            explicitly_allowed_http = parsed.scheme == "http" and self.allow_insecure_http
            if (
                (parsed.scheme != "https" and not loopback_http and not explicitly_allowed_http)
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Managed media base URLs must be credential-free HTTPS, loopback HTTP, "
                    "or explicitly allow insecure HTTP"
                )
        for api_key_env in {
            self.api_key_env,
            self.resolved_image_api_key_env,
            self.resolved_video_api_key_env,
        }:
            if not api_key_env.isidentifier():
                raise ValueError("Managed media API key names must be environment variables")
        if (
            self.image is None
            and not self.image_models
            and self.video is None
            and not self.video_models
        ):
            raise ValueError("Managed media profile must configure image or video")
        resolved_image_models = self.resolved_image_models
        if len({item.model for item in resolved_image_models}) != len(resolved_image_models):
            raise ValueError("Managed image model IDs must be unique")
        resolved_video_models = self.video_models or (
            (self.video,) if self.video is not None else ()
        )
        if len({item.model for item in resolved_video_models}) != len(resolved_video_models):
            raise ValueError("Managed video model IDs must be unique")
        if self.approved and any(
            item.cost_per_output is None and not item.cost_per_output_by_setting
            for item in resolved_image_models
        ):
            raise ValueError("Approved managed image media requires an explicit positive cost rate")
        if self.approved and (not self.allowed_source_hosts or not self.allowed_output_hosts):
            raise ValueError(
                "Approved managed media requires non-empty source and output host allowlists"
            )
        for host in (*self.allowed_source_hosts, *self.allowed_output_hosts):
            if not host.strip() or ":" in host or "/" in host:
                raise ValueError("Allowed media hosts must be bare hostnames")
        return self

    @property
    def resolved_image_base_url(self) -> str:
        return self.image_base_url or self.base_url

    @property
    def resolved_video_base_url(self) -> str:
        return self.video_base_url or self.base_url

    @property
    def resolved_image_api_key_env(self) -> str:
        return self.image_api_key_env or self.api_key_env

    @property
    def resolved_video_api_key_env(self) -> str:
        return self.video_api_key_env or self.api_key_env

    @property
    def resolved_video_models(self) -> tuple[ManagedVideoModelConfig, ...]:
        if self.video_models:
            return self.video_models
        return (self.video,) if self.video is not None else ()

    @property
    def resolved_image_models(self) -> tuple[ManagedImageModelConfig, ...]:
        if self.image_models:
            return self.image_models
        return (self.image,) if self.image is not None else ()


def load_managed_media_config(path: Path) -> ManagedMediaConfig:
    return ManagedMediaConfig.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = [
    "ManagedImageModelConfig",
    "ManagedMediaConfig",
    "ManagedVideoModelConfig",
    "load_managed_media_config",
]
