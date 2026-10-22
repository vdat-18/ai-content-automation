"""BAML adapter for bounded Creative strategy and brief model calls."""

import asyncio
import base64
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, Literal, Protocol

from baml_py import Collector, Image
from baml_py.baml_py import BamlError
from baml_py.logging import set_log_level
from loguru import logger
from pydantic import TypeAdapter

from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)
from ai_content.platform.observability import observe_ai_call

from ..application.model_context import preparation_context_for_model
from ..config.preparation import PreparationConfig, PreparationPrompt
from ..ports.contracts import CreativeWorkItemInput, ExperimentContext
from ..ports.preparation import (
    BriefDraft,
    BriefReview,
    CompositionDraft,
    IdeaAssessment,
    IdeaCritique,
    IdeaDraft,
    ModelCallTrace,
    ModelStepResult,
    PersonaHypothesis,
    PreparationContext,
    PreparationError,
    RegionDraft,
    TextPlacementDraft,
    VariationBriefDraft,
)
from .baml_client import types as baml_types
from .baml_client.async_client import b
from .baml_client.inlinedbaml import get_baml_files
from .baml_model_profile import build_creative_orchestrator_registry
from .image_files import inspect_image, read_local_image

_BAML_FUNCTIONS = {
    "persona": "ResolveCreativePersona",
    "ideas": "GenerateCreativeIdeas",
    "idea_critique": "CritiqueCreativeIdeas",
    "brief": "WriteCreativeBrief",
    "brief_review": "ReviewCreativeBrief",
    "composition": "PlanStaticComposition",
}


