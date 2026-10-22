"""BAML/Terra adapter for Media Lab video planning, review and prompt repair."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import replace
from typing import Protocol, Self

from baml_py import Collector, Image
from baml_py.baml_py import BamlError
from baml_py.logging import set_log_level
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)
from ai_content.platform.observability import observe_ai_call

from ..config.orchestration import MediaLabVideoOrchestratorConfig
from ..domain.models import ImageBinary
from ..domain.video_ads import VideoAdShotPlan, VideoAdTimelinePlan
from ..domain.video_models import (
    VideoCapability,
    VideoIntent,
    VideoOrchestrationPlan,
    VideoOrchestrationTrace,
    VideoPlanningImageSource,
    VideoPlanningState,
    VideoQualityDecision,
    VideoQualityIssue,
    VideoQualityIssueSeverity,
    VideoQualityReview,
    VideoQualityReviewRequest,
    VideoSourcePlan,
    VideoSourceRole,
    VideoSourceUsage,
    VideoVerificationReport,
    VideoVerificationStage,
    VideoVerificationStagePlan,
)
from ..ports.video_interfaces import (
    IVideoOrchestrator,
    IVideoQualityReviewer,
    MediaLabVideoOrchestrationError,
    MediaLabVideoQualityReviewError,
)
from .baml_client import types as baml_types
from .baml_client.async_client import b
from .baml_client.inlinedbaml import get_baml_files


class _BamlMediaLabTerraVideoClient(Protocol):
    async def PlanMediaLabVideo(
        self,
        instructions: str,
        input_json: str,
        capabilities_json: str,
        sources: list[baml_types.MediaLabVideoPlanningImage],
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabVideoPlan: ...

    async def PlanMediaLabVideoAd(
        self,
        instructions: str,
        input_json: str,
        sources: list[baml_types.MediaLabVideoPlanningImage],
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabVideoAdPlan: ...

    async def ReviewMediaLabVideo(
        self,
        instructions: str,
        input_json: str,
        sources: list[baml_types.MediaLabVideoReviewImage],
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabVideoQualityReview: ...

    async def RewriteMediaLabVideoPrompt(
        self,
        instructions: str,
        input_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabVideoRepairPrompt: ...


_CAPABILITY_IDS = {
    baml_types.MediaLabVideoCapabilityId.CREATE_FROM_TEXT: "create_from_text",
    baml_types.MediaLabVideoCapabilityId.CREATE_FROM_IMAGES: "create_from_images",
}


class _QualityIssueOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    severity: VideoQualityIssueSeverity
    description: str = Field(min_length=1)


class _QualityReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: VideoQualityDecision
    summary: str = Field(min_length=1)
    issues: tuple[_QualityIssueOutput, ...] = ()
    repair_instructions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_decision_details(self) -> Self:
        if self.decision == VideoQualityDecision.PASS and (
            self.issues or self.repair_instructions or self.uncertainties
        ):
            raise ValueError("pass quality review cannot contain issues or uncertainty")
        if self.decision == VideoQualityDecision.REGENERATE and (
            not self.issues or not self.repair_instructions
        ):
            raise ValueError("regenerate quality review requires issues and repair instructions")
        if self.decision == VideoQualityDecision.HUMAN_REVIEW and not (
            self.issues or self.uncertainties
        ):
            raise ValueError("human review quality decision requires an issue or uncertainty")
        return self


class _RepairPromptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_prompt: str = Field(min_length=1)


class BamlMediaLabVideoOrchestrator(IVideoOrchestrator, IVideoQualityReviewer):
    def __init__(
        self,
        config: MediaLabVideoOrchestratorConfig,
        *,
        api_key: str | None,
        capabilities: tuple[VideoCapability, ...],
        client: _BamlMediaLabTerraVideoClient | None = None,
        usage_tracker: AIUsageTracker | None = None,
    ) -> None:
        if config.api_key_env and not api_key:
            raise MediaLabVideoOrchestrationError(
                "Configured Media Lab video orchestration credential is missing",
                status_code=503,
                code="model_credentials_missing",
            )
        self._config = config
        self._usage_tracker = usage_tracker
        self._maximum_video_ad_generation_images = max(
            (
                capability.maximum_generation_images
                for capability in capabilities
                if capability.intent == VideoIntent.CREATE_FROM_IMAGES
            ),
            default=0,
        )
        # BAML INFO logging can include raw prompts and media context.
        set_log_level("OFF")
        self._client = client or b.with_options(
            env={
                "MEDIA_LAB_TERRA_BASE_URL": config.base_url,
                "MEDIA_LAB_TERRA_MODEL": config.model,
                "MEDIA_LAB_TERRA_API_KEY": api_key or "local-no-auth",
            }
        )
        self._baml_source = get_baml_files()["image_orchestration.baml"]
        self._template_hash = hashlib.sha256(self._baml_source.encode("utf-8")).hexdigest()
        self._planning_prompt_hash = _template_prompt_hash(
            self._baml_source,
            "PlanMediaLabVideo",
            config.prompt.text,
        )
        self._video_ad_prompt_hash = (
            _template_prompt_hash(
                self._baml_source,
                "PlanMediaLabVideoAd",
                config.video_ad_prompt.text,
            )
            if config.video_ad_prompt is not None
            else None
        )

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def max_source_images(self) -> int:
        return self._config.max_source_images

    @property
    def max_regenerations(self) -> int:
        quality = self._config.quality_review
        return quality.max_regenerations if quality is not None else 0

    @property
    def quality_review_enabled(self) -> bool:
        return self._config.quality_review is not None

    async def plan(
        self,
        user_request: str,
        sources: tuple[VideoPlanningImageSource, ...],
        capabilities: tuple[VideoCapability, ...],
    ) -> VideoOrchestrationPlan:
        self._validate_planning_sources(sources)
        input_json = json.dumps(
            {
                "user_request": user_request,
                "source_manifest": [
                    {
                        "source_index": source.source_index,
                        "source_origin": source.source_origin.value,
                        "source_run_id": source.source_run_id,
                    }
                    for source in sources
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self._validate_context_size(input_json)
        capabilities_json = json.dumps(
            _capability_contract(capabilities),
            ensure_ascii=False,
            sort_keys=True,
        )
        baml_sources = [
            baml_types.MediaLabVideoPlanningImage(
                source_index=source.source_index,
                content=_baml_image(source.image.content_type, source.image.content),
            )
            for source in sources
        ]
        collector = Collector(name="media-lab-video-orchestration")
        event_id = None
        with observe_ai_call(
            "media_lab.video_orchestration",
            "baml",
            self._config.model,
            prompt_version=self._planning_prompt_version,
            prompt_hash=self._planning_prompt_hash,
            config_hash=self._config.config_hash,
            input_image_count=len(sources),
        ) as observation:
            if self._usage_tracker is not None:
                event_id = await self._usage_tracker.start(
                    AIUsageStart(
                        workstream="media_lab",
                        operation="video_orchestration.plan",
                        backend="baml",
                        model=self._config.model,
                    )
                )
            try:
                async with asyncio.timeout(self._config.request_timeout_seconds):
                    output = await self._client.PlanMediaLabVideo(
                        instructions=self._config.prompt.text,
                        input_json=input_json,
                        capabilities_json=capabilities_json,
                        sources=baml_sources,
                        baml_options={"collector": collector},
                    )
                plan = self._to_plan(user_request, output)
            except (TimeoutError, BamlError, ValueError) as error:
                error_code = _error_code(error)
                if event_id is not None:
                    await self._usage_tracker.fail(
                        event_id,
                        AIUsageFailure(
                            error_code=error_code,
                            request_count=_request_count(collector),
                            input_tokens=collector.usage.input_tokens,
                            output_tokens=collector.usage.output_tokens,
                        ),
                    )
                observation.fail(error_code)
                raise MediaLabVideoOrchestrationError(
                    "Terra could not prepare a Media Lab video plan",
                    code=error_code,
                ) from error
            if event_id is not None:
                await self._usage_tracker.succeed(
                    event_id,
                    AIUsageCompletion(
                        request_count=_request_count(collector),
                        input_tokens=collector.usage.input_tokens,
                        output_tokens=collector.usage.output_tokens,
                        output_count=1,
                    ),
                )
            observation.usage(collector.usage.input_tokens, collector.usage.output_tokens)
            observation.succeed()
            return plan

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
    ) -> VideoAdTimelinePlan:
        prompt = self._config.video_ad_prompt
        if prompt is None or self._video_ad_prompt_hash is None:
            raise MediaLabVideoOrchestrationError(
                "Terra final Video Ad planning is not configured",
                status_code=503,
                code="video_ad_planning_not_configured",
            )
        self._validate_video_ad_sources(sources)
        input_json = json.dumps(
            {
                "user_request": user_request,
                "brand": brand,
                "sku": sku,
                "angle": angle,
                "target_duration_seconds": target_duration_seconds,
                "aspect_ratio": aspect_ratio,
                "cta_text": cta_text,
                "source_count": len(sources),
                "maximum_generation_images": self._maximum_video_ad_generation_images,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self._validate_context_size(input_json)
        baml_sources = [
            baml_types.MediaLabVideoPlanningImage(
                source_index=index,
                content=_baml_image(source.content_type, source.content),
            )
            for index, source in enumerate(sources)
        ]
        collector = Collector(name="media-lab-video-ad-orchestration")
        event_id = None
        with observe_ai_call(
            "media_lab.video_ad_orchestration",
            "baml",
            self._config.model,
            prompt_version=f"{prompt.version}+baml:{self._template_hash[:12]}",
            prompt_hash=self._video_ad_prompt_hash,
            config_hash=self._config.config_hash,
            input_image_count=len(sources),
        ) as observation:
            if self._usage_tracker is not None:
                event_id = await self._usage_tracker.start(
                    AIUsageStart(
                        workstream="media_lab",
                        operation="video_ad_orchestration.plan",
                        backend="baml",
                        model=self._config.model,
                    )
                )
            try:
                async with asyncio.timeout(self._config.request_timeout_seconds):
                    output = await self._client.PlanMediaLabVideoAd(
                        instructions=prompt.text,
                        input_json=input_json,
                        sources=baml_sources,
                        baml_options={"collector": collector},
                    )
                plan = self._to_video_ad_plan(
                    output,
                    target_duration_seconds=target_duration_seconds,
                    aspect_ratio=aspect_ratio,
                    source_count=len(sources),
                )
            except (TimeoutError, BamlError, ValueError) as error:
                error_code = _error_code(error)
                if event_id is not None:
                    await self._usage_tracker.fail(
                        event_id,
                        AIUsageFailure(
                            error_code=error_code,
                            request_count=_request_count(collector),
                            input_tokens=collector.usage.input_tokens,
                            output_tokens=collector.usage.output_tokens,
                        ),
                    )
                observation.fail(error_code)
                raise MediaLabVideoOrchestrationError(
                    "Terra could not prepare a final Video Ad plan",
                    code=error_code,
                ) from error
            if event_id is not None:
                await self._usage_tracker.succeed(
                    event_id,
                    AIUsageCompletion(
                        request_count=_request_count(collector),
                        input_tokens=collector.usage.input_tokens,
                        output_tokens=collector.usage.output_tokens,
                        output_count=1,
                    ),
                )
            observation.usage(collector.usage.input_tokens, collector.usage.output_tokens)
            observation.succeed(shot_count=len(plan.shots))
            return plan

    def _to_video_ad_plan(
        self,
        output: baml_types.MediaLabVideoAdPlan,
        *,
        target_duration_seconds: float,
        aspect_ratio: str,
        source_count: int,
    ) -> VideoAdTimelinePlan:
        prompt = self._config.video_ad_prompt
        assert prompt is not None
        assert self._video_ad_prompt_hash is not None
        state = output.state.value.lower()
        questions = tuple(item.strip() for item in output.questions if item.strip())
        source_plans = _video_source_plans(output.sources)
        if state == "needs_input":
            if not questions or output.shots or source_plans:
                raise ValueError("Terra returned an invalid needs-input Video Ad plan")
            return VideoAdTimelinePlan(
                summary=output.summary.strip(),
                questions=questions,
                uncertainties=tuple(item.strip() for item in output.uncertainties if item.strip()),
                target_duration_seconds=target_duration_seconds,
                aspect_ratio=aspect_ratio,
                sources=(),
                shots=(),
                planner_model=self._config.model,
                planner_prompt_version=f"{prompt.version}+baml:{self._template_hash[:12]}",
                planner_prompt_hash=self._video_ad_prompt_hash,
                planner_config_hash=self._config.config_hash,
                plan_hash=_video_ad_plan_hash(output),
            )
        shots = tuple(
            VideoAdShotPlan(
                shot_id=item.shot_id.strip(),
                purpose=item.purpose.strip(),
                prompt=item.production_prompt.strip(),
                intent=(
                    VideoIntent.CREATE_FROM_IMAGES
                    if item.source_indexes
                    else VideoIntent.CREATE_FROM_TEXT
                ),
                source_indexes=tuple(item.source_indexes),
                generation_duration_seconds=item.generation_duration_seconds,
                usable_duration_seconds=item.usable_duration_seconds,
                on_screen_text=(item.on_screen_text.strip() if item.on_screen_text else None),
            )
            for item in output.shots
        )
        if questions:
            raise ValueError("Terra returned questions for a ready final Video Ad plan")
        if (
            abs(output.target_duration_seconds - target_duration_seconds) > 0.01
            or output.aspect_ratio != aspect_ratio
        ):
            raise ValueError("Terra changed the requested final Video Ad output contract")
        _validate_video_ad_plan(
            source_plans,
            shots,
            target_duration_seconds,
            aspect_ratio,
            source_count,
            self._maximum_video_ad_generation_images,
        )
        return VideoAdTimelinePlan(
            summary=output.summary.strip(),
            questions=questions,
            uncertainties=tuple(item.strip() for item in output.uncertainties if item.strip()),
            target_duration_seconds=target_duration_seconds,
            aspect_ratio=aspect_ratio,
            sources=source_plans,
            shots=shots,
            planner_model=self._config.model,
            planner_prompt_version=f"{prompt.version}+baml:{self._template_hash[:12]}",
            planner_prompt_hash=self._video_ad_prompt_hash,
            planner_config_hash=self._config.config_hash,
            plan_hash=_video_ad_plan_hash(output),
        )

    async def review(self, request: VideoQualityReviewRequest) -> VideoQualityReview:
        quality = self._require_quality_review()
        self._validate_quality_review_images(request)
        input_json = json.dumps(
            _quality_review_context(request),
            ensure_ascii=False,
            sort_keys=True,
        )
        self._validate_quality_context_size(input_json)
        prompt_hash = _template_prompt_hash(
            self._baml_source,
            "ReviewMediaLabVideo",
            quality.prompt.text,
            input_json,
        )
        sources = [
            *[
                baml_types.MediaLabVideoReviewImage(
                    label=frame.label,
                    content=_baml_image(frame.image.content_type, frame.image.content),
                )
                for frame in request.candidate_evidence.frames
            ],
            *[
                baml_types.MediaLabVideoReviewImage(
                    label=source.label,
                    content=_baml_image(source.image.content_type, source.image.content),
                )
                for source in request.sources
            ],
        ]
        collector = Collector(name="media-lab-video-quality-review")
        event_id = None
        with observe_ai_call(
            "media_lab.video_quality_review",
            "baml",
            self._config.model,
            prompt_version=self._quality_prompt_version,
            prompt_hash=prompt_hash,
            config_hash=self._config.config_hash,
            input_image_count=len(sources),
            run_id=request.run_id,
        ) as observation:
            if self._usage_tracker is not None:
                event_id = await self._usage_tracker.start(
                    AIUsageStart(
                        workstream="media_lab",
                        operation="video_quality_review",
                        backend="baml",
                        model=self._config.model,
                        job_id=request.run_id,
                    )
                )
            try:
                async with asyncio.timeout(quality.request_timeout_seconds):
                    raw_output = await self._client.ReviewMediaLabVideo(
                        instructions=quality.prompt.text,
                        input_json=input_json,
                        sources=sources,
                        baml_options={"collector": collector},
                    )
                output = _QualityReviewOutput.model_validate(_normalized_quality_output(raw_output))
                review = self._to_quality_review(output, prompt_hash, request.verification)
            except (TimeoutError, BamlError, ValidationError, ValueError) as error:
                error_code = _error_code(error)
                if event_id is not None:
                    await self._usage_tracker.fail(
                        event_id,
                        AIUsageFailure(
                            error_code=error_code,
                            request_count=_request_count(collector),
                            input_tokens=collector.usage.input_tokens,
                            output_tokens=collector.usage.output_tokens,
                        ),
                    )
                observation.fail(error_code)
                raise MediaLabVideoQualityReviewError(
                    "Terra could not review the generated Media Lab video",
                    code=error_code,
                ) from error
            if event_id is not None:
                await self._usage_tracker.succeed(
                    event_id,
                    AIUsageCompletion(
                        request_count=_request_count(collector),
                        input_tokens=collector.usage.input_tokens,
                        output_tokens=collector.usage.output_tokens,
                        output_count=1,
                    ),
                )
            observation.usage(collector.usage.input_tokens, collector.usage.output_tokens)
            observation.semantic_review(review.decision.value, "advisory")
            observation.succeed(issue_count=len(review.issues))
            return review

    async def repair_prompt(
        self,
        request: VideoQualityReviewRequest,
        review: VideoQualityReview,
    ) -> VideoQualityReview:
        quality = self._require_quality_review()
        if review.decision != VideoQualityDecision.REGENERATE:
            raise MediaLabVideoQualityReviewError(
                "Only a regenerate review can produce a replacement video prompt",
                code="invalid_quality_review",
            )
        input_json = json.dumps(
            {
                **_quality_review_context(request),
                "quality_review": {
                    "summary": review.summary,
                    "issues": [
                        {
                            "category": issue.category,
                            "severity": issue.severity.value,
                            "description": issue.description,
                        }
                        for issue in review.issues
                    ],
                    "repair_instructions": list(review.repair_instructions),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self._validate_quality_context_size(input_json)
        prompt_hash = _template_prompt_hash(
            self._baml_source,
            "RewriteMediaLabVideoPrompt",
            quality.repair_prompt.text,
            input_json,
        )
        collector = Collector(name="media-lab-video-prompt-repair")
        event_id = None
        with observe_ai_call(
            "media_lab.video_prompt_repair",
            "baml",
            self._config.model,
            prompt_version=self._repair_prompt_version,
            prompt_hash=prompt_hash,
            config_hash=self._config.config_hash,
            run_id=request.run_id,
        ) as observation:
            if self._usage_tracker is not None:
                event_id = await self._usage_tracker.start(
                    AIUsageStart(
                        workstream="media_lab",
                        operation="video_prompt_repair",
                        backend="baml",
                        model=self._config.model,
                        job_id=request.run_id,
                    )
                )
            try:
                async with asyncio.timeout(quality.request_timeout_seconds):
                    raw_output = await self._client.RewriteMediaLabVideoPrompt(
                        instructions=quality.repair_prompt.text,
                        input_json=input_json,
                        baml_options={"collector": collector},
                    )
                output = _RepairPromptOutput.model_validate(raw_output.model_dump(mode="json"))
            except (TimeoutError, BamlError, ValidationError, ValueError) as error:
                error_code = _error_code(error)
                if event_id is not None:
                    await self._usage_tracker.fail(
                        event_id,
                        AIUsageFailure(
                            error_code=error_code,
                            request_count=_request_count(collector),
                            input_tokens=collector.usage.input_tokens,
                            output_tokens=collector.usage.output_tokens,
                        ),
                    )
                observation.fail(error_code)
                raise MediaLabVideoQualityReviewError(
                    "Terra could not prepare a corrected Media Lab video prompt",
                    code=error_code,
                ) from error
            if event_id is not None:
                await self._usage_tracker.succeed(
                    event_id,
                    AIUsageCompletion(
                        request_count=_request_count(collector),
                        input_tokens=collector.usage.input_tokens,
                        output_tokens=collector.usage.output_tokens,
                        output_count=1,
                    ),
                )
            production_prompt = output.production_prompt.strip()
            observation.usage(collector.usage.input_tokens, collector.usage.output_tokens)
            observation.succeed()
            return replace(
                review,
                repair_prompt=production_prompt,
                repair_prompt_version=self._repair_prompt_version,
                repair_prompt_hash=prompt_hash,
            )

    @property
    def _planning_prompt_version(self) -> str:
        return f"{self._config.prompt.version}+baml:{self._template_hash[:12]}"

    @property
    def _quality_prompt_version(self) -> str:
        return f"{self._require_quality_review().prompt.version}+baml:{self._template_hash[:12]}"

    @property
    def _repair_prompt_version(self) -> str:
        return (
            f"{self._require_quality_review().repair_prompt.version}"
            f"+baml:{self._template_hash[:12]}"
        )

    def _to_plan(
        self,
        user_request: str,
        output: baml_types.MediaLabVideoPlan,
    ) -> VideoOrchestrationPlan:
        state = VideoPlanningState(output.state.value.lower())
        capability_id = (
            _CAPABILITY_IDS[output.capability_id] if output.capability_id is not None else None
        )
        production_prompt = output.production_prompt.strip() if output.production_prompt else None
        sources = tuple(
            VideoSourcePlan(
                source_index=item.source_index,
                role=VideoSourceRole(item.role.value.lower()),
                usage=VideoSourceUsage(item.usage.value.lower()),
                priority=item.priority,
                must_preserve=tuple(value.strip() for value in item.must_preserve if value.strip()),
                allowed_changes=tuple(
                    value.strip() for value in item.allowed_changes if value.strip()
                ),
                identity_group=(
                    item.identity_group.strip()
                    if item.identity_group and item.identity_group.strip()
                    else None
                ),
                is_primary_identity=item.is_primary_identity,
            )
            for item in output.sources
        )
        verification_plan = tuple(
            VideoVerificationStagePlan(
                stage=VideoVerificationStage(item.stage.value.lower()),
                reason=item.reason.strip(),
            )
            for item in output.verification_plan
        )
        if state == VideoPlanningState.NEEDS_INPUT and not output.questions:
            raise ValueError("needs-input plan did not contain a question")
        trace = VideoOrchestrationTrace(
            user_request=user_request,
            capability_id=capability_id or "needs_input",
            summary=output.summary.strip(),
            planner_model=self._config.model,
            planner_prompt_version=self._planning_prompt_version,
            planner_prompt_hash=self._planning_prompt_hash,
            planner_config_hash=self._config.config_hash,
            plan_hash=_plan_hash(
                state,
                output.summary,
                output.questions,
                output.uncertainties,
                capability_id,
                production_prompt,
                sources,
                verification_plan,
            ),
        )
        return VideoOrchestrationPlan(
            state=state,
            summary=output.summary.strip(),
            questions=tuple(question.strip() for question in output.questions if question.strip()),
            uncertainties=tuple(
                uncertainty.strip() for uncertainty in output.uncertainties if uncertainty.strip()
            ),
            capability_id=capability_id,
            production_prompt=production_prompt,
            sources=sources,
            verification_plan=verification_plan,
            trace=trace,
        )

    def _to_quality_review(
        self,
        output: _QualityReviewOutput,
        prompt_hash: str,
        verification: VideoVerificationReport | None = None,
    ) -> VideoQualityReview:
        issues = tuple(
            VideoQualityIssue(
                category=item.category.strip(),
                severity=item.severity,
                description=item.description.strip(),
            )
            for item in output.issues
        )
        review_hash = hashlib.sha256(
            json.dumps(
                {
                    "decision": output.decision.value,
                    "summary": output.summary,
                    "issues": [
                        {
                            "category": item.category,
                            "severity": item.severity.value,
                            "description": item.description,
                        }
                        for item in issues
                    ],
                    "repair_instructions": output.repair_instructions,
                    "uncertainties": output.uncertainties,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return VideoQualityReview(
            decision=output.decision,
            summary=output.summary.strip(),
            issues=issues,
            repair_instructions=tuple(
                value.strip() for value in output.repair_instructions if value.strip()
            ),
            uncertainties=tuple(value.strip() for value in output.uncertainties if value.strip()),
            reviewer_model=self._config.model,
            reviewer_prompt_version=self._quality_prompt_version,
            reviewer_prompt_hash=prompt_hash,
            reviewer_config_hash=self._config.config_hash,
            review_hash=review_hash,
            verification=verification,
        )

    def _validate_planning_sources(
        self,
        sources: tuple[VideoPlanningImageSource, ...],
    ) -> None:
        if len(sources) > self._config.max_source_images:
            raise MediaLabVideoOrchestrationError(
                "Media Lab Terra planning exceeds the configured image-source capacity",
                status_code=400,
                code="too_many_sources",
            )
        total_image_bytes = sum(len(source.image.content) for source in sources)
        if total_image_bytes > self._config.max_total_image_bytes:
            raise MediaLabVideoOrchestrationError(
                "Planning images exceed the configured total byte limit",
                status_code=400,
                code="sources_too_large",
            )

    def _validate_video_ad_sources(self, sources: tuple[ImageBinary, ...]) -> None:
        if len(sources) > self._config.max_source_images:
            raise MediaLabVideoOrchestrationError(
                "Media Lab Terra planning exceeds the configured image-source capacity",
                status_code=400,
                code="too_many_sources",
            )
        if sum(len(source.content) for source in sources) > self._config.max_total_image_bytes:
            raise MediaLabVideoOrchestrationError(
                "Planning images exceed the configured total byte limit",
                status_code=400,
                code="sources_too_large",
            )

    def _validate_quality_review_images(self, request: VideoQualityReviewRequest) -> None:
        quality = self._require_quality_review()
        labels = [
            *(frame.label for frame in request.candidate_evidence.frames),
            *(source.label for source in request.sources),
        ]
        if len(set(labels)) != len(labels):
            raise MediaLabVideoQualityReviewError(
                "Media Lab video review labels must be unique",
                code="invalid_review_sources",
            )
        total = sum(len(frame.image.content) for frame in request.candidate_evidence.frames) + sum(
            len(source.image.content) for source in request.sources
        )
        if total > quality.max_total_image_bytes:
            raise MediaLabVideoQualityReviewError(
                "Review images exceed the configured total byte limit",
                code="sources_too_large",
            )

    def _validate_context_size(self, input_json: str) -> None:
        if len(input_json.encode("utf-8")) > self._config.max_context_bytes:
            raise MediaLabVideoOrchestrationError(
                "Creative request exceeds the configured orchestration input limit",
                status_code=400,
                code="model_input_too_large",
            )

    def _validate_quality_context_size(self, input_json: str) -> None:
        try:
            self._validate_context_size(input_json)
        except MediaLabVideoOrchestrationError as error:
            raise MediaLabVideoQualityReviewError(
                "Media Lab video quality-review context exceeds the configured input limit",
                code=error.code,
            ) from error

    def _require_quality_review(self):
        quality = self._config.quality_review
        if quality is None:
            raise MediaLabVideoQualityReviewError(
                "Media Lab Terra video quality review is not configured",
                code="quality_review_not_configured",
            )
        return quality


def _capability_contract(capabilities: tuple[VideoCapability, ...]) -> list[dict[str, object]]:
    return [
        {
            "capability_id": capability.capability_id,
            "intent": capability.intent.value,
            "minimum_generation_images": capability.minimum_generation_images,
            "maximum_generation_images": capability.maximum_generation_images,
            "supported_duration_seconds": list(capability.supported_duration_seconds),
        }
        for capability in capabilities
    ]


def _quality_review_context(request: VideoQualityReviewRequest) -> dict[str, object]:
    return {
        "run_id": request.run_id,
        "user_request": request.user_request,
        "production_prompt": request.production_prompt,
        "temporal_evidence": {
            "sampling_rate_fps": request.candidate_evidence.sampling_rate_fps,
            "duration_milliseconds": request.candidate_evidence.duration_milliseconds,
            "candidate_frames": [
                {
                    "label": frame.label,
                    "timestamp_milliseconds": frame.timestamp_milliseconds,
                }
                for frame in request.candidate_evidence.frames
            ],
        },
        "reference_contract": [
            {
                "label": source.label,
                "role": source.role.value,
                "usage": source.usage.value,
                "must_preserve": list(source.must_preserve),
                "allowed_changes": list(source.allowed_changes),
                "identity_group": source.identity_group,
                "is_primary_identity": source.is_primary_identity,
            }
            for source in request.sources
        ],
        "image_order": [
            *(frame.label for frame in request.candidate_evidence.frames),
            *(source.label for source in request.sources),
        ],
        "verification": _verification_context(request.verification),
        "retry_memory": _retry_memory_context(request),
    }


def _retry_memory_context(request: VideoQualityReviewRequest) -> dict[str, object] | None:
    memory = request.retry_memory
    if memory is None:
        return None
    return {
        "root_run_id": memory.root_run_id,
        "attempts": [
            {
                "run_id": attempt.run_id,
                "seed": attempt.seed,
                "production_prompt": attempt.production_prompt,
                "output_asset_id": attempt.output_asset_id,
                "output_checksum_sha256": attempt.output_checksum_sha256,
                "duration_seconds": attempt.duration_seconds,
                "output_preset_id": attempt.output_preset_id,
                "review_decision": (
                    attempt.review_decision.value if attempt.review_decision is not None else None
                ),
                "review_summary": attempt.review_summary,
                "repair_instructions": list(attempt.repair_instructions),
                "repair_prompt": attempt.repair_prompt,
                "verifier_status": (
                    attempt.verifier_status.value if attempt.verifier_status is not None else None
                ),
                "suspicious_timestamps_milliseconds": list(
                    attempt.suspicious_timestamps_milliseconds
                ),
            }
            for attempt in memory.attempts
        ],
    }


def _normalized_quality_output(output: baml_types.MediaLabVideoQualityReview) -> dict[str, object]:
    payload = output.model_dump(mode="json")
    payload["decision"] = payload["decision"].lower()
    for issue in payload["issues"]:
        issue["severity"] = issue["severity"].lower()
    return payload


def _baml_image(content_type: str, content: bytes) -> Image:
    return Image.from_base64(content_type, base64.b64encode(content).decode("ascii"))


def _template_prompt_hash(
    baml_source: str,
    function: str,
    instructions: str,
    input_json: str | None = None,
) -> str:
    payload: dict[str, str] = {
        "baml": baml_source,
        "function": function,
        "instructions": instructions,
    }
    if input_json is not None:
        payload["input"] = input_json
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _plan_hash(
    state: VideoPlanningState,
    summary: str,
    questions: list[str],
    uncertainties: list[str],
    capability_id: str | None,
    production_prompt: str | None,
    sources: tuple[VideoSourcePlan, ...],
    verification_plan: tuple[VideoVerificationStagePlan, ...],
) -> str:
    payload = {
        "state": state.value,
        "summary": summary,
        "questions": questions,
        "uncertainties": uncertainties,
        "capability_id": capability_id,
        "production_prompt": production_prompt,
        "sources": [
            {
                "source_index": source.source_index,
                "role": source.role.value,
                "usage": source.usage.value,
                "priority": source.priority,
                "must_preserve": list(source.must_preserve),
                "allowed_changes": list(source.allowed_changes),
                "identity_group": source.identity_group,
                "is_primary_identity": source.is_primary_identity,
            }
            for source in sources
        ],
        "verification_plan": [
            {"stage": item.stage.value, "reason": item.reason} for item in verification_plan
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _request_count(collector: Collector) -> int:
    log = collector.last
    return max(1, len(log.calls)) if log is not None else 1


def _error_code(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "provider_timeout"
    if isinstance(error, BamlError):
        return "provider_error"
    if isinstance(error, ValidationError):
        return "invalid_provider_schema"
    return "invalid_provider_output"


def _video_source_plans(
    sources: list[baml_types.MediaLabVideoSourcePlan],
) -> tuple[VideoSourcePlan, ...]:
    return tuple(
        VideoSourcePlan(
            source_index=item.source_index,
            role=VideoSourceRole(item.role.value.lower()),
            usage=VideoSourceUsage(item.usage.value.lower()),
            priority=item.priority,
            must_preserve=tuple(value.strip() for value in item.must_preserve if value.strip()),
            allowed_changes=tuple(value.strip() for value in item.allowed_changes if value.strip()),
            identity_group=(
                item.identity_group.strip()
                if item.identity_group and item.identity_group.strip()
                else None
            ),
            is_primary_identity=item.is_primary_identity,
        )
        for item in sources
    )


def _validate_video_ad_plan(
    sources: tuple[VideoSourcePlan, ...],
    shots: tuple[VideoAdShotPlan, ...],
    target_duration_seconds: float,
    aspect_ratio: str,
    source_count: int,
    maximum_generation_images: int,
) -> None:
    if aspect_ratio not in {"1:1", "9:16", "16:9"}:
        raise ValueError("Unsupported final Video Ad aspect ratio")
    source_indexes = tuple(source.source_index for source in sources)
    if (
        len(sources) != source_count
        or len(set(source_indexes)) != len(source_indexes)
        or set(source_indexes) != set(range(source_count))
    ):
        raise ValueError("Terra did not resolve every final Video Ad source exactly once")
    identity_roles = {VideoSourceRole.PRODUCT, VideoSourceRole.CHARACTER}
    primary_groups: set[str] = set()
    for source in sources:
        if source.usage != VideoSourceUsage.GENERATION or not 1 <= source.priority <= 100:
            raise ValueError("Terra returned an invalid final Video Ad source contract")
        if source.role in identity_roles:
            if not source.identity_group:
                raise ValueError("Terra omitted an identity group for a Video Ad source")
            if source.is_primary_identity:
                primary_groups.add(source.identity_group)
        elif source.identity_group is not None or source.is_primary_identity:
            raise ValueError("Terra assigned identity metadata to a non-identity source")
    if len(primary_groups) > 1:
        raise ValueError("Terra selected more than one primary Video Ad identity group")
    if not 3 <= len(shots) <= 6 or len({shot.shot_id for shot in shots}) != len(shots):
        raise ValueError("Terra returned an invalid final Video Ad shot count")
    if abs(sum(shot.usable_duration_seconds for shot in shots) - target_duration_seconds) > 0.01:
        raise ValueError("Terra final Video Ad shot durations do not match the target")
    for shot in shots:
        if (
            not shot.prompt
            or not 4 <= shot.generation_duration_seconds <= 8
            or not 3 <= shot.usable_duration_seconds <= shot.generation_duration_seconds
            or len(set(shot.source_indexes)) != len(shot.source_indexes)
            or len(shot.source_indexes) > maximum_generation_images
            or any(index < 0 or index >= source_count for index in shot.source_indexes)
        ):
            raise ValueError("Terra returned an invalid final Video Ad shot")


def _video_ad_plan_hash(output: baml_types.MediaLabVideoAdPlan) -> str:
    payload = {
        "state": output.state.value,
        "summary": output.summary,
        "questions": output.questions,
        "uncertainties": output.uncertainties,
        "target_duration_seconds": output.target_duration_seconds,
        "aspect_ratio": output.aspect_ratio,
        "sources": [
            {
                "source_index": item.source_index,
                "role": item.role.value,
                "usage": item.usage.value,
                "priority": item.priority,
                "must_preserve": item.must_preserve,
                "allowed_changes": item.allowed_changes,
                "identity_group": item.identity_group,
                "is_primary_identity": item.is_primary_identity,
            }
            for item in output.sources
        ],
        "shots": [
            {
                "shot_id": item.shot_id,
                "purpose": item.purpose,
                "production_prompt": item.production_prompt,
                "source_indexes": item.source_indexes,
                "generation_duration_seconds": item.generation_duration_seconds,
                "usable_duration_seconds": item.usable_duration_seconds,
                "on_screen_text": item.on_screen_text,
            }
            for item in output.shots
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


__all__ = ["BamlMediaLabVideoOrchestrator"]


def _verification_context(report: VideoVerificationReport | None) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "status": report.status.value,
        "verifier_version": report.verifier_version,
        "config_hash": report.config_hash,
        "suspicious_timestamps_milliseconds": list(report.suspicious_timestamps_milliseconds),
        "uncertainties": list(report.uncertainties),
        "stages": [
            {
                "stage": stage.stage.value,
                "status": stage.status.value,
                "model": stage.model,
                "model_version": stage.model_version,
                "metadata": dict(stage.metadata),
                "observations": [
                    {
                        "observation_id": observation.observation_id,
                        "category": observation.category,
                        "status": observation.status.value,
                        "severity": observation.severity.value,
                        "description": observation.description,
                        "confidence": observation.confidence,
                        "start_timestamp_milliseconds": observation.start_timestamp_milliseconds,
                        "end_timestamp_milliseconds": observation.end_timestamp_milliseconds,
                        "evidence_refs": list(observation.evidence_refs),
                    }
                    for observation in stage.observations
                ],
            }
            for stage in report.stages
        ],
    }
