"""Persistence contract for M1 preparation snapshots, independent of storage technology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.entities import CreativeJob
from .contracts import (
    ContextPackage,
    CreativeWorkItemInput,
    IdeaPackage,
    MarketingCreativeAutomationRequest,
    ProductionRoutingDecision,
    SkuInput,
    StaticCompositionSpec,
    StaticCreativeInput,
)
from .orchestration import CreativeAutomationPlan
from .preparation import (
    BriefReview,
    IdeaCritique,
    ModelCallTrace,
    PersonaResolution,
    PreparationContext,
)


@dataclass(frozen=True)
class CandidateDecision:
    idea_id: str
    eligible: bool
    selected: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StrategyPackage:
    strategy_id: str
    selected_idea_id: str
    critique: IdeaCritique
    brief_reviews: tuple[BriefReview, ...]
    evidence_refs: tuple[str, ...]
    prompt_versions: tuple[str, ...]
    composition: StaticCompositionSpec | None = None
    compositions: tuple[StaticCompositionSpec, ...] = ()
    schema_version: str = "strategy-package@3"


@dataclass(frozen=True)
class CreativeKnowledgeAssignment:
    stage: str
    version_refs: tuple[str, ...]


@dataclass(frozen=True)
class ProductionReadyCreativePackage:
    package_id: str
    request: MarketingCreativeAutomationRequest
    routing: ProductionRoutingDecision
    sku: SkuInput
    context: ContextPackage
    work_item: CreativeWorkItemInput
    selected_idea: IdeaPackage | None = None
    brief: StaticCreativeInput | None = None
    strategy: StrategyPackage | None = None
    automation_plan: CreativeAutomationPlan | None = None
    knowledge_refs: tuple[str, ...] = ()
    knowledge_assignments: tuple[CreativeKnowledgeAssignment, ...] = ()
    persona_resolution: PersonaResolution | None = None
    review_checklist: tuple[str, ...] = ()
    schema_version: str = "production-ready-creative-package@4"


@dataclass(frozen=True)
class PreparedBrief:
    context: PreparationContext
    ideas: tuple[IdeaPackage, ...]
    decisions: tuple[CandidateDecision, ...]
    selected_idea: IdeaPackage
    brief: StaticCreativeInput
    traces: tuple[ModelCallTrace, ...]
    warnings: tuple[str, ...]
    preparation_hash: str
    selection_rule_version: str
    strategy: StrategyPackage | None = None
    schema_version: str = "3"


@dataclass(frozen=True)
class PreparationResult:
    success: bool
    job: CreativeJob
    output: PreparedBrief | None = None
    duplicate: bool = False
    error: str | None = None
    exception_type: str | None = None


class IPreparationRunner(Protocol):
    async def prepare(self, work_item: CreativeWorkItemInput) -> PreparationResult: ...


class IPreparationStore(Protocol):
    def write_snapshot(self, source_run_id: str, name: str, value: object) -> str:
        """Write a typed snapshot and return its storage-relative reference."""
        ...

    def load_brief(self, reference: str) -> PreparedBrief:
        """Read the final immutable preparation artifact."""
        ...
