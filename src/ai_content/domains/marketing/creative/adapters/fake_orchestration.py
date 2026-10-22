"""Deterministic test adapter for selected-SKU Creative orchestration."""

from __future__ import annotations

from ai_content.domains.marketing.creative.config.orchestration import OrchestrationConfig
from ai_content.domains.marketing.creative.ports.orchestration import (
    AssembledVideoCreativePlan,
    CreativeAutomationPlan,
    HumanPresenceMode,
    ImageCreativePlan,
    OrchestrationReadiness,
    VideoAudioCreativePlan,
    VideoGenerationStrategy,
    VideoMusicMode,
    VideoSceneCreativePlan,
    VideoVoiceMode,
)

_IMAGE_SCENARIOS = (
    ("Product hero", HumanPresenceMode.PRODUCT_ONLY),
    ("Lifestyle use", HumanPresenceMode.HUMAN_IN_USE),
    ("Product detail", HumanPresenceMode.HANDS_ONLY),
    ("Everyday setting", HumanPresenceMode.HUMAN_LIFESTYLE),
)
_VIDEO_SCENARIOS = (
    (
        "Product showcase",
        HumanPresenceMode.PRODUCT_ONLY,
        VideoVoiceMode.NONE,
        VideoMusicMode.SUBTLE_BACKGROUND,
    ),
    (
        "Problem to solution",
        HumanPresenceMode.HUMAN_IN_USE,
        VideoVoiceMode.VOICE_OVER,
        VideoMusicMode.SUBTLE_BACKGROUND,
    ),
    (
        "On-camera demonstration",
        HumanPresenceMode.ON_CAMERA_PRESENTER,
        VideoVoiceMode.ON_CAMERA,
        VideoMusicMode.SUBTLE_BACKGROUND,
    ),
    (
        "Lifestyle mood",
        HumanPresenceMode.HUMAN_LIFESTYLE,
        VideoVoiceMode.NONE,
        VideoMusicMode.MOOD_DRIVEN,
    ),
)


