"""Provider-neutral contracts for paid image and video production."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

MediaKind = Literal["image", "video"]
MediaFidelityMode = Literal["generative", "exact_source_transform"]
VideoVoiceMode = Literal["none", "voice_over", "on_camera"]
VideoMusicMode = Literal["none", "subtle_background", "mood_driven"]


@dataclass(frozen=True)
class PaidMediaGenerationLimits:
    timeout_seconds: int
    max_cost: Decimal
    max_attempts: int = 1
    enforce_cost_limit: bool = False

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("Media generation timeout must be positive")
        if self.max_cost <= 0:
            raise ValueError("Media generation cost limit must be positive")
        if self.max_attempts < 1:
            raise ValueError("Media generation attempts must be positive")


@dataclass(frozen=True)
class ProductMediaSourceRef:
    source_id: str
    product_id: str
    media_id: str
    url: str | None = None
    variant_ids: tuple[str, ...] = ()
    artifact_ref: str | None = None
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.source_id, self.product_id, self.media_id)):
            raise ValueError("Product media source identity is required")
        if self.url is None and self.artifact_ref is None:
            raise ValueError("Product media source URL or frozen artifact is required")
        if (self.artifact_ref is None) != (self.checksum_sha256 is None):
            raise ValueError("Frozen product media requires both artifact reference and checksum")
        if self.checksum_sha256 is not None and len(self.checksum_sha256) != 64:
            raise ValueError("Product media source checksum must be SHA-256")


@dataclass(frozen=True)
class PaidMediaSource:
    asset_ref: str
    checksum_sha256: str
    role: Literal["product", "style", "background", "character", "keyframe", "logo"]
    source_id: str | None = None
    product_id: str | None = None
    media_id: str | None = None
    variant_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.asset_ref.strip():
            raise ValueError("Media source reference is required")
        if len(self.checksum_sha256) != 64:
            raise ValueError("Media source checksum must be SHA-256")


@dataclass(frozen=True)
class PaidImageGenerationRequest:
    request_id: str
    package_id: str
    sku_id: str
    variation_key: str
    visual_direction: str
    width: int
    height: int
    sources: tuple[PaidMediaSource, ...]
    limits: PaidMediaGenerationLimits
    aspect_ratio: str = "1:1"
    provider_id: str | None = None
    model_id: str | None = None
    resolution: str | None = None
    quality: str | None = None
    image_size: str | None = None
    background: str | None = None
    moderation: str | None = None
    output_compression: int | None = None
    input_fidelity: Literal["low", "high"] | None = None
    generation_mode: Literal["single_image_edit", "multi_image_edit"] = "single_image_edit"
    file_format: Literal["png", "jpeg", "webp"] = "png"
    include_text: bool = False
    include_logo: bool = False
    include_watermark: bool = False
    headline: str | None = None
    subtext: str | None = None
    cta_text: str | None = None
    logo_source: PaidMediaSource | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.request_id,
                self.package_id,
                self.sku_id,
                self.variation_key,
                self.visual_direction,
            )
        ):
            raise ValueError("Paid image generation identity and direction are required")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Paid image generation dimensions must be positive")
        if self.provider_id is not None and not self.provider_id.strip():
            raise ValueError("Paid image provider ID cannot be empty")
        if self.model_id is not None and not self.model_id.strip():
            raise ValueError("Paid image model ID cannot be empty")
        if self.resolution is not None and not self.resolution.strip():
            raise ValueError("Paid image resolution cannot be empty")
        if self.include_watermark:
            raise ValueError("Paid image scope excludes watermarks")
        if self.include_text and not any((self.headline, self.subtext, self.cta_text)):
            raise ValueError("Enabled image text requires approved copy")
        if not self.include_text and any((self.headline, self.subtext, self.cta_text)):
            raise ValueError("Approved copy requires image text to be enabled")
        if self.include_logo != (self.logo_source is not None):
            raise ValueError("Image logo selection and logo source must match")
        if not any(source.role == "product" for source in self.sources):
            raise ValueError("Paid image generation requires a product source")


@dataclass(frozen=True)
class PaidVideoGenerationRequest:
    request_id: str
    package_id: str
    sku_id: str
    visual_direction: str
    aspect_ratio: Literal["1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"]
    sources: tuple[PaidMediaSource, ...]
    limits: PaidMediaGenerationLimits
    duration_seconds: int
    model_id: str | None = None
    resolution: str | None = None
    generate_audio: bool | None = None
    usable_duration_seconds: int | None = None
    duration_min_seconds: int = 1
    duration_max_seconds: int = 15
    voice_mode: VideoVoiceMode = "none"
    music_mode: VideoMusicMode = "none"
    voice_direction: str | None = None
    music_direction: str | None = None
    audio_direction: str | None = None
    continuity_direction: str = ""
    continuous_clip: bool = True
    include_text: bool = False
    include_logo: bool = False
    include_postproduction: bool = False

    @property
    def expects_audio(self) -> bool:
        return self.voice_mode != "none" or self.music_mode != "none"

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.request_id,
                self.package_id,
                self.sku_id,
                self.visual_direction,
            )
        ):
            raise ValueError("Paid video generation identity and direction are required")
        if not self.continuous_clip:
            raise ValueError("Each paid video source must be one continuous clip")
        if not self.duration_min_seconds <= self.duration_seconds <= self.duration_max_seconds:
            raise ValueError("Paid video source duration must be within the configured range")
        if self.model_id is not None and not self.model_id.strip():
            raise ValueError("Paid video model ID cannot be empty")
        if self.resolution is not None and not self.resolution.strip():
            raise ValueError("Paid video resolution cannot be empty")
        usable_duration = self.usable_duration_seconds or self.duration_seconds
        if usable_duration < 1 or usable_duration > self.duration_seconds:
            raise ValueError("Paid video usable duration must fit inside the generated source")
        if any((self.include_text, self.include_logo, self.include_postproduction)):
            raise ValueError("Paid video scope excludes text, logo and post-production overlays")
        if self.voice_mode == "none" and self.voice_direction is not None:
            raise ValueError("Voice direction requires an enabled voice mode")
        if self.voice_mode != "none" and not (self.voice_direction or "").strip():
            raise ValueError("Enabled voice mode requires a voice direction")
        if self.music_mode == "none" and self.music_direction is not None:
            raise ValueError("Music direction requires an enabled music mode")
        if self.music_mode != "none" and not (self.music_direction or "").strip():
            raise ValueError("Enabled music mode requires a music direction")
        if not any(source.role in {"product", "keyframe"} for source in self.sources):
            raise ValueError("Paid video generation requires a product or keyframe source")


PaidOneShotVideoGenerationRequest = PaidVideoGenerationRequest


@dataclass(frozen=True)
class PaidAssembledVideoRequest:
    request_id: str
    package_id: str
    sku_id: str
    aspect_ratio: Literal["1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"]
    scene_artifacts: tuple[PaidMediaArtifact, ...]
    final_duration_seconds: int
    expects_audio: bool
    audio_continuity_direction: str
    limits: PaidMediaGenerationLimits
    scene_usable_durations_seconds: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.request_id, self.package_id, self.sku_id)):
            raise ValueError("Assembled video identity is required")
        if self.final_duration_seconds < 1:
            raise ValueError("Assembled video duration must be positive")
        if not self.scene_artifacts:
            raise ValueError("Assembled video requires at least one source artifact")
        if any(scene.content_type != "video/mp4" for scene in self.scene_artifacts):
            raise ValueError("Assembled video sources must be MP4 artifacts")
        if any(scene.duration_seconds is None for scene in self.scene_artifacts):
            raise ValueError("Assembled video sources must declare their duration")
        usable_durations = self.scene_usable_durations_seconds or tuple(
            scene.duration_seconds or 0 for scene in self.scene_artifacts
        )
        if len(usable_durations) != len(self.scene_artifacts):
            raise ValueError("Every assembled scene requires a usable duration")
        if any(
            usable < 1 or usable > (scene.duration_seconds or 0)
            for usable, scene in zip(usable_durations, self.scene_artifacts, strict=True)
        ):
            raise ValueError("Assembled scene trims must fit inside generated sources")
        if sum(usable_durations) != self.final_duration_seconds:
            raise ValueError("Assembled video usable durations must match the final duration")


@dataclass(frozen=True)
class PaidMediaArtifact:
    artifact_ref: str
    checksum_sha256: str
    content_type: str
    provider_id: str
    provider_job_id: str
    model: str
    model_revision: str | None
    elapsed_seconds: float
    cost: Decimal
    width: int
    height: int
    duration_seconds: int | None = None
    has_audio_stream: bool | None = None
    connection_id: str | None = None
    configuration_version: str | None = None
    requested_model: str | None = None
    fidelity_mode: MediaFidelityMode = "generative"
    product_source_checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.artifact_ref,
                self.content_type,
                self.provider_id,
                self.provider_job_id,
                self.model,
            )
        ):
            raise ValueError("Paid media artifact identity is required")
        if len(self.checksum_sha256) != 64:
            raise ValueError("Paid media artifact checksum must be SHA-256")
        if (
            self.product_source_checksum_sha256 is not None
            and len(self.product_source_checksum_sha256) != 64
        ):
            raise ValueError("Paid media product source checksum must be SHA-256")
        if self.elapsed_seconds < 0 or self.cost < 0:
            raise ValueError("Paid media elapsed time and cost cannot be negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Paid media dimensions must be positive")


@dataclass(frozen=True)
class PaidMediaQualityIssue:
    code: str
    detail: str
    severity: Literal["minor", "major", "critical"]
    repair_instruction: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.detail.strip():
            raise ValueError("Paid media quality issue code and detail are required")


@dataclass(frozen=True)
class PaidMediaQualityEvaluation:
    outcome: Literal["pass", "revise", "human_review"]
    summary: str
    issues: tuple[PaidMediaQualityIssue, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("Paid media quality evaluation summary is required")
        if self.outcome == "pass" and self.issues:
            raise ValueError("Passing paid media cannot contain quality issues")
        if self.outcome == "revise" and not any(issue.repair_instruction for issue in self.issues):
            raise ValueError("Revision requires at least one repair instruction")


@dataclass(frozen=True)
class PaidVideoModelDescriptor:
    model_id: str
    display_name: str
    supported_aspect_ratios: tuple[str, ...]
    supported_resolutions: tuple[str, ...]
    supported_generation_durations_seconds: tuple[int, ...]
    max_reference_images: int = 1
    max_product_images: int = 1
    reference_to_video_resolutions: tuple[str, ...] = ()
    supports_native_voice: bool = False
    supports_native_music: bool = False
    fidelity_mode: MediaFidelityMode = "generative"

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.display_name.strip():
            raise ValueError("Video model identity is required")
        if not self.supported_aspect_ratios or not self.supported_resolutions:
            raise ValueError("Video model must declare ratios and resolutions")
        if not self.supported_generation_durations_seconds:
            raise ValueError("Video model must declare durations")
        if self.max_product_images < 1 or self.max_product_images > self.max_reference_images:
            raise ValueError("Video product image limit must fit within the total image limit")
        if not set(self.reference_to_video_resolutions).issubset(self.supported_resolutions):
            raise ValueError("Reference-to-video resolutions must be supported by the model")


@dataclass(frozen=True)
class PaidImageModelDescriptor:
    model_id: str
    display_name: str
    supported_modes: tuple[str, ...]
    supported_aspect_ratios: tuple[str, ...]
    supported_resolutions: tuple[str, ...]
    supported_qualities: tuple[str, ...]
    supported_formats: tuple[str, ...]
    supported_image_sizes: tuple[str, ...] = ()
    supported_backgrounds: tuple[str, ...] = ()
    supported_moderation: tuple[str, ...] = ()
    supported_input_fidelities: tuple[str, ...] = ()
    supports_output_compression: bool = False
    max_reference_images: int = 1
    supports_text_rendering: bool = False
    supports_logo_input: bool = False
    cost_per_output_by_setting: tuple[tuple[str, Decimal], ...] = ()
    input_image_cost: Decimal = Decimal("0")
    fidelity_mode: MediaFidelityMode = "generative"

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.display_name.strip():
            raise ValueError("Image model identity is required")
        if not self.supported_modes or not self.supported_aspect_ratios:
            raise ValueError("Image model must declare modes and ratios")
        if not self.supported_resolutions or not self.supported_formats:
            raise ValueError("Image model must declare resolutions and formats")
        if self.max_reference_images < 1 or self.input_image_cost < 0:
            raise ValueError("Image model source limits and costs are invalid")


@dataclass(frozen=True)
class PaidMediaProviderDescriptor:
    provider_id: str
    media_kind: MediaKind
    approved: bool
    configuration_version: str
    supported_aspect_ratios: tuple[str, ...] = ("1:1", "4:5", "9:16", "16:9")
    duration_min_seconds: int | None = None
    duration_max_seconds: int | None = None
    supports_native_voice: bool = False
    supports_native_music: bool = False
    supported_image_formats: tuple[str, ...] = ("png", "jpeg", "webp")
    max_reference_images: int = 1
    supported_generation_durations_seconds: tuple[int, ...] = tuple(range(1, 16))
    video_models: tuple[PaidVideoModelDescriptor, ...] = ()
    image_models: tuple[PaidImageModelDescriptor, ...] = ()
    fidelity_mode: MediaFidelityMode = "generative"
    selected_sku_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.configuration_version.strip():
            raise ValueError("Provider identity and configuration version are required")
        if not self.supported_aspect_ratios:
            raise ValueError("Provider must declare at least one supported aspect ratio")
        if self.media_kind == "image" and not self.supported_image_formats:
            raise ValueError("Image provider must declare supported output formats")
        if self.max_reference_images < 1:
            raise ValueError("Media provider must support at least one product reference")
        if self.media_kind == "video" and not self.supported_generation_durations_seconds:
            raise ValueError("Video provider must declare supported generation durations")
        if (self.duration_min_seconds is None) != (self.duration_max_seconds is None):
            raise ValueError("Provider duration capability must include both bounds")
        if (
            self.duration_min_seconds is not None
            and self.duration_max_seconds is not None
            and self.duration_max_seconds < self.duration_min_seconds
        ):
            raise ValueError("Provider duration capability is invalid")


class IPaidMediaSourceResolver(Protocol):
    async def resolve_product_sources(
        self,
        *,
        request_id: str,
        sku_id: str,
        source_refs: tuple[ProductMediaSourceRef, ...],
    ) -> tuple[PaidMediaSource, ...]: ...


class IFrozenProductMediaResolver(IPaidMediaSourceResolver, Protocol):
    def read_frozen_source(self, artifact_ref: str, max_bytes: int | None = None) -> bytes:
        """Read a bounded planning preview of one frozen source artifact.

        Exact frozen bytes for paid generation are resolved through
        ``resolve_product_sources`` instead.
        """

    async def resolve_brand_asset(
        self,
        *,
        artifact_ref: str,
        checksum_sha256: str,
    ) -> PaidMediaSource: ...

    async def resolve_reference_asset(
        self,
        *,
        reference_id: str,
        artifact_ref: str,
        checksum_sha256: str,
    ) -> PaidMediaSource: ...


class IManagedImageGenerationProvider(Protocol):
    descriptor: PaidMediaProviderDescriptor

    async def generate(self, request: PaidImageGenerationRequest) -> PaidMediaArtifact: ...


class IManagedVideoGenerationProvider(Protocol):
    descriptor: PaidMediaProviderDescriptor

    async def generate(self, request: PaidVideoGenerationRequest) -> PaidMediaArtifact: ...

    async def assemble(self, request: PaidAssembledVideoRequest) -> PaidMediaArtifact:
        """Join source clips in order while preserving their native audio."""
        ...


class IPaidImageQualityEvaluator(Protocol):
    async def evaluate_image(
        self,
        request: PaidImageGenerationRequest,
        artifact: PaidMediaArtifact,
    ) -> PaidMediaQualityEvaluation:
        """Compare a generated image with the request's frozen product source."""
        ...


class PaidMediaProviderUnavailableError(Exception):
    """No explicitly approved provider is configured for the requested media kind."""


__all__ = [
    "IFrozenProductMediaResolver",
    "IManagedImageGenerationProvider",
    "IManagedVideoGenerationProvider",
    "IPaidImageQualityEvaluator",
    "IPaidMediaSourceResolver",
    "MediaFidelityMode",
    "MediaKind",
    "PaidAssembledVideoRequest",
    "PaidImageGenerationRequest",
    "PaidImageModelDescriptor",
    "PaidMediaArtifact",
    "PaidMediaGenerationLimits",
    "PaidMediaProviderDescriptor",
    "PaidMediaQualityEvaluation",
    "PaidMediaQualityIssue",
    "PaidMediaProviderUnavailableError",
    "PaidMediaSource",
    "ProductMediaSourceRef",
    "PaidOneShotVideoGenerationRequest",
    "PaidVideoGenerationRequest",
    "VideoMusicMode",
    "VideoVoiceMode",
]
