"""Fixed brief input for supervised image evaluation, with explicit provenance."""

import hashlib

from ..domain.value_objects import GenerationBudget
from ..ports.contracts import (
    ContextPackage,
    CreativeWorkItemInput,
    EvidenceRef,
    IdeaPackage,
    SkuInput,
    StaticCreativeInput,
)
from ..ports.images import ImageGenerationError
from .image_files import INPUT_ADAPTER


class ProvidedBriefContext:
    def __init__(self, brief: StaticCreativeInput) -> None:
        self._brief = brief

    async def collect(self, work_item: CreativeWorkItemInput, sku: SkuInput) -> ContextPackage:
        if len(work_item.target_sku_set) != 1:
            raise ImageGenerationError("Image pilot accepts one SKU per work item")
        if sku.sku_id != self._brief.sku or work_item.marketing_scope.brand != self._brief.brand:
            raise ImageGenerationError("Provided brief does not match work item brand/SKU")
        if self._brief.output_spec != sku.creative_constraints.format_spec:
            raise ImageGenerationError("Provided brief does not match work item output format")
        constraints = sku.creative_constraints
        if not set(constraints.banned_claims).issubset(self._brief.banned_claims):
            raise ImageGenerationError("Provided brief must retain all source SKU banned claims")
        if (
            constraints.brand_guideline_ref is not None
            and self._brief.brand_guideline_ref != constraints.brand_guideline_ref
        ):
            raise ImageGenerationError("Provided brief must retain the source SKU brand guideline")
        return ContextPackage(
            context_id=f"{work_item.source_run_id}:provided-brief",
            source_run_id=work_item.source_run_id,
            sku_id=sku.sku_id,
            brand=work_item.marketing_scope.brand,
            evidence=(
                EvidenceRef(
                    source_id="team-provided-brief",
                    data_version=hashlib.sha256(INPUT_ADAPTER.dump_json(self._brief)).hexdigest(),
                ),
            ),
            historical=sku.historical_creative_context,
            brand_guideline_ref=self._brief.brand_guideline_ref,
        )


class ProvidedBriefIdeas:
    def __init__(self, brief: StaticCreativeInput) -> None:
        self._brief = brief

    async def generate_ideas(
        self, context: ContextPackage, work_item: CreativeWorkItemInput
    ) -> tuple[IdeaPackage, ...]:
        return (
            IdeaPackage(
                idea_id=self._brief.idea_id,
                brand=context.brand,
                sku_id=context.sku_id,
                objective=self._brief.objective,
                market=work_item.marketing_scope.market,
                persona=work_item.persona_override or "team-provided",
                angle="team-provided",
                hook=self._brief.heading,
                concept=self._brief.visual_direction,
                evidence_refs=("team-provided-brief",),
                duration_plan=GenerationBudget(max_retries=0),
            ),
        )