class FakeCreativeAutomationOrchestrator:
    def __init__(self, config: OrchestrationConfig) -> None:
        self._config = config

    async def plan(self, request, context, prepared, memory) -> CreativeAutomationPlan:
        evidence = tuple(item.source_id for item in context.package.evidence)
        family = context.sku.product_family
        image_plans = tuple(
            ImageCreativePlan(
                variation_key=f"image-{index + 1}",
                scenario=scenario,
                creative_hypothesis=f"Test whether {scenario.lower()} makes the product useful.",
                human_presence=presence,
                visual_direction=(
                    f"{prepared.brief.visual_direction} Use a distinct {scenario.lower()} treatment. "
                    "No text, captions, logos, or watermarks."
                ),
                product_id=family.ref.product_id if family is not None else "",
                selected_variant_id=_selection(family, request.selected_variant_id, index)[0],
                selected_media_ids=_selection(family, request.selected_variant_id, index)[1],
                evidence_refs=evidence,
            )
            for index in range(request.output.image_output_count)
            for scenario, presence in [_IMAGE_SCENARIOS[index % len(_IMAGE_SCENARIOS)]]
        )
        video_plans = tuple(
            self._video_plan(request, evidence, index, family)
            for index in range(request.output.video_output_count)
        )
        return CreativeAutomationPlan(
            plan_id=f"creative-automation-plan:{request.request_id}",
            readiness=OrchestrationReadiness.READY,
            strategy_summary=prepared.selected_idea.concept,
            rationale="Synthetic diverse portfolio for deterministic verification.",
            evidence_refs=evidence,
            image_plans=image_plans,
            video_plans=video_plans,
            memory_refs=tuple(item.memory_id for item in memory),
            model_profile=self._config.profile_id,
            prompt_version=self._config.prompt_version,
        )

    def _video_plan(self, request, evidence, index: int, family) -> AssembledVideoCreativePlan:
        scenario, presence, voice_mode, music_mode = _VIDEO_SCENARIOS[index % len(_VIDEO_SCENARIOS)]
        preferred_durations = (15, 20, 25, 18)
        duration = (
            request.output.video_duration_seconds
            or preferred_durations[index % len(preferred_durations)]
        )
        duration = max(
            request.output.video_duration_min_seconds,
            min(duration, request.output.video_duration_max_seconds),
        )
        max_source_duration = request.output.video_scene_duration_max_seconds
        strategy = (
            VideoGenerationStrategy.ONE_SHOT
            if duration <= max_source_duration
            else VideoGenerationStrategy.MULTI_SOURCE
        )
        scene_durations = _scene_durations(duration, max_source_duration)
        voice_direction = (
            None
            if voice_mode == VideoVoiceMode.NONE
            else "Use one consistent natural US English voice and complete each sentence within a source."
        )
        music_direction = (
            None
            if music_mode == VideoMusicMode.NONE
            else "Use one coherent background music identity and keep it below any speech."
        )
        selected_variant_id, selected_media_ids = _selection(
            family, request.selected_variant_id, index
        )
        audio_plan = VideoAudioCreativePlan(
            voice_mode=voice_mode,
            music_mode=music_mode,
            voice_direction=voice_direction,
            music_direction=music_direction,
            continuity_direction="Keep voice, music, ambience, and loudness continuous across sources.",
        )
        return AssembledVideoCreativePlan(
            variation_key=f"video-{index + 1}",
            scenario=scenario,
            creative_hypothesis=f"Test whether {scenario.lower()} communicates product value.",
            human_presence=presence,
            generation_strategy=strategy,
            final_duration_seconds=duration,
            continuity_plan=(
                "Keep the same product, people, wardrobe, setting, lighting, and motion direction. "
                "Use intentional action or match cuts between sources."
            ),
            product_id=family.ref.product_id if family is not None else "",
            audio_plan=audio_plan,
            scenes=tuple(
                VideoSceneCreativePlan(
                    scene_id=f"scene-{scene_index + 1}",
                    purpose=(
                        "Complete one coherent product story"
                        if len(scene_durations) == 1
                        else "Hook"
                        if scene_index == 0
                        else "Payoff"
                    ),
                    visual_direction=(
                        f"Create the {scenario.lower()} source with natural product motion. "
                        "No text, captions, logos, or watermarks."
                    ),
                    audio_direction=_scene_audio_direction(audio_plan),
                    transition_direction=(
                        "No transition; this is the complete one-shot output."
                        if len(scene_durations) == 1
                        else "End on a stable action state that supports an intentional cut."
                    ),
                    duration_seconds=scene_duration,
                    evidence_refs=evidence,
                    generation_duration_seconds=scene_duration,
                    selected_variant_id=selected_variant_id,
                    selected_media_ids=selected_media_ids,
                )
                for scene_index, scene_duration in enumerate(scene_durations)
            ),
            background_music_direction=music_direction,
            evidence_refs=evidence,
        )


def _selection(family, pinned_variant_id: str | None, index: int):
    if family is None:
        return None, ()
    variant = next(
        (item for item in family.variants if item.variant_id == pinned_variant_id),
        family.variants[index % len(family.variants)],
    )
    media_ids = tuple(
        item.media_id
        for item in family.media
        if not item.variant_ids or variant.variant_id in item.variant_ids
    )
    if not media_ids:
        raise ValueError("Synthetic orchestration found no media for the selected variant")
    return variant.variant_id, media_ids[:4]


def _scene_durations(duration: int, maximum: int) -> tuple[int, ...]:
    if duration <= maximum:
        return (duration,)
    first = duration // 2
    return (first, duration - first)


def _scene_audio_direction(plan: VideoAudioCreativePlan) -> str | None:
    directions = tuple(
        item for item in (plan.voice_direction, plan.music_direction) if item is not None
    )
    return " ".join(directions) or None


__all__ = ["FakeCreativeAutomationOrchestrator"]