class _BamlPreparationClient(Protocol):
    async def ResolveCreativePersona(
        self,
        instructions: str,
        input_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.CreativePersonaHypothesis: ...

    async def GenerateCreativeIdeas(
        self,
        instructions: str,
        input_json: str,
        max_ideas: int,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeIdeaCandidates: ...

    async def CritiqueCreativeIdeas(
        self,
        instructions: str,
        input_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeIdeaCritique: ...

    async def WriteCreativeBrief(
        self,
        instructions: str,
        input_json: str,
        variation_count: int,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeBriefDraft: ...

    async def ReviewCreativeBrief(
        self,
        instructions: str,
        input_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeBriefReview: ...

    async def PlanStaticComposition(
        self,
        instructions: str,
        input_json: str,
        product_images: list[baml_types.LabeledReviewImage],
        baml_options: dict[str, object],
    ) -> baml_types.StaticCompositionDraft: ...


class BamlPreparationModel:
    def __init__(
        self,
        config: PreparationConfig,
        *,
        api_key: str | None = None,
        client: _BamlPreparationClient | None = None,
        usage_tracker: AIUsageTracker | None = None,
        image_reader: Callable[[str], bytes] | None = None,
    ) -> None:
        self._config = config
        self._usage_tracker = usage_tracker
        self._image_reader = image_reader or read_local_image
        # BAML INFO logs include full prompts; application telemetry records metadata only.
        set_log_level("OFF")
        if config.api_key_env:
            if not api_key:
                raise PreparationError(
                    "Configured model credential environment variable is missing",
                    "model_credentials_missing",
                )
        else:
            api_key = "local-no-auth"
        if config.fallback_model is not None:
            raise PreparationError(
                "Creative Orchestrator does not allow automatic model fallback",
                "model_fallback_not_allowed",
            )
        if client is not None:
            self._client = client
        else:
            self._client = b.with_options(
                client_registry=build_creative_orchestrator_registry(
                    name="CreativeOrchestrator",
                    base_url=config.base_url,
                    model=config.model,
                    api_key=api_key or "local-no-auth",
                    reasoning_effort=config.reasoning_effort,
                    temperature=config.temperature,
                    max_output_tokens=config.max_output_tokens,
                )
            )
        self._baml_source = get_baml_files()["creative_preparation.baml"]

    async def resolve_persona(
        self, context: PreparationContext, work_item: CreativeWorkItemInput
    ) -> ModelStepResult[PersonaHypothesis]:
        prompt = self._config.persona_prompt
        if prompt is None:
            raise PreparationError(
                "Persona resolution prompt is not configured",
                "persona_resolution_not_configured",
            )
        payload = self._payload(context, work_item)
        output, trace = await self._call(
            "persona",
            prompt,
            payload,
            lambda collector, instructions: self._client.ResolveCreativePersona(
                instructions=instructions,
                input_json=payload,
                baml_options={"collector": collector},
            ),
            work_item,
        )
        hypothesis = PersonaHypothesis(
            name=output.name.strip(),
            description=output.description.strip(),
            rationale=output.rationale.strip(),
            evidence_refs=self._evidence_refs(output.evidence_refs),
            uncertainties=tuple(output.uncertainties),
        )
        if not hypothesis.name or not hypothesis.description or not hypothesis.rationale:
            raise PreparationError(
                "Persona resolution returned incomplete content",
                "persona_resolution_invalid",
                trace=trace,
            )
        return ModelStepResult(hypothesis, trace)

    async def propose(
        self, context: PreparationContext, work_item: CreativeWorkItemInput
    ) -> ModelStepResult[tuple[IdeaDraft, ...]]:
        payload = self._payload(context, work_item)
        output, trace = await self._call(
            "ideas",
            self._config.idea_prompt,
            payload,
            lambda collector, instructions: self._client.GenerateCreativeIdeas(
                instructions=instructions,
                input_json=payload,
                max_ideas=self._config.max_ideas,
                baml_options={"collector": collector},
            ),
            work_item,
        )
        ideas = tuple(
            IdeaDraft(
                persona_id=item.persona_id,
                angle=item.angle,
                hook=item.hook,
                concept=item.concept,
                rationale=item.rationale,
                evidence_refs=self._evidence_refs(item.evidence_refs),
                claim_ids=tuple(item.claim_ids),
                reference_ids=tuple(item.reference_ids),
            )
            for item in output.ideas[: self._config.max_ideas]
        )
        if not ideas:
            raise PreparationError("Model returned no Creative ideas", "model_invalid_output")
        return ModelStepResult(ideas, trace)

    async def write_brief(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
    ) -> ModelStepResult[BriefDraft]:
        payload = self._payload(context, work_item, selected)
        output, trace = await self._call(
            "brief",
            self._config.brief_prompt,
            payload,
            lambda collector, instructions: self._client.WriteCreativeBrief(
                instructions=instructions,
                input_json=payload,
                variation_count=work_item.variation_count,
                baml_options={"collector": collector},
            ),
            work_item,
        )
        return ModelStepResult(
            self._brief_draft(output),
            trace,
        )

    async def critique_ideas(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        candidates: tuple[IdeaDraft, ...],
        eligible_candidate_indices: tuple[int, ...],
    ) -> ModelStepResult[IdeaCritique]:
        payload = self._payload(
            context,
            work_item,
            candidates=candidates,
            eligible_candidate_indices=eligible_candidate_indices,
        )
        output, trace = await self._call(
            "idea_critique",
            self._config.idea_critique_prompt,
            payload,
            lambda collector, instructions: self._client.CritiqueCreativeIdeas(
                instructions=instructions,
                input_json=payload,
                baml_options={"collector": collector},
            ),
            work_item,
        )
        return ModelStepResult(
            IdeaCritique(
                selected_candidate_index=output.selected_candidate_index,
                rationale=output.rationale,
                evidence_refs=self._evidence_refs(output.evidence_refs),
                assessments=tuple(
                    IdeaAssessment(
                        candidate_index=assessment.candidate_index,
                        recommendation=assessment.recommendation.value.lower(),
                        rationale=assessment.rationale,
                        evidence_refs=self._evidence_refs(assessment.evidence_refs),
                        concerns=tuple(assessment.concerns),
                    )
                    for assessment in output.assessments
                ),
                uncertainties=tuple(output.uncertainties),
            ),
            trace,
        )

    async def review_brief(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        draft: BriefDraft,
    ) -> ModelStepResult[BriefReview]:
        payload = self._payload(context, work_item, selected=selected, brief=draft)
        output, trace = await self._call(
            "brief_review",
            self._config.brief_review_prompt,
            payload,
            lambda collector, instructions: self._client.ReviewCreativeBrief(
                instructions=instructions,
                input_json=payload,
                baml_options={"collector": collector},
            ),
            work_item,
        )
        return ModelStepResult(
            BriefReview(
                outcome=output.outcome.value.lower(),
                rationale=output.rationale,
                evidence_refs=self._evidence_refs(output.evidence_refs),
                issues=tuple(output.issues),
                revision_instructions=tuple(output.revision_instructions),
                revised_brief=(
                    self._brief_draft(output.revised_brief)
                    if output.revised_brief is not None
                    else None
                ),
            ),
            trace,
        )

    async def plan_composition(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        brief: BriefDraft,
    ) -> ModelStepResult[CompositionDraft]:
        payload = self._payload(context, work_item, selected=selected, brief=brief)
        product_images = self._product_images(context)
        output, trace = await self._call(
            "composition",
            self._config.composition_prompt,
            payload,
            lambda collector, instructions: self._client.PlanStaticComposition(
                instructions=instructions,
                input_json=payload,
                product_images=product_images,
                baml_options={"collector": collector},
            ),
            work_item,
        )
        return ModelStepResult(
            CompositionDraft(
                visual_prompt=output.visual_prompt,
                product_region=self._region(output.product_region),
                heading=self._text_placement(output.heading),
                subtext=(self._text_placement(output.subtext) if output.subtext else None),
                logo_region=self._region(output.logo_region) if output.logo_region else None,
                rationale=output.rationale,
                evidence_refs=self._evidence_refs(output.evidence_refs),
                product_source_index=output.product_source_index,
                segmentation_prompt=output.segmentation_prompt,
            ),
            trace,
        )

    def _product_images(self, context: PreparationContext) -> list[baml_types.LabeledReviewImage]:
        images: list[baml_types.LabeledReviewImage] = []
        for index, reference in enumerate(context.sku.product_metadata.image_refs):
            content = self._image_reader(reference)
            _, _, image_format = inspect_image(content)
            mime = "image/jpeg" if image_format == "jpeg" else f"image/{image_format}"
            images.append(
                baml_types.LabeledReviewImage(
                    label=f"product_source_{index}",
                    content=Image.from_base64(mime, base64.b64encode(content).decode("ascii")),
                )
            )
        for reference in context.references:
            content = self._image_reader(reference.asset.url)
            _, _, image_format = inspect_image(content)
            mime = "image/jpeg" if image_format == "jpeg" else f"image/{image_format}"
            images.append(
                baml_types.LabeledReviewImage(
                    label=f"research_reference:{reference.reference_id}",
                    content=Image.from_base64(mime, base64.b64encode(content).decode("ascii")),
                )
            )
        return images

    @staticmethod
    def _region(output: baml_types.CompositionRegion) -> RegionDraft:
        return RegionDraft(output.x, output.y, output.width, output.height)

    @classmethod
    def _text_placement(cls, output: baml_types.CompositionTextPlacement) -> TextPlacementDraft:
        return TextPlacementDraft(
            region=cls._region(output.region),
            alignment=output.alignment.value.lower(),
            text_color=output.text_color,
            background_color=output.background_color,
        )

    @staticmethod
    def _evidence_refs(evidence_refs: list[str]) -> tuple[str, ...]:
        return tuple(reference.strip() for reference in evidence_refs)

    @classmethod
    def _brief_draft(cls, output: baml_types.CreativeBriefDraft) -> BriefDraft:
        return BriefDraft(
            heading=output.heading,
            visual_direction=output.visual_direction,
            evidence_refs=cls._evidence_refs(output.evidence_refs),
            subtext=output.subtext,
            claim_ids=tuple(output.claim_ids),
            reference_ids=tuple(output.reference_ids),
            variations=tuple(
                VariationBriefDraft(
                    variation_key=item.variation_key,
                    heading=item.heading,
                    visual_direction=item.visual_direction,
                    evidence_refs=cls._evidence_refs(item.evidence_refs),
                    subtext=item.subtext,
                    awareness_stage=item.awareness_stage,
                    angle=item.angle,
                    offer=item.offer,
                    production_level=item.production_level,
                    claim_ids=tuple(item.claim_ids),
                    reference_ids=tuple(item.reference_ids),
                )
                for item in output.variations
            ),
        )

    def _payload(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft | None = None,
        candidates: tuple[IdeaDraft, ...] = (),
        eligible_candidate_indices: tuple[int, ...] = (),
        brief: BriefDraft | None = None,
    ) -> str:
        payload = {
            "context": preparation_context_for_model(context),
            "allowed_evidence_refs": tuple(
                dict.fromkeys(
                    (
                        *(source.source_id for source in context.package.evidence),
                        *(
                            work_item.experiment_context.evidence_refs
                            if work_item.experiment_context is not None
                            else ()
                        ),
                    )
                )
            ),
            "objective": work_item.objective,
            "channel": work_item.channel,
            "market": work_item.marketing_scope.market,
            "time_window": work_item.time_window,
            "persona_override": work_item.persona_override,
            "creative_direction_override": work_item.creative_direction_override,
            "campaign_notes": work_item.campaign_notes,
            "requested_image_count": work_item.requested_image_count,
            "requested_video_count": work_item.requested_video_count,
            "experiment_context": TypeAdapter(ExperimentContext | None).dump_python(
                work_item.experiment_context, mode="json"
            ),
            "selected_idea": TypeAdapter(IdeaDraft | None).dump_python(selected, mode="json"),
            "candidates": TypeAdapter(tuple[IdeaDraft, ...]).dump_python(candidates, mode="json"),
            "eligible_candidate_indices": eligible_candidate_indices,
            "brief": TypeAdapter(BriefDraft | None).dump_python(brief, mode="json"),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    async def _call(
        self,
        step: Literal["persona", "ideas", "idea_critique", "brief", "brief_review", "composition"],
        prompt: PreparationPrompt,
        payload: str,
        operation: Callable[[Collector, str], Awaitable[Any]],
        work_item: CreativeWorkItemInput,
    ) -> tuple[Any, ModelCallTrace]:
        prompt_text = json.dumps(
            {
                "baml": self._baml_source,
                "function": _BAML_FUNCTIONS[step],
                "instructions": prompt.text,
                "input": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        started = monotonic()
        collectors: list[Collector] = []

        def trace(error_code: str | None = None) -> ModelCallTrace:
            model = self._config.model
            for completed_collector in reversed(collectors):
                log = completed_collector.last
                selected_call = log.selected_call if log is not None else None
                if selected_call is None:
                    continue
                if (
                    selected_call.client_name == "LocalMarketingFallbackLLM"
                    and self._config.fallback_model is not None
                ):
                    model = self._config.fallback_model
                break
            request_count = 0
            input_tokens: int | None = None
            output_tokens: int | None = None
            for completed_collector in collectors:
                log = completed_collector.last
                request_count += len(log.calls) if log is not None else 1
                usage = completed_collector.usage
                if usage.input_tokens is not None:
                    input_tokens = (input_tokens or 0) + usage.input_tokens
                if usage.output_tokens is not None:
                    output_tokens = (output_tokens or 0) + usage.output_tokens
            return ModelCallTrace(
                step=step,
                backend="baml",
                model=model,
                prompt_version=prompt.version,
                prompt_hash=prompt_hash,
                prompt_text=None,
                config_hash=self._config.config_hash,
                elapsed_seconds=monotonic() - started,
                request_count=request_count,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=None,
                error_code=error_code,
            )

        with observe_ai_call(
            f"preparation.{step}",
            "baml",
            self._config.model,
            prompt_version=prompt.version,
            prompt_hash=prompt_hash,
            config_hash=self._config.config_hash,
        ) as observation:
            if (
                self._config.max_context_bytes is not None
                and len(prompt_text.encode("utf-8")) > self._config.max_context_bytes
            ):
                code = "model_input_too_large"
                call_trace = trace(code)
                observation.fail(code)
                raise PreparationError(
                    "Prepared model input exceeds the configured byte limit",
                    code,
                    trace=call_trace,
                )
            code = "model_service_error"
            previous_event_id: str | None = None
            for attempt in range(self._config.max_attempts):
                retry_delay_seconds = self._config.retry_delay_seconds
                collector = Collector(name=f"creative-{step}-attempt-{attempt + 1}")
                collectors.append(collector)
                event_id = None
                if self._usage_tracker is not None:
                    event_id = await self._usage_tracker.start(
                        AIUsageStart(
                            workstream="creative",
                            operation=f"preparation.{step}",
                            backend="baml",
                            model=self._config.model,
                            source_run_id=work_item.source_run_id,
                            brand_id=work_item.marketing_scope.brand,
                            parent_event_id=previous_event_id,
                            attempt_number=attempt + 1,
                        )
                    )
                try:
                    async with asyncio.timeout(self._config.step_timeout_seconds):
                        output = await operation(
                            collector, _retry_instructions(prompt.text, step, attempt)
                        )
                except TimeoutError:
                    code = "model_timeout"
                except BamlError as error:
                    code = "model_service_error"
                    retry_delay_seconds = _provider_retry_delay_seconds(
                        error, self._config.retry_delay_seconds
                    )
                    logger.warning(
                        "Creative preparation model call failed; retrying "
                        "step={} attempt={} reason={}",
                        step,
                        attempt + 1,
                        str(error),
                    )
                else:
                    if event_id is not None:
                        model, request_count, input_tokens, output_tokens = _collector_usage(
                            collector, self._config
                        )
                        await self._usage_tracker.succeed(
                            event_id,
                            AIUsageCompletion(
                                model=model,
                                request_count=request_count,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                output_count=1,
                            ),
                        )
                    call_trace = trace()
                    observation.update(
                        model=call_trace.model,
                        request_count=call_trace.request_count,
                    )
                    observation.usage(call_trace.input_tokens, call_trace.output_tokens)
                    observation.succeed()
                    return output, call_trace
                if event_id is not None:
                    model, request_count, input_tokens, output_tokens = _collector_usage(
                        collector, self._config
                    )
                    await self._usage_tracker.fail(
                        event_id,
                        AIUsageFailure(
                            error_code=code,
                            request_count=request_count,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            model=model,
                        ),
                    )
                    previous_event_id = event_id
                if attempt + 1 < self._config.max_attempts:
                    await asyncio.sleep(retry_delay_seconds)
            call_trace = trace(code)
            observation.update(model=call_trace.model, request_count=call_trace.request_count)
            observation.usage(call_trace.input_tokens, call_trace.output_tokens)
            observation.fail(code)
            raise PreparationError(
                "Preparation model step failed", code, trace=call_trace
            ) from None


def _retry_instructions(instructions: str, step: str, attempt: int) -> str:
    if attempt == 0:
        return instructions
    return (
        f"{instructions}\n\n"
        "Validation retry: return only a complete response that conforms exactly to the "
        f"declared BAML schema for {step}. Include every required field with valid enum "
        "values and no extra commentary."
    )


def _provider_retry_delay_seconds(error: BaseException, default: float) -> float:
    """Honor a provider retry delay when BAML preserves it in the error message."""
    match = re.search(
        r"(?:retryDelay|retry in|reset after)[^0-9]{0,64}(\d+(?:\.\d+)?)s",
        str(error),
        flags=re.IGNORECASE,
    )
    if match is None:
        return default
    return max(default, min(float(match.group(1)), 60.0))


def _collector_usage(
    collector: Collector, config: PreparationConfig
) -> tuple[str, int, int | None, int | None]:
    log = collector.last
    model = config.model
    if (
        log is not None
        and log.selected_call is not None
        and log.selected_call.client_name == "LocalMarketingFallbackLLM"
        and config.fallback_model is not None
    ):
        model = config.fallback_model
    usage = collector.usage
    return (
        model,
        max(1, len(log.calls)) if log is not None else 1,
        usage.input_tokens,
        usage.output_tokens,
    )
