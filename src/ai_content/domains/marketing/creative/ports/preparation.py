"""Typed M1 context and model drafts; application owns identities and decisions."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Literal, Protocol, TypeVar

from .contracts import (
    AssetReference,
    ContextPackage,
    CreativeWorkItemInput,
    ProofReference,
    SkuInput,
)


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    data_version: str
    content: str
    category: Literal[
        "product",
        "brand",
        "persona",
        "customer",
        "history",
        "reference",
        "claim",
        "knowledge",
    ] = "reference"
    knowledge_type: str | None = None
    knowledge_authority: str | None = None
    knowledge_scope: tuple[tuple[str, str], ...] = ()
    non_conclusions: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonaOption:
    persona_id: str
    name: str
    description: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonaHypothesis:
    name: str
    description: str
    rationale: str
    evidence_refs: tuple[str, ...]
    uncertainties: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovedReference:
    reference_id: str
    asset: AssetReference
    description: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovedClaim:
    claim_id: str
    proof: ProofReference
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrandProfile:
    profile_id: str
    brand: str
    visual_rules: tuple[str, ...]
    production_rules: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class CreativeStrategySelection:
    strategy_id: str
    persona_id: str
    persona_name: str
    angle: str
    hooks: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    persona_context: tuple[str, ...] = ()
    awareness_stage: str | None = None
    offer: str | None = None
    claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparationContext:
    package: ContextPackage
    sku: SkuInput
    sources: tuple[SourceDocument, ...]
    personas: tuple[PersonaOption, ...]
    references: tuple[ApprovedReference, ...] = ()
    approved_claims: tuple[ApprovedClaim, ...] = ()
    brand_profile: BrandProfile | None = None
    selected_strategy: CreativeStrategySelection | None = None
    warnings: tuple[str, ...] = ()
    pack_version: str = "1"
    pack_hash: str = ""


@dataclass(frozen=True)
class IdeaDraft:
    persona_id: str
    angle: str
    hook: str
    concept: str
    rationale: str
    evidence_refs: tuple[str, ...]
    claim_ids: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class VariationBriefDraft:
    variation_key: str
    heading: str
    visual_direction: str
    evidence_refs: tuple[str, ...]
    subtext: str | None = None
    awareness_stage: str | None = None
    angle: str | None = None
    offer: str | None = None
    production_level: str | None = None
    claim_ids: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BriefDraft:
    heading: str
    visual_direction: str
    evidence_refs: tuple[str, ...]
    subtext: str | None = None
    claim_ids: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()
    variations: tuple[VariationBriefDraft, ...] = ()


@dataclass(frozen=True)
class IdeaAssessment:
    candidate_index: int
    recommendation: Literal["select", "keep", "reject"]
    rationale: str
    evidence_refs: tuple[str, ...]
    concerns: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdeaCritique:
    selected_candidate_index: int | None
    rationale: str
    evidence_refs: tuple[str, ...]
    assessments: tuple[IdeaAssessment, ...]
    uncertainties: tuple[str, ...] = ()


@dataclass(frozen=True)
class BriefReview:
    outcome: Literal["pass", "revise", "blocked"]
    rationale: str
    evidence_refs: tuple[str, ...]
    issues: tuple[str, ...] = ()
    revision_instructions: tuple[str, ...] = ()
    revised_brief: BriefDraft | None = None


@dataclass(frozen=True)
class RegionDraft:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TextPlacementDraft:
    region: RegionDraft
    alignment: Literal["left", "center", "right"]
    text_color: str
    background_color: str | None = None


@dataclass(frozen=True)
class CompositionDraft:
    visual_prompt: str
    product_region: RegionDraft
    heading: TextPlacementDraft
    evidence_refs: tuple[str, ...]
    rationale: str
    subtext: TextPlacementDraft | None = None
    logo_region: RegionDraft | None = None
    product_source_index: int | None = None
    segmentation_prompt: str | None = None


@dataclass(frozen=True)
class ModelCallTrace:
    step: Literal["persona", "ideas", "idea_critique", "brief", "brief_review", "composition"]
    backend: str
    model: str
    prompt_version: str
    prompt_hash: str
    config_hash: str
    elapsed_seconds: float
    request_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: Decimal | None = None
    error_code: str | None = None
    prompt_text: str | None = None


OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class ModelStepResult(Generic[OutputT]):
    output: OutputT
    trace: ModelCallTrace


@dataclass(frozen=True)
class PersonaResolution:
    persona: PersonaOption
    rationale: str
    uncertainties: tuple[str, ...]
    trace: ModelCallTrace


class PreparationError(Exception):
    """Expected preparation failure with safe diagnostics and optional call trace."""

    def __init__(
        self,
        message: str,
        code: str = "preparation_error",
        *,
        trace: ModelCallTrace | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.trace = trace


class IPreparationModel(Protocol):
    async def propose(
        self, context: PreparationContext, work_item: CreativeWorkItemInput
    ) -> ModelStepResult[tuple[IdeaDraft, ...]]: ...

    async def critique_ideas(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        candidates: tuple[IdeaDraft, ...],
        eligible_candidate_indices: tuple[int, ...],
    ) -> ModelStepResult[IdeaCritique]: ...

    async def write_brief(
        self, context: PreparationContext, work_item: CreativeWorkItemInput, selected: IdeaDraft
    ) -> ModelStepResult[BriefDraft]: ...

    async def review_brief(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        draft: BriefDraft,
    ) -> ModelStepResult[BriefReview]: ...

    async def plan_composition(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        brief: BriefDraft,
    ) -> ModelStepResult[CompositionDraft]: ...


class IPersonaResolver(Protocol):
    async def resolve_persona(
        self, context: PreparationContext, work_item: CreativeWorkItemInput
    ) -> ModelStepResult[PersonaHypothesis]: ...
