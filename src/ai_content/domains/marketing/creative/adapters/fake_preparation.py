"""Deterministic M1 drafts for offline workflow tests; no model calls."""

import hashlib
import json
from typing import Literal

from pydantic import TypeAdapter

from ..config.preparation import PreparationConfig
from ..ports.contracts import CreativeWorkItemInput
from ..ports.preparation import (
    BriefDraft,
    BriefReview,
    CompositionDraft,
    IdeaAssessment,
    IdeaCritique,
    IdeaDraft,
    ModelCallTrace,
    ModelStepResult,
    PreparationContext,
    PreparationError,
    RegionDraft,
    TextPlacementDraft,
    VariationBriefDraft,
)


class FakePreparationModel:
    def __init__(self, config: PreparationConfig) -> None:
        self._config = config

    def _trace(
        self,
        step: Literal["ideas", "idea_critique", "brief", "brief_review", "composition"],
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft | None = None,
    ) -> ModelCallTrace:
        prompts = {
            "ideas": self._config.idea_prompt,
            "idea_critique": self._config.idea_critique_prompt,
            "brief": self._config.brief_prompt,
            "brief_review": self._config.brief_review_prompt,
            "composition": self._config.composition_prompt,
        }
        prompt = prompts[step]
        prompt_text = json.dumps(
            {
                "instructions": prompt.text,
                "context": TypeAdapter(PreparationContext).dump_python(context, mode="json"),
                "work_item": TypeAdapter(CreativeWorkItemInput).dump_python(work_item, mode="json"),
                "selected": TypeAdapter(IdeaDraft | None).dump_python(selected, mode="json"),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return ModelCallTrace(
            step=step,
            backend="fake",
            model="synthetic-preparation",
            prompt_version=prompt.version,
            prompt_hash=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
            config_hash=self._config.config_hash,
            elapsed_seconds=0,
            request_count=0,
            prompt_text=prompt_text,
        )

    async def propose(
        self, context: PreparationContext, work_item: CreativeWorkItemInput
    ) -> ModelStepResult[tuple[IdeaDraft, ...]]:
        if not context.personas:
            raise PreparationError("No persona supplied for preparation", "missing_persona")
        persona_id = work_item.persona_override or context.personas[0].persona_id
        evidence = tuple(source.source_id for source in context.sources)
        claim_ids = tuple(claim.claim_id for claim in context.approved_claims[:1])
        reference_ids = tuple(reference.reference_id for reference in context.references[:1])
        candidates = (
            IdeaDraft(
                persona_id=persona_id,
                angle="Make an unfinished room feel considered",
                hook="Give your room a focal point",
                concept="Show the unmodified product in a warm room with clear copy space.",
                rationale="Synthetic test hypothesis based on the supplied persona and brand guide.",
                evidence_refs=evidence,
                claim_ids=claim_ids,
                reference_ids=reference_ids,
            ),
            IdeaDraft(
                persona_id=persona_id,
                angle="Coordinate one focal point with existing furniture",
                hook="A considered detail for your room",
                concept="Show the unmodified product beside complementary furniture in soft light.",
                rationale="Synthetic alternative for testing; no performance conclusion is implied.",
                evidence_refs=evidence,
                claim_ids=claim_ids,
                reference_ids=reference_ids,
            ),
        )
        return ModelStepResult(
            candidates[: self._config.max_ideas], self._trace("ideas", context, work_item)
        )

    async def write_brief(
        self, context: PreparationContext, work_item: CreativeWorkItemInput, selected: IdeaDraft
    ) -> ModelStepResult[BriefDraft]:
        claims = {claim.claim_id: claim for claim in context.approved_claims}
        subtext = " · ".join(claims[claim_id].proof.text for claim_id in selected.claim_ids) or None
        return ModelStepResult(
            BriefDraft(
                heading=selected.hook,
                visual_direction=selected.concept,
                evidence_refs=selected.evidence_refs,
                subtext=subtext,
                claim_ids=selected.claim_ids,
                reference_ids=selected.reference_ids,
                variations=tuple(
                    VariationBriefDraft(
                        variation_key=f"variation-{index:02d}",
                        heading=(
                            selected.hook if index == 1 else f"{selected.hook} — concept {index}"
                        ),
                        visual_direction=(
                            f"{selected.concept} Use a distinct composition concept {index} "
                            "while preserving the exact product."
                        ),
                        evidence_refs=selected.evidence_refs,
                        subtext=subtext,
                        awareness_stage=context.sku.customer_context.target_stage,
                        angle=selected.angle,
                        offer=context.sku.product_metadata.offer,
                        production_level="synthetic-test",
                        claim_ids=selected.claim_ids,
                        reference_ids=selected.reference_ids,
                    )
                    for index in range(1, work_item.variation_count + 1)
                ),
            ),
            self._trace("brief", context, work_item, selected),
        )

    async def critique_ideas(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        candidates: tuple[IdeaDraft, ...],
        eligible_candidate_indices: tuple[int, ...],
    ) -> ModelStepResult[IdeaCritique]:
        selected = eligible_candidate_indices[0] if eligible_candidate_indices else None
        source_ids = {source.source_id for source in context.package.evidence}
        assessments = tuple(
            IdeaAssessment(
                candidate_index=index,
                recommendation=(
                    "select"
                    if index == selected
                    else "keep"
                    if index in eligible_candidate_indices
                    else "reject"
                ),
                rationale="Deterministic strategy evaluation for offline tests.",
                evidence_refs=tuple(ref for ref in candidate.evidence_refs if ref in source_ids),
                concerns=() if index in eligible_candidate_indices else ("ineligible_candidate",),
            )
            for index, candidate in enumerate(candidates, 1)
        )
        evidence_refs = candidates[selected - 1].evidence_refs if selected is not None else ()
        return ModelStepResult(
            IdeaCritique(
                selected_candidate_index=selected,
                rationale="Select the first eligible candidate in the synthetic strategy flow.",
                evidence_refs=evidence_refs,
                assessments=assessments,
            ),
            self._trace("idea_critique", context, work_item),
        )

    async def review_brief(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        draft: BriefDraft,
    ) -> ModelStepResult[BriefReview]:
        return ModelStepResult(
            BriefReview(
                outcome="pass",
                rationale="Synthetic brief is aligned with the selected synthetic idea.",
                evidence_refs=draft.evidence_refs,
            ),
            self._trace("brief_review", context, work_item, selected),
        )

    async def plan_composition(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        brief: BriefDraft,
    ) -> ModelStepResult[CompositionDraft]:
        return ModelStepResult(
            CompositionDraft(
                visual_prompt=(
                    f"{brief.visual_direction} Place the unchanged product on the right, "
                    "leave clean negative space on the left, and render no text or logo."
                ),
                product_region=RegionDraft(500, 100, 450, 800),
                heading=TextPlacementDraft(
                    RegionDraft(60, 140, 380, 260), "left", "#111111", "#FFFFFFCC"
                ),
                subtext=(
                    TextPlacementDraft(
                        RegionDraft(60, 430, 380, 180), "left", "#333333", "#FFFFFFCC"
                    )
                    if brief.subtext
                    else None
                ),
                logo_region=RegionDraft(60, 40, 180, 70),
                rationale="Synthetic composition reserves separate product and copy regions.",
                evidence_refs=brief.evidence_refs,
                product_source_index=0,
                segmentation_prompt="The complete primary product, excluding the background and props.",
            ),
            self._trace("composition", context, work_item, selected),
        )
