"""BAML/Terra adapter for Media Lab planning, review and prompt repair."""

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

from ..config.orchestration import MediaLabImageOrchestratorConfig
from ..domain.models import (
    ImageCapability,
    ImageOrchestrationPlan,
    ImageOrchestrationTrace,
    ImagePlanningSource,
    ImagePlanningState,
    ImageQualityDecision,
    ImageQualityIssue,
    ImageQualityIssueSeverity,
    ImageQualityReview,
    ImageQualityReviewRequest,
    ImageReferencePlan,
    ImageReferenceRole,
)
from ..ports.interfaces import (
    IImageOrchestrator,
    IImageQualityReviewer,
    MediaLabImageOrchestrationError,
    MediaLabImageQualityReviewError,
)
from .baml_client import types as baml_types
from .baml_client.async_client import b
from .baml_client.inlinedbaml import get_baml_files


class _BamlMediaLabTerraClient(Protocol):
    async def PlanMediaLabImage(
        self,
        instructions: str,
        input_json: str,
        capabilities_json: str,
        sources: list[baml_types.MediaLabPlanningImage],
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabImagePlan: ...

    async def ReviewMediaLabImage(
        self,
        instructions: str,
        input_json: str,
        sources: list[baml_types.MediaLabReviewImage],
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabImageQualityReview: ...

    async def RewriteMediaLabImagePrompt(
        self,
        instructions: str,
        input_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.MediaLabImageRepairPrompt: ...


_CAPABILITY_IDS = {
    baml_types.MediaLabImageCapabilityId.CREATE_FROM_TEXT: "create_from_text",
    baml_types.MediaLabImageCapabilityId.PRODUCT_SOURCE: "product_source",
    baml_types.MediaLabImageCapabilityId.PRODUCT_AND_STYLE: "product_and_style",
    baml_types.MediaLabImageCapabilityId.EDIT_EXISTING: "edit_existing",
}


class _QualityIssueOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    severity: ImageQualityIssueSeverity
    description: str = Field(min_length=1)


class _QualityReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ImageQualityDecision
    summary: str = Field(min_length=1)
    issues: tuple[_QualityIssueOutput, ...] = ()
    repair_instructions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_decision_details(self) -> Self:
        if self.decision == ImageQualityDecision.PASS and (
            self.issues or self.repair_instructions or self.uncertainties
        ):
            raise ValueError("pass quality review cannot contain issues or uncertainty")
        if self.decision == ImageQualityDecision.REGENERATE and (
            not self.issues or not self.repair_instructions
        ):
            raise ValueError("regenerate quality review requires issues and repair instructions")
        if self.decision == ImageQualityDecision.HUMAN_REVIEW and not (
            self.issues or self.uncertainties
        ):
            raise ValueError("human review quality decision requires an issue or uncertainty")
        return self


class _RepairPromptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_prompt: str = Field(min_length=1)


class BamlMediaLabImageOrchestrator(IImageOrchestrator, IImageQualityReviewer):
    def __init__(
        self,
        config: MediaLabImageOrchestratorConfig,
        *,
        api_key: str | None,
        client: _BamlMediaLabTerraClient | None = None,
        usage_tracker: AIUsageTracker | None = None,
    ) -> None:
        if config.api_key_env and not api_key:
            raise MediaLabImageOrchestrationError(
                "Configured Media Lab orchestration credential is missing",
                status_code=503,
                code="model_credentials_missing",
            )
        self._config = config
        self._usage_tracker = usage_tracker
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
            "PlanMediaLabImage",
            config.prompt.text,
        )

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def max_images(self) -> int:
        return self._config.max_images

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
        sources: tuple[ImagePlanningSource, ...],
        capabilities: tuple[ImageCapability, ...],
    ) -> ImageOrchestrationPlan:
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
            baml_types.MediaLabPlanningImage(
                source_index=source.source_index,
                content=_baml_image(source.image.content_type, source.image.content),
            )
            for source in sources
        ]
        collector = Collector(name="media-lab-image-orchestration")
        event_id = None
        with observe_ai_call(
            "media_lab.image_orchestration",
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
                        operation="image_orchestration.plan",
                        backend="baml",
                        model=self._config.model,
                    )
                )
            try:
                async with asyncio.timeout(self._config.request_timeout_seconds):
                    output = await self._client.PlanMediaLabImage(
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
                raise MediaLabImageOrchestrationError(
                    "Terra could not prepare a Media Lab image plan",
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

    async def review(self, request: ImageQualityReviewRequest) -> ImageQualityReview:
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
            "ReviewMediaLabImage",
            quality.prompt.text,
            input_json,
        )
        sources = [
            baml_types.MediaLabReviewImage(
                label="candidate",
                content=_baml_image(request.candidate.content_type, request.candidate.content),
            ),
            *[
                baml_types.MediaLabReviewImage(
                    label=source.label,
                    content=_baml_image(source.image.content_type, source.image.content),
                )
                for source in request.sources
            ],
        ]
        collector = Collector(name="media-lab-image-quality-review")
        event_id = None
        with observe_ai_call(
            "media_lab.image_quality_review",
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
                        operation="image_quality_review",
                        backend="baml",
                        model=self._config.model,
                        job_id=request.run_id,
                    )
                )
            try:
                async with asyncio.timeout(quality.request_timeout_seconds):
                    raw_output = await self._client.ReviewMediaLabImage(
                        instructions=quality.prompt.text,
                        input_json=input_json,
                        sources=sources,
                        baml_options={"collector": collector},
                    )
                output = _QualityReviewOutput.model_validate(_normalized_quality_output(raw_output))
                review = self._to_quality_review(output, prompt_hash)
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
                raise MediaLabImageQualityReviewError(
                    "Terra could not review the generated Media Lab image",
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
        request: ImageQualityReviewRequest,
        review: ImageQualityReview,
    ) -> ImageQualityReview:
        quality = self._require_quality_review()
        if review.decision != ImageQualityDecision.REGENERATE:
            raise MediaLabImageQualityReviewError(
                "Only a regenerate review can produce a replacement image prompt",
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
            "RewriteMediaLabImagePrompt",
            quality.repair_prompt.text,
            input_json,
        )
        collector = Collector(name="media-lab-image-prompt-repair")
        event_id = None
        with observe_ai_call(
            "media_lab.image_prompt_repair",
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
                        operation="image_prompt_repair",
                        backend="baml",
                        model=self._config.model,
                        job_id=request.run_id,
                    )
                )
            try:
                async with asyncio.timeout(quality.request_timeout_seconds):
                    raw_output = await self._client.RewriteMediaLabImagePrompt(
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
                raise MediaLabImageQualityReviewError(
                    "Terra could not prepare a corrected Media Lab image prompt",
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
        return f"{self._require_quality_review().repair_prompt.version}+baml:{self._template_hash[:12]}"

    def _to_plan(
        self,
        user_request: str,
        output: baml_types.MediaLabImagePlan,
    ) -> ImageOrchestrationPlan:
        state = ImagePlanningState(output.state.value.lower())
        capability_id = (
            _CAPABILITY_IDS[output.capability_id] if output.capability_id is not None else None
        )
        production_prompt = output.production_prompt.strip() if output.production_prompt else None
        references = tuple(
            ImageReferencePlan(
                source_index=item.source_index,
                role=ImageReferenceRole(item.role.value.lower()),
                priority=item.priority,
                must_preserve=tuple(value.strip() for value in item.must_preserve if value.strip()),
                allowed_changes=tuple(
                    value.strip() for value in item.allowed_changes if value.strip()
                ),
                identity_group=(
                    item.identity_group.strip()
                    if item.identity_group is not None and item.identity_group.strip()
                    else None
                ),
            )
            for item in output.references
        )
        if state == ImagePlanningState.NEEDS_INPUT and not output.questions:
            raise ValueError("needs-input plan did not contain a question")
        trace = ImageOrchestrationTrace(
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
                references,
            ),
        )
        return ImageOrchestrationPlan(
            state=state,
            summary=output.summary.strip(),
            questions=tuple(question.strip() for question in output.questions if question.strip()),
            uncertainties=tuple(
                uncertainty.strip() for uncertainty in output.uncertainties if uncertainty.strip()
            ),
            capability_id=capability_id,
            production_prompt=production_prompt,
            references=references,
            trace=trace,
        )

    def _to_quality_review(
        self,
        output: _QualityReviewOutput,
        prompt_hash: str,
    ) -> ImageQualityReview:
        issues = tuple(
            ImageQualityIssue(
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
        return ImageQualityReview(
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
        )

    def _validate_planning_sources(self, sources: tuple[ImagePlanningSource, ...]) -> None:
        if len(sources) > self._config.max_images:
            raise MediaLabImageOrchestrationError(
                f"Media Lab Terra planning supports at most {self._config.max_images} image inputs",
                status_code=400,
                code="too_many_sources",
            )
        if (
            sum(len(source.image.content) for source in sources)
            > self._config.max_total_image_bytes
        ):
            raise MediaLabImageOrchestrationError(
                "Planning images exceed the configured total byte limit",
                status_code=400,
                code="sources_too_large",
            )

    def _validate_quality_review_images(self, request: ImageQualityReviewRequest) -> None:
        quality = self._require_quality_review()
        labels = [source.label for source in request.sources]
        if len(set(labels)) != len(labels):
            raise MediaLabImageQualityReviewError(
                "Media Lab review source labels must be unique",
                code="invalid_review_sources",
            )
        total = len(request.candidate.content) + sum(
            len(source.image.content) for source in request.sources
        )
        if total > quality.max_total_image_bytes:
            raise MediaLabImageQualityReviewError(
                "Review images exceed the configured total byte limit",
                code="sources_too_large",
            )

    def _validate_context_size(self, input_json: str) -> None:
        if len(input_json.encode("utf-8")) > self._config.max_context_bytes:
            raise MediaLabImageOrchestrationError(
                "Creative request exceeds the configured orchestration input limit",
                status_code=400,
                code="model_input_too_large",
            )

    def _validate_quality_context_size(self, input_json: str) -> None:
        try:
            self._validate_context_size(input_json)
        except MediaLabImageOrchestrationError as error:
            raise MediaLabImageQualityReviewError(
                "Media Lab quality-review context exceeds the configured input limit",
                code=error.code,
            ) from error

    def _require_quality_review(self):
        quality = self._config.quality_review
        if quality is None:
            raise MediaLabImageQualityReviewError(
                "Media Lab Terra quality review is not configured",
                code="quality_review_not_configured",
            )
        return quality


def _capability_contract(
    capabilities: tuple[ImageCapability, ...],
) -> list[dict[str, object]]:
    return [
        {
            "capability_id": capability.capability_id,
            "intent": capability.intent.value,
            "required_roles": [role.value for role in capability.required_roles],
            "minimum_style_reference_count": capability.minimum_style_reference_count,
            "maximum_style_reference_count": capability.maximum_style_reference_count,
        }
        for capability in capabilities
    ]


def _quality_review_context(request: ImageQualityReviewRequest) -> dict[str, object]:
    return {
        "run_id": request.run_id,
        "user_request": request.user_request,
        "production_prompt": request.production_prompt,
        "candidate_label": "candidate",
        "reference_contract": [
            {
                "label": source.label,
                "role": source.role.value,
                "must_preserve": list(source.must_preserve),
                "allowed_changes": list(source.allowed_changes),
                "identity_group": source.identity_group,
            }
            for source in request.sources
        ],
        "image_order": ["candidate", *(source.label for source in request.sources)],
        "retry_memory": _retry_memory_context(request),
    }


def _retry_memory_context(request: ImageQualityReviewRequest) -> dict[str, object] | None:
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
                "review_decision": (
                    attempt.review_decision.value if attempt.review_decision is not None else None
                ),
                "review_summary": attempt.review_summary,
                "repair_instructions": list(attempt.repair_instructions),
                "repair_prompt": attempt.repair_prompt,
            }
            for attempt in memory.attempts
        ],
    }


def _normalized_quality_output(
    output: baml_types.MediaLabImageQualityReview,
) -> dict[str, object]:
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
    state: ImagePlanningState,
    summary: str,
    questions: list[str],
    uncertainties: list[str],
    capability_id: str | None,
    production_prompt: str | None,
    references: tuple[ImageReferencePlan, ...],
) -> str:
    payload = {
        "state": state.value,
        "summary": summary,
        "questions": questions,
        "uncertainties": uncertainties,
        "capability_id": capability_id,
        "production_prompt": production_prompt,
        "references": [
            {
                "source_index": reference.source_index,
                "role": reference.role.value,
                "priority": reference.priority,
                "must_preserve": list(reference.must_preserve),
                "allowed_changes": list(reference.allowed_changes),
                "identity_group": reference.identity_group,
            }
            for reference in references
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


__all__ = ["BamlMediaLabImageOrchestrator"]
