"""Typed semantic portfolio for one independently orchestrated Creative SKU."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from .contracts import MarketingCreativeAutomationRequest
from .preparation import PreparationContext

if TYPE_CHECKING:
    from .preparation_store import PreparedBrief


@dataclass(frozen=True)
class ApprovedCreativeMemory:
    memory_id: str
    summary: str
    supported_facts: tuple[str, ...]
    non_conclusions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    knowledge_type: str = "lesson"
    authority: str | None = None
    scope: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.memory_id.strip() or not self.summary.strip():
            raise ValueError("Approved Creative memory identity and summary are required")
        if not self.supported_facts or not self.non_conclusions or not self.evidence_refs:
            raise ValueError("Approved Creative memory requires facts, limits and evidence")


class OrchestrationReadiness(StrEnum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"


class HumanPresenceMode(StrEnum):
    PRODUCT_ONLY = "product_only"
    HANDS_ONLY = "hands_only"
    HUMAN_IN_USE = "human_in_use"
    HUMAN_LIFESTYLE = "human_lifestyle"
    ON_CAMERA_PRESENTER = "on_camera_presenter"


class VideoVoiceMode(StrEnum):
    NONE = "none"
    VOICE_OVER = "voice_over"
    ON_CAMERA = "on_camera"


class VideoMusicMode(StrEnum):
    NONE = "none"
    SUBTLE_BACKGROUND = "subtle_background"
    MOOD_DRIVEN = "mood_driven"


class VideoGenerationStrategy(StrEnum):
    ONE_SHOT = "one_shot"
    MULTI_SOURCE = "multi_source"


@dataclass(frozen=True)
class ImageCreativePlan:
    variation_key: str
    visual_direction: str
    evidence_refs: tuple[str, ...]
    scenario: str = ""
    creative_hypothesis: str = ""
    human_presence: HumanPresenceMode = HumanPresenceMode.PRODUCT_ONLY
    product_id: str = ""
    selected_variant_id: str | None = None
    selected_media_ids: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()
    reference_rationale: str = ""

    def __post_init__(self) -> None:
        if not self.variation_key.strip() or not self.visual_direction.strip():
            raise ValueError("Image plan identity and direction are required")
        if not self.evidence_refs:
            raise ValueError("Image plan requires evidence")


@dataclass(frozen=True)
class VideoAudioCreativePlan:
    voice_mode: VideoVoiceMode
    music_mode: VideoMusicMode
    voice_direction: str | None = None
    music_direction: str | None = None
    continuity_direction: str = ""

    def __post_init__(self) -> None:
        if self.voice_mode == VideoVoiceMode.NONE and self.voice_direction is not None:
            raise ValueError("Voice direction requires an enabled voice mode")
        if self.voice_mode != VideoVoiceMode.NONE and not (self.voice_direction or "").strip():
            raise ValueError("Enabled voice mode requires a voice direction")
        if self.music_mode == VideoMusicMode.NONE and self.music_direction is not None:
            raise ValueError("Music direction requires an enabled music mode")
        if self.music_mode != VideoMusicMode.NONE and not (self.music_direction or "").strip():
            raise ValueError("Enabled music mode requires a music direction")

    @property
    def expects_audio(self) -> bool:
        return self.voice_mode != VideoVoiceMode.NONE or self.music_mode != VideoMusicMode.NONE


@dataclass(frozen=True)
class VideoSceneCreativePlan:
    scene_id: str
    purpose: str
    visual_direction: str
    duration_seconds: int
    evidence_refs: tuple[str, ...]
    generation_duration_seconds: int | None = None
    audio_direction: str | None = None
    transition_direction: str = ""
    selected_variant_id: str | None = None
    selected_media_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.scene_id, self.purpose, self.visual_direction)):
            raise ValueError("Video scene identity, purpose and direction are required")
        generation_duration = self.generation_duration_seconds or self.duration_seconds
        if generation_duration < 1 or self.duration_seconds < 1:
            raise ValueError("Video scene durations must be positive")
        if self.duration_seconds > generation_duration:
            raise ValueError("Video scene usable duration cannot exceed generated duration")
        if not self.evidence_refs:
            raise ValueError("Video scene requires evidence")

    @property
    def usable_duration_seconds(self) -> int:
        return self.duration_seconds

    @property
    def resolved_generation_duration_seconds(self) -> int:
        return self.generation_duration_seconds or self.duration_seconds


@dataclass(frozen=True)
class AssembledVideoCreativePlan:
    final_duration_seconds: int
    scenes: tuple[VideoSceneCreativePlan, ...]
    background_music_direction: str | None
    evidence_refs: tuple[str, ...]
    variation_key: str = "video-1"
    scenario: str = ""
    creative_hypothesis: str = ""
    human_presence: HumanPresenceMode = HumanPresenceMode.PRODUCT_ONLY
    generation_strategy: VideoGenerationStrategy = VideoGenerationStrategy.MULTI_SOURCE
    continuity_plan: str = ""
    product_id: str = ""
    audio_plan: VideoAudioCreativePlan = VideoAudioCreativePlan(
        VideoVoiceMode.NONE,
        VideoMusicMode.NONE,
    )
    reference_ids: tuple[str, ...] = ()
    reference_rationale: str = ""

    def __post_init__(self) -> None:
        if self.final_duration_seconds < 1:
            raise ValueError("Final video duration must be positive")
        if not self.scenes:
            raise ValueError("Video plan requires scenes")
        if len({item.scene_id for item in self.scenes}) != len(self.scenes):
            raise ValueError("Video scene IDs must be unique")
        if sum(item.duration_seconds for item in self.scenes) != self.final_duration_seconds:
            raise ValueError("Video scene durations must match the final video duration")
        if self.generation_strategy == VideoGenerationStrategy.ONE_SHOT and len(self.scenes) != 1:
            raise ValueError("One-shot video plans require exactly one scene")
        if (
            self.generation_strategy == VideoGenerationStrategy.MULTI_SOURCE
            and len(self.scenes) < 2
        ):
            raise ValueError("Multi-source video plans require at least two scenes")
        if not self.variation_key.strip() or not self.evidence_refs:
            raise ValueError("Video plan identity and evidence are required")


@dataclass(frozen=True)
class CreativeAutomationPlan:
    plan_id: str
    readiness: OrchestrationReadiness
    strategy_summary: str
    rationale: str
    evidence_refs: tuple[str, ...]
    image_plans: tuple[ImageCreativePlan, ...]
    video_plan: AssembledVideoCreativePlan | None = None
    video_plans: tuple[AssembledVideoCreativePlan, ...] = ()
    missing_context: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    model_profile: str = "unconfigured"
    prompt_version: str = "creative-automation-orchestration@4"
    request_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    schema_version: str = "creative-automation-plan@2"

    @property
    def resolved_video_plans(self) -> tuple[AssembledVideoCreativePlan, ...]:
        if self.video_plans:
            return self.video_plans
        return (self.video_plan,) if self.video_plan is not None else ()

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.plan_id, self.strategy_summary, self.rationale, self.model_profile)
        ):
            raise ValueError("Creative automation plan identity and rationale are required")
        if self.video_plan is not None and self.video_plans:
            raise ValueError("Creative automation plan cannot mix legacy and portfolio video plans")
        video_keys = [item.variation_key for item in self.resolved_video_plans]
        if len(video_keys) != len(set(video_keys)):
            raise ValueError("Creative automation video variation keys must be unique")
        if self.readiness == OrchestrationReadiness.READY and not self.evidence_refs:
            raise ValueError("A ready Creative automation plan requires evidence")
        if self.readiness == OrchestrationReadiness.NEEDS_INPUT and not self.missing_context:
            raise ValueError("A blocked Creative automation plan must name missing context")
        if self.request_count < 0:
            raise ValueError("Orchestration request count cannot be negative")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("Orchestration input tokens cannot be negative")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("Orchestration output tokens cannot be negative")


class ICreativeAutomationOrchestrator(Protocol):
    async def plan(
        self,
        request: MarketingCreativeAutomationRequest,
        context: PreparationContext,
        prepared: PreparedBrief,
        memory: tuple[ApprovedCreativeMemory, ...],
    ) -> CreativeAutomationPlan: ...


__all__ = [
    "ApprovedCreativeMemory",
    "AssembledVideoCreativePlan",
    "CreativeAutomationPlan",
    "HumanPresenceMode",
    "ICreativeAutomationOrchestrator",
    "ImageCreativePlan",
    "OrchestrationReadiness",
    "VideoAudioCreativePlan",
    "VideoGenerationStrategy",
    "VideoMusicMode",
    "VideoSceneCreativePlan",
    "VideoVoiceMode",
]
