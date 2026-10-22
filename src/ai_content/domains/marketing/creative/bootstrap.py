"""Composition root for the Static Creative pilot.

Builds the runtime: SQLite repository, filesystem artifact store, selected
adapters and the two use cases. Mode selection lives here, never in domain
or application code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ai_content.platform.ai_usage import AIUsageTracker
from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import (
    refresh_after_decision,
    safe_run_dir,
    write_job_artifacts,
)
from .adapters.fakes import (
    DeterministicQAChecker,
    FakeContextCollector,
    FakeIdeaGenerator,
    FakeImageGenerator,
    SyntheticProductSegmenter,
)
from .adapters.image_files import FileGeneratedImageStore, TechnicalImageChecker
from .adapters.in_memory import FakeApprovalQueue, FakeExceptionQueue
from .adapters.local_context import load_preparation_context
from .adapters.openai_compatible_reviews import BamlSemanticReviewer
from .adapters.pillow_renderer import PillowStaticRenderer
from .adapters.provided_brief import ProvidedBriefContext, ProvidedBriefIdeas
from .adapters.sam3_product_segmenter import Sam3ProductSegmenter
from .adapters.sqlite_repository import SqliteCreativeRepository
from .application.image_generation import StoredImageGenerator
from .application.qa import CompositeCreativeQAChecker, ShadowSemanticCreativeQAChecker
from .application.use_cases import (
    ProcessApproval,
    ProcessResult,
    RunCreativeWorkflow,
)
from .config.images import ImageBackendConfig
from .config.loader import ConfigError, ConfigLoader
from .config.reviewers import SemanticReviewerConfig
from .config.segmentation import ProductSegmenterConfig
from .domain.entities import ApprovalDecision, CreativeJobId
from .image_pilot import build_image_backend
from .ports.contracts import (
    CreativeConstraints,
    CreativeWorkItemInput,
    CustomerContext,
    ExperimentContext,
    HistoricalCreativeContext,
    LeadFeedbackContext,
    MarketingScope,
    OutputSpec,
    PolicyVersion,
    ProductMetadata,
    PromptVersion,
    RubricVersion,
    RuleVersion,
    SkuInput,
    StaticCreativeInput,
    StaticVariationPlan,
    WorkflowVersionRef,
)
from .ports.interfaces import ICreativeRepository
from .ports.preparation import PreparationContext
from .ports.preparation_store import IPreparationRunner

LOCAL_CASE_WORK_ITEM = "work-item.json"
LOCAL_CASE_CONTEXT = "context.json"


class FixtureError(Exception):
    """Invalid or unreadable fixture file."""


def _require(data: dict[str, Any], key: str, context: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise FixtureError(f"Missing required field '{key}' in {context}")
    return data[key]


def _version_pair(data: Any, context: str) -> tuple[str, str]:
    if not isinstance(data, dict) or not data.get("id") or not data.get("version"):
        raise FixtureError(f"Expected {{id, version}} object for {context}")
    return str(data["id"]), str(data["version"])


def _sku_from_dict(data: dict[str, Any]) -> SkuInput:
    sku_id = _require(data, "sku_id", "sku")
    sku_name = _require(data, "sku_name", "sku")
    pm = _require(data, "product_metadata", f"sku {sku_id}")
    image_refs = tuple(str(r) for r in pm.get("image_refs", ()))
    price = None
    if pm.get("price") is not None:
        try:
            price = Decimal(str(pm["price"]))
        except InvalidOperation as e:
            raise FixtureError(f"Invalid price for sku {sku_id}: {pm['price']}") from e

    cc = data.get("creative_constraints", {})
    fmt = cc.get("format_constraints")
    if not isinstance(fmt, dict):
        raise FixtureError(f"Missing format_constraints for sku {sku_id}")
    format_spec = OutputSpec(
        width=int(_require(fmt, "width", f"sku {sku_id} format")),
        height=int(_require(fmt, "height", f"sku {sku_id} format")),
        file_format=str(_require(fmt, "file_format", f"sku {sku_id} format")),
        aspect_ratio=str(fmt["aspect_ratio"]) if fmt.get("aspect_ratio") is not None else None,
    )

    cust = data.get("customer_context", {})
    hist = data.get("historical_creative_context", {})
    lead = data.get("lead_feedback_context")

    return SkuInput(
        sku_id=str(sku_id),
        sku_name=str(sku_name),
        product_metadata=ProductMetadata(
            image_refs=image_refs,
            price=price,
            currency=pm.get("currency"),
            offer=pm.get("offer"),
            differentiators=tuple(str(d) for d in pm.get("differentiators", ())),
        ),
        creative_constraints=CreativeConstraints(
            format_spec=format_spec,
            brand_guideline_ref=cc.get("brand_guideline_ref"),
            banned_claims=tuple(str(c) for c in cc.get("banned_claims", ())),
        ),
        customer_context=CustomerContext(
            pain_points=tuple(str(p) for p in cust.get("pain_points", ())),
            promises=tuple(str(p) for p in cust.get("promises", ())),
            target_stage=cust.get("target_stage"),
        ),
        historical_creative_context=HistoricalCreativeContext(
            tested_angles=tuple(str(a) for a in hist.get("tested_angles", ())),
            performance_notes=hist.get("performance_notes"),
        ),
        lead_feedback_context=LeadFeedbackContext(
            common_issues=tuple(str(i) for i in lead.get("common_issues", ())),
            recent_rejections=tuple(str(r) for r in lead.get("recent_rejections", ())),
        )
        if isinstance(lead, dict)
        else None,
    )


def work_item_from_dict(data: dict[str, Any]) -> CreativeWorkItemInput:
    """Build a typed CreativeWorkItemInput from a parsed fixture dict."""
    scope_data = _require(data, "marketing_scope", "work item")
    scope = MarketingScope(
        brand=str(_require(scope_data, "brand", "marketing_scope")),
        market=str(_require(scope_data, "market", "marketing_scope")),
    )

    rubric_data = _require(data, "rubric_version", "work item")
    rubric_id, rubric_ver = _version_pair(rubric_data, "rubric_version")
    rule_id, rule_ver = _version_pair(_require(data, "rule_version", "work item"), "rule_version")
    prompt_id, prompt_ver = _version_pair(
        _require(data, "prompt_version", "work item"), "prompt_version"
    )
    policy_id, policy_ver = _version_pair(
        _require(data, "policy_version", "work item"), "policy_version"
    )
    workflow_id, workflow_ver = _version_pair(
        _require(data, "workflow_version", "work item"), "workflow_version"
    )

    sku_list = _require(data, "target_sku_set", "work item")
    if not isinstance(sku_list, list) or len(sku_list) == 0:
        raise FixtureError("target_sku_set must be a non-empty list")
    skus = tuple(_sku_from_dict(s) for s in sku_list)

    weight = None
    if data.get("manual_priority_weight") is not None:
        try:
            weight = Decimal(str(data["manual_priority_weight"]))
        except InvalidOperation as e:
            raise FixtureError(
                f"Invalid manual_priority_weight: {data['manual_priority_weight']}"
            ) from e

    experiment = data.get("experiment_context")
    variation_plans = tuple(
        StaticVariationPlan(
            variation_key=str(_require(item, "variation_key", "variation plan")),
            heading=str(_require(item, "heading", "variation plan")),
            subtext=(str(item["subtext"]) if item.get("subtext") is not None else None),
            visual_direction=str(_require(item, "visual_direction", "variation plan")),
            awareness_stage=(
                str(item["awareness_stage"]) if item.get("awareness_stage") is not None else None
            ),
            angle=str(item["angle"]) if item.get("angle") is not None else None,
            offer=str(item["offer"]) if item.get("offer") is not None else None,
            production_level=(
                str(item["production_level"]) if item.get("production_level") is not None else None
            ),
            evidence_refs=tuple(str(ref) for ref in item.get("evidence_refs", ())),
        )
        for item in data.get("variation_plans", ())
    )
    return CreativeWorkItemInput(
        source_run_id=str(_require(data, "source_run_id", "work item")),
        marketing_scope=scope,
        objective=str(_require(data, "objective", "work item")),
        channel=str(_require(data, "channel", "work item")),
        time_window=str(_require(data, "time_window", "work item")),
        target_sku_set=skus,
        rubric_version=RubricVersion(
            rubric_id=rubric_id,
            version=rubric_ver,
            is_draft=bool(rubric_data.get("is_draft", True)),
        ),
        rule_version=RuleVersion(rule_id=rule_id, version=rule_ver),
        prompt_version=PromptVersion(prompt_id=prompt_id, version=prompt_ver),
        policy_version=PolicyVersion(policy_id=policy_id, version=policy_ver),
        workflow_version=WorkflowVersionRef(
            workflow_id=workflow_id,
            version=workflow_ver,
        ),
        persona_override=data.get("persona_override"),
        creative_direction_override=data.get("creative_direction_override"),
        campaign_notes=data.get("campaign_notes"),
        manual_priority_weight=weight,
        experiment_context=(
            ExperimentContext(
                source_decision_ref=str(
                    _require(experiment, "source_decision_ref", "experiment_context")
                ),
                category=str(_require(experiment, "category", "experiment_context")),
                priority=int(_require(experiment, "priority", "experiment_context")),
                hypothesis=str(_require(experiment, "hypothesis", "experiment_context")),
                experiment=str(_require(experiment, "experiment", "experiment_context")),
                success_signal=str(_require(experiment, "success_signal", "experiment_context")),
                evidence_refs=tuple(str(ref) for ref in experiment.get("evidence_refs", ())),
                uncertainty=str(experiment.get("uncertainty", "")),
            )
            if isinstance(experiment, dict)
            else None
        ),
        variation_count=int(data.get("variation_count", 1)),
        variation_plans=variation_plans,
        requested_image_count=int(data.get("requested_image_count", 1)),
        requested_video_count=int(data.get("requested_video_count", 0)),
        created_by=str(data.get("created_by", "system")),
        created_at=(
            datetime.fromisoformat(str(data["created_at"]))
            if data.get("created_at") is not None
            else datetime.now(UTC)
        ),
    )


def load_work_item(path: Path) -> CreativeWorkItemInput:
    """Load and validate a work item fixture file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise FixtureError(f"Cannot read fixture {path}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FixtureError(f"Invalid JSON in fixture {path}: {e}") from e
    if not isinstance(data, dict):
        raise FixtureError(f"Fixture {path} must be a JSON object")
    try:
        return work_item_from_dict(data)
    except (KeyError, TypeError, ValueError) as e:
        raise FixtureError(f"Invalid fixture {path}: {e}") from e


@dataclass(frozen=True)
class LocalPreparationCase:
    """Resolved work item and context loaded from local case files."""

    work_item: CreativeWorkItemInput
    context: PreparationContext


def load_preparation_case(
    work_item_path: Path,
    context_path: Path,
    *,
    max_context_bytes: int,
) -> LocalPreparationCase:
    """Load one local M1 case without reading or fetching referenced assets."""
    work_item = load_work_item(work_item_path)
    work_item = replace(
        work_item,
        target_sku_set=tuple(
            replace(
                sku,
                product_metadata=replace(
                    sku.product_metadata,
                    image_refs=tuple(
                        ref
                        if "://" in ref
                        else str((work_item_path.resolve().parent / ref).resolve())
                        for ref in sku.product_metadata.image_refs
                    ),
                ),
            )
            for sku in work_item.target_sku_set
        ),
    )
    context = load_preparation_context(
        context_path,
        work_item,
        max_bytes=max_context_bytes,
    )
    return LocalPreparationCase(work_item=work_item, context=context)


def load_preparation_case_dir(
    case_dir: Path,
    *,
    max_context_bytes: int,
) -> LocalPreparationCase:
    """Load the conventional work-item.json and context.json from one directory."""
    if not case_dir.is_dir():
        raise FixtureError(f"Local preparation case directory does not exist: {case_dir}")
    return load_preparation_case(
        case_dir / LOCAL_CASE_WORK_ITEM,
        case_dir / LOCAL_CASE_CONTEXT,
        max_context_bytes=max_context_bytes,
    )


@dataclass
class RunOutcome:
    """Run/replay outcome plus the manifest path when artifacts were written."""

    result: ProcessResult
    manifest_path: Path | None = None


class CreativeRuntime:
    """Thin pilot harness facade: run, decide, inspect, replay."""

    def __init__(
        self,
        repository: ICreativeRepository,
        artifact_store: ArtifactStore,
        config_loader: ConfigLoader,
        run_workflow: RunCreativeWorkflow,
        process_approval: ProcessApproval,
        image_brief: StaticCreativeInput | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.config_loader = config_loader
        self.run_workflow = run_workflow
        self.process_approval = process_approval
        self.image_brief = image_brief

    async def run(self, work_item: CreativeWorkItemInput) -> RunOutcome:
        """Execute the workflow and write the artifact tree."""
        try:
            self.config_loader.validate_work_item_versions(
                prompt_id=work_item.prompt_version.prompt_id,
                prompt_version=work_item.prompt_version.version,
                rubric_id=work_item.rubric_version.rubric_id,
                rubric_version=work_item.rubric_version.version,
                policy_id=work_item.policy_version.policy_id,
                policy_version=work_item.policy_version.version,
                rule_id=work_item.rule_version.rule_id,
                rule_version=work_item.rule_version.version,
                workflow_id=work_item.workflow_version.workflow_id,
                workflow_version=work_item.workflow_version.version,
            )
        except ConfigError as e:
            raise FixtureError(f"Config resolution failed: {e}") from e

        if self.image_brief is not None:
            brief = self.image_brief
            if (
                brief.prompt_version != work_item.prompt_version
                or brief.rubric_version != work_item.rubric_version
                or brief.policy_version != work_item.policy_version
                or brief.objective != work_item.objective
            ):
                raise FixtureError("Brief objective/config versions must match the work item")
        result = await self.run_workflow.execute(work_item, generation_input=self.image_brief)
        if result.job is None or result.duplicate:
            return RunOutcome(result=result)
        manifest_path = write_job_artifacts(
            self.artifact_store,
            result.job,
            work_item,
            result.context,
            result.ideas,
        )
        return RunOutcome(result=result, manifest_path=manifest_path)

    async def decide(
        self,
        job_id: str,
        decision: ApprovalDecision,
        reviewer: str,
        reason: str | None = None,
    ) -> RunOutcome:
        """Apply an approval decision and refresh manifest/card artifacts."""
        result = await self.process_approval.execute(
            CreativeJobId.from_string(job_id),
            decision,
            reviewer,
            reason,
        )
        manifest_path = None
        if result.success and result.job is not None:
            manifest_path = refresh_after_decision(self.artifact_store, result.job)
        return RunOutcome(result=result, manifest_path=manifest_path)

    def run_dir(self, source_run_id: str) -> Path:
        return self.artifact_store.path(safe_run_dir(source_run_id))


def build_runtime(
    db_path: Path | None,
    artifacts_root: Path,
    config_dir: Path = Path("config"),
    *,
    image_config: ImageBackendConfig | None = None,
    image_api_key: str | None = None,
    image_brief: StaticCreativeInput | None = None,
    reviewer_config: SemanticReviewerConfig | None = None,
    reviewer_api_key: str | None = None,
    product_segmenter_config: ProductSegmenterConfig | None = None,
    product_segmenter_runpod_endpoint_id: str | None = None,
    product_segmenter_runpod_api_key: str | None = None,
    seed: int = 0,
    preparation: IPreparationRunner | None = None,
    repository: ICreativeRepository | None = None,
    usage_tracker: AIUsageTracker | None = None,
) -> CreativeRuntime:
    """Compose fake workflow or supervised fixed-brief image workflow."""
    if image_brief is not None and image_config is None:
        raise FixtureError("A fixed image brief requires image_config")
    if preparation is not None and image_brief is not None:
        raise FixtureError("Choose preparation or a fixed image brief, not both")
    if repository is None:
        if db_path is None:
            raise ValueError("db_path is required when no repository is provided")
        repository = SqliteCreativeRepository(db_path)
    store = ArtifactStore(artifacts_root)
    config_loader = ConfigLoader(config_dir)
    approval_queue = FakeApprovalQueue()
    technical_checker = (
        TechnicalImageChecker(image_config.max_image_bytes)
        if image_config
        else DeterministicQAChecker()
    )
    if reviewer_config is not None:
        if image_config is None:
            raise FixtureError("Semantic review requires an image configuration")
        reviewer = BamlSemanticReviewer(
            reviewer_config,
            api_key=reviewer_api_key,
            usage_tracker=usage_tracker,
        )
        qa_checker = (
            ShadowSemanticCreativeQAChecker(technical_checker, reviewer)
            if reviewer_config.mode == "shadow"
            else CompositeCreativeQAChecker(technical_checker, reviewer)
        )
    else:
        qa_checker = technical_checker
    run_workflow = RunCreativeWorkflow(
        context_collector=ProvidedBriefContext(image_brief)
        if image_brief
        else FakeContextCollector(),
        idea_generator=ProvidedBriefIdeas(image_brief) if image_brief else FakeIdeaGenerator(),
        generator=StoredImageGenerator(
            build_image_backend(image_config, image_api_key),
            FileGeneratedImageStore(store, image_config.max_image_bytes),
            seed,
            usage_tracker=(usage_tracker if image_config.backend != "synthetic" else None),
            backend_name=image_config.backend,
            model=image_config.model,
            model_revision=image_config.model_revision,
            renderer=PillowStaticRenderer(),
            product_segmenter=(
                Sam3ProductSegmenter(
                    product_segmenter_config,
                    runpod_endpoint_id=product_segmenter_runpod_endpoint_id,
                    runpod_api_key=product_segmenter_runpod_api_key,
                )
                if product_segmenter_config is not None
                else (SyntheticProductSegmenter() if image_config.backend == "synthetic" else None)
            ),
        )
        if image_config
        else FakeImageGenerator(),
        qa_checker=qa_checker,
        repository=repository,
        approval_queue=approval_queue,
        exception_queue=FakeExceptionQueue(),
        preparation=preparation,
    )
    process_approval = ProcessApproval(
        repository=repository,
        approval_queue=approval_queue,
    )
    return CreativeRuntime(
        repository=repository,
        artifact_store=store,
        config_loader=config_loader,
        run_workflow=run_workflow,
        process_approval=process_approval,
        image_brief=image_brief,
    )


__all__ = [
    "CreativeRuntime",
    "FixtureError",
    "LocalPreparationCase",
    "RunOutcome",
    "build_runtime",
    "load_preparation_case",
    "load_preparation_case_dir",
    "load_work_item",
    "work_item_from_dict",
]
