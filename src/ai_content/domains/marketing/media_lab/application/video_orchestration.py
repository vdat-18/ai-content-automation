"""LLM orchestration service for the bounded Media Lab Create Video flow."""

from __future__ import annotations

from ..domain.video_models import (
    VideoCapability,
    VideoOrchestrationPlan,
    VideoPlanningImageSource,
    VideoPlanningState,
    VideoSourceOrigin,
    VideoSourceRole,
    VideoSourceUsage,
    VideoVerificationStage,
)
from ..ports.video_interfaces import IVideoOrchestrator, MediaLabVideoOrchestrationError


class MediaLabVideoOrchestrationService:
    def __init__(
        self,
        orchestrator: IVideoOrchestrator,
        capabilities: tuple[VideoCapability, ...],
    ) -> None:
        self._orchestrator = orchestrator
        self._capabilities = capabilities

    def model(self) -> str:
        return self._orchestrator.model

    def maximum_source_count(self) -> int:
        return self._orchestrator.max_source_images

    def maximum_generation_source_count(self) -> int:
        return max(capability.maximum_generation_images for capability in self._capabilities)

    async def plan(
        self,
        user_request: str,
        sources: tuple[VideoPlanningImageSource, ...],
    ) -> VideoOrchestrationPlan:
        if not user_request.strip():
            raise MediaLabVideoOrchestrationError(
                "Creative request cannot be blank",
                status_code=400,
                code="invalid_request",
            )
        if len(sources) > self.maximum_source_count():
            raise MediaLabVideoOrchestrationError(
                "Planning sources exceed the configured video planning capacity",
                status_code=400,
                code="too_many_sources",
            )
        if tuple(source.source_index for source in sources) != tuple(range(len(sources))):
            raise MediaLabVideoOrchestrationError(
                "Planning sources must have consecutive indexes",
                status_code=400,
                code="invalid_sources",
            )
        plan = await self._orchestrator.plan(
            user_request.strip(),
            sources,
            self._capabilities,
        )
        self._validate_plan(plan, sources)
        return plan

    def _validate_plan(
        self,
        plan: VideoOrchestrationPlan,
        sources: tuple[VideoPlanningImageSource, ...],
    ) -> None:
        if plan.state == VideoPlanningState.NEEDS_INPUT:
            if (
                plan.capability_id is not None
                or plan.production_prompt is not None
                or plan.sources
                or plan.verification_plan
            ):
                raise MediaLabVideoOrchestrationError(
                    "Terra returned an invalid needs-input video plan",
                    code="invalid_provider_output",
                )
            return
        if plan.state != VideoPlanningState.READY:
            raise MediaLabVideoOrchestrationError(
                "Terra returned an unknown video plan state",
                code="invalid_provider_output",
            )
        if plan.capability_id is None or plan.production_prompt is None:
            raise MediaLabVideoOrchestrationError(
                "Terra returned an incomplete ready video plan",
                code="invalid_provider_output",
            )
        capability = next(
            (item for item in self._capabilities if item.capability_id == plan.capability_id),
            None,
        )
        if capability is None:
            raise MediaLabVideoOrchestrationError(
                "Terra selected an unsupported Media Lab video capability",
                code="invalid_provider_output",
            )
        source_indexes = tuple(item.source_index for item in plan.sources)
        if (
            len(plan.sources) != len(sources)
            or len(set(source_indexes)) != len(source_indexes)
            or set(source_indexes) != set(range(len(sources)))
        ):
            raise MediaLabVideoOrchestrationError(
                "Terra did not resolve every video source exactly once",
                code="invalid_provider_output",
            )
        generation_sources = tuple(
            item
            for item in plan.sources
            if item.usage in {VideoSourceUsage.GENERATION, VideoSourceUsage.BOTH}
        )
        if not (
            capability.minimum_generation_images
            <= len(generation_sources)
            <= capability.maximum_generation_images
        ):
            raise MediaLabVideoOrchestrationError(
                "Terra selected an invalid number of generation sources",
                code="invalid_provider_output",
            )
        if not generation_sources and sources:
            raise MediaLabVideoOrchestrationError(
                "Terra ignored every supplied image during generation",
                code="invalid_provider_output",
            )
        selected_stages = tuple(item.stage for item in plan.verification_plan)
        if (
            len(set(selected_stages)) != len(selected_stages)
            or VideoVerificationStage.TECHNICAL in selected_stages
            or VideoVerificationStage.TEMPORAL_QUALITY not in selected_stages
            or (
                VideoVerificationStage.PRODUCT_FIDELITY in selected_stages
                and VideoVerificationStage.TRACKING not in selected_stages
            )
            or any(not item.reason.strip() for item in plan.verification_plan)
        ):
            raise MediaLabVideoOrchestrationError(
                "Terra returned an invalid video verification plan",
                code="invalid_provider_output",
            )
        identity_roles = {VideoSourceRole.PRODUCT, VideoSourceRole.CHARACTER}
        for item in plan.sources:
            if item.role in identity_roles and not item.identity_group:
                raise MediaLabVideoOrchestrationError(
                    "Terra omitted an identity group for a product or character source",
                    code="invalid_provider_output",
                )
            if item.role not in identity_roles and (
                item.identity_group is not None or item.is_primary_identity
            ):
                raise MediaLabVideoOrchestrationError(
                    "Terra assigned identity metadata to a non-identity source",
                    code="invalid_provider_output",
                )
            if item.is_primary_identity and item.usage not in {
                VideoSourceUsage.VERIFICATION,
                VideoSourceUsage.BOTH,
            }:
                raise MediaLabVideoOrchestrationError(
                    "A primary identity must be used for verification",
                    code="invalid_provider_output",
                )

        tracking_sources = tuple(
            item
            for item in plan.sources
            if item.role in identity_roles
            and item.usage in {VideoSourceUsage.VERIFICATION, VideoSourceUsage.BOTH}
        )
        primary_sources = tuple(item for item in tracking_sources if item.is_primary_identity)
        if VideoVerificationStage.TRACKING in selected_stages:
            primary_groups = {item.identity_group for item in primary_sources}
            primary_roles = {item.role for item in primary_sources}
            if (
                not primary_sources
                or len(primary_groups) != 1
                or None in primary_groups
                or len(primary_roles) != 1
                or any(not item.is_primary_identity for item in tracking_sources)
            ):
                raise MediaLabVideoOrchestrationError(
                    "Tracking requires exactly one primary product or character identity group",
                    code="invalid_provider_output",
                )
        elif any(item.is_primary_identity for item in plan.sources):
            raise MediaLabVideoOrchestrationError(
                "Terra selected a primary identity without tracking verification",
                code="invalid_provider_output",
            )

        if VideoVerificationStage.PRODUCT_FIDELITY in selected_stages:
            if not primary_sources or any(
                item.role != VideoSourceRole.PRODUCT for item in primary_sources
            ):
                raise MediaLabVideoOrchestrationError(
                    "Product-fidelity verification requires one primary product identity group",
                    code="invalid_provider_output",
                )
            if any(
                sources[item.source_index].source_origin != VideoSourceOrigin.UPLOAD
                for item in primary_sources
            ):
                raise MediaLabVideoOrchestrationError(
                    "Generated images cannot be used as product-truth evidence",
                    code="invalid_provider_output",
                )
        for source in plan.sources:
            if source.priority < 1 or source.priority > 100:
                raise MediaLabVideoOrchestrationError(
                    "Terra returned an invalid video source priority",
                    code="invalid_provider_output",
                )
            if (
                source.usage in {VideoSourceUsage.VERIFICATION, VideoSourceUsage.BOTH}
                and not source.must_preserve
            ):
                raise MediaLabVideoOrchestrationError(
                    "Terra omitted preservation constraints for a verification source",
                    code="invalid_provider_output",
                )


__all__ = ["MediaLabVideoOrchestrationService"]
