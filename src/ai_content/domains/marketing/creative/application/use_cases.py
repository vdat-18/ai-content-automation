"""Use cases for Creative subdomain.

These orchestrate the domain logic with external dependencies via ports.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal

from ai_content.platform.observability import observe_ai_call

from ..domain.entities import (
    ApprovalCard,
    ApprovalDecision,
    AssetVersion,
    CreativeJob,
    CreativeJobId,
    CreativeJobStatus,
    QACheckResult,
    QASession,
    VersionId,
)
from ..domain.services import GenerationPolicyValidator
from ..domain.value_objects import GenerationBudget
from ..ports import (
    IApprovalQueue,
    IContextCollector,
    ICreativeRepository,
    IExceptionQueue,
    IIdeaGenerator,
    IImageGenerator,
    IQAChecker,
)
from ..ports.contracts import (
    ContextPackage,
    CreativeWorkItemInput,
    IdeaPackage,
    ProductAsset,
    ProvenanceSource,
    RevisionRequest,
    SkuInput,
    StaticCreativeInput,
)
from ..ports.preparation_store import IPreparationRunner
from .revision import PlanCreativeRevision, RevisionPlanningError


@dataclass
class ProcessResult:
    """Result of processing a creative job."""

    success: bool
    job: CreativeJob | None = None
    error: str | None = None
    exception_type: str | None = None
    duplicate: bool = False
    context: ContextPackage | None = None
    ideas: tuple[IdeaPackage, ...] | None = None


def validate_work_item(work_item: CreativeWorkItemInput) -> tuple[str, ...]:
    """Check hard input requirements beyond dataclass shape validation."""
    errors = []
    for sku in work_item.target_sku_set:
        if len(sku.product_metadata.image_refs) == 0:
            errors.append(f"SKU {sku.sku_id} has no product image refs")
    return tuple(errors)


def build_generation_input(
    work_item: CreativeWorkItemInput,
    sku: SkuInput,
    idea: IdeaPackage,
) -> StaticCreativeInput:
    """Derive the generation contract from the selected idea plus SKU data."""
    return StaticCreativeInput(
        brand=work_item.marketing_scope.brand,
        sku=sku.sku_id,
        objective=work_item.objective,
        idea_id=idea.idea_id,
        heading=idea.hook,
        visual_direction=(
            work_item.creative_direction_override
            if work_item.creative_direction_override is not None
            else idea.concept
        ),
        product_assets=tuple(
            ProductAsset(
                url=ref,
                asset_type="product",
                provenance=ProvenanceSource.SOURCE_OF_TRUTH,
            )
            for ref in sku.product_metadata.image_refs
        ),
        output_spec=sku.creative_constraints.format_spec,
        prompt_version=work_item.prompt_version,
        rubric_version=work_item.rubric_version,
        policy_version=work_item.policy_version,
        created_by=work_item.created_by,
        brand_guideline_ref=sku.creative_constraints.brand_guideline_ref,
        banned_claims=sku.creative_constraints.banned_claims,
        variation_plans=work_item.variation_plans,
    )


def build_generation_inputs(
    work_item: CreativeWorkItemInput,
    sku: SkuInput,
    idea: IdeaPackage,
    base_input: StaticCreativeInput | None = None,
) -> tuple[StaticCreativeInput, ...]:
    """Build one stable creative set from the selected idea and approved brief."""
    source = base_input or build_generation_input(work_item, sku, idea)
    set_seed = f"{work_item.source_run_id}:{idea.idea_id}"
    creative_set_id = f"set_{hashlib.sha256(set_seed.encode()).hexdigest()[:12]}"
    plans = source.variation_plans or work_item.variation_plans
    if work_item.variation_count > 1 and len(plans) != work_item.variation_count:
        raise ValueError(
            "Static Creative Sets require one explicit variation plan per requested variation"
        )
    inputs = []
    for index in range(1, work_item.variation_count + 1):
        variation_id = f"{creative_set_id}_var_{index:02d}"
        plan = plans[index - 1] if plans else None
        inputs.append(
            replace(
                source,
                creative_set_id=creative_set_id,
                variation_id=variation_id,
                variation_key=plan.variation_key if plan else source.variation_key,
                variation_evidence_refs=(
                    plan.evidence_refs if plan else source.variation_evidence_refs
                ),
                heading=plan.heading if plan else source.heading,
                subtext=plan.subtext if plan else source.subtext,
                visual_direction=plan.visual_direction if plan else source.visual_direction,
                awareness_stage=plan.awareness_stage if plan else source.awareness_stage,
                angle=plan.angle if plan else source.angle,
                offer=plan.offer if plan else source.offer,
                production_level=plan.production_level if plan else source.production_level,
                composition=plan.composition if plan else source.composition,
                variation_plans=(),
            )
        )
    return tuple(inputs)


def compute_input_hash(
    input_data: StaticCreativeInput,
    revision: RevisionRequest | None = None,
) -> str:
    """Deterministic hash over the stable fields of the generation input.

    Volatile fields (created_at, created_by) are excluded so the same
    business input yields the same hash across runs and replays.
    """
    stable = {
        "brand": input_data.brand,
        "sku": input_data.sku,
        "objective": input_data.objective,
        "idea_id": input_data.idea_id,
        "heading": input_data.heading,
        "visual_direction": input_data.visual_direction,
        "subtext": input_data.subtext,
        "product_assets": [
            {
                "url": asset.url,
                "asset_type": asset.asset_type,
                "provenance": asset.provenance.value,
            }
            for asset in input_data.product_assets
        ],
        "reference_assets": [
            {
                "url": ref.url,
                "provenance": ref.provenance.value,
                "license_info": ref.license_info,
                "expires_at": ref.expires_at,
            }
            for ref in input_data.reference_assets
        ],
        "proof_references": [
            {
                "proof_type": ref.proof_type.value,
                "text": ref.text,
                "source_url": ref.source_url,
                "verified": ref.verified,
            }
            for ref in input_data.proof_references
        ],
        "output_spec": {
            "width": input_data.output_spec.width,
            "height": input_data.output_spec.height,
            "file_format": input_data.output_spec.file_format,
            "aspect_ratio": input_data.output_spec.aspect_ratio,
        },
        "prompt_version": str(input_data.prompt_version),
        "rubric_version": str(input_data.rubric_version),
        "policy_version": str(input_data.policy_version),
        "brand_guideline_ref": input_data.brand_guideline_ref,
        "banned_claims": list(input_data.banned_claims),
        "creative_set_id": input_data.creative_set_id,
        "variation_id": input_data.variation_id,
        "variation_key": input_data.variation_key,
        "variation_evidence_refs": input_data.variation_evidence_refs,
        "awareness_stage": input_data.awareness_stage,
        "angle": input_data.angle,
        "offer": input_data.offer,
        "production_level": input_data.production_level,
        "variation_plans": [
            {
                "variation_key": plan.variation_key,
                "heading": plan.heading,
                "subtext": plan.subtext,
                "visual_direction": plan.visual_direction,
                "awareness_stage": plan.awareness_stage,
                "angle": plan.angle,
                "offer": plan.offer,
                "production_level": plan.production_level,
                "evidence_refs": plan.evidence_refs,
                "composition": asdict(plan.composition) if plan.composition else None,
            }
            for plan in input_data.variation_plans
        ],
        "logo_asset": (
            {
                "url": input_data.logo_asset.url,
                "provenance": input_data.logo_asset.provenance.value,
                "license_info": input_data.logo_asset.license_info,
                "expires_at": input_data.logo_asset.expires_at,
            }
            if input_data.logo_asset
            else None
        ),
        "composition": (
            {
                "composition_id": input_data.composition.composition_id,
                "version": input_data.composition.version,
                "visual_prompt": input_data.composition.visual_prompt,
                "product_region": vars(input_data.composition.product_region),
                "heading": {
                    "region": vars(input_data.composition.heading.region),
                    "alignment": input_data.composition.heading.alignment,
                    "text_color": input_data.composition.heading.text_color,
                    "background_color": input_data.composition.heading.background_color,
                },
                "subtext": (
                    {
                        "region": vars(input_data.composition.subtext.region),
                        "alignment": input_data.composition.subtext.alignment,
                        "text_color": input_data.composition.subtext.text_color,
                        "background_color": input_data.composition.subtext.background_color,
                    }
                    if input_data.composition.subtext
                    else None
                ),
                "logo_region": (
                    vars(input_data.composition.logo_region)
                    if input_data.composition.logo_region
                    else None
                ),
                "product_preservation": (
                    vars(input_data.composition.product_preservation)
                    if input_data.composition.product_preservation
                    else None
                ),
                "evidence_refs": list(input_data.composition.evidence_refs),
                "rationale": input_data.composition.rationale,
            }
            if input_data.composition
            else None
        ),
        "revision": asdict(revision) if revision else None,
    }
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunCreativeWorkflow:
    """Use case: closed-loop static creative workflow (M1 + M2 + X1).

    Process:
    1. Idempotency check by source_run_id (same trigger never creates 2 jobs)
    2. VALIDATING: verify hard input fields
    3. COLLECTING_CONTEXT: gather typed context with evidence refs
    4. IDEA_GENERATING: create candidate idea packages
    5. IDEA_REVIEW: select the highest-confidence idea
    6. GENERATING -> QA_CHECKING loop; failed QA produces a RevisionRequest
       carrying the previous version's issues/feedback into the next attempt
    7. QA pass -> AWAITING_APPROVAL with an ApprovalCard on the passing version
    8. Operational failures -> EXCEPTION_OPERATIONAL; policy violations found
       by QA -> EXCEPTION_POLICY; both create exception queue entries

    The walking skeleton processes the first SKU of the work item; multi-SKU
    scheduling is out of pilot scope.
    """

    def __init__(
        self,
        context_collector: IContextCollector,
        idea_generator: IIdeaGenerator,
        generator: IImageGenerator,
        qa_checker: IQAChecker,
        repository: ICreativeRepository,
        approval_queue: IApprovalQueue,
        exception_queue: IExceptionQueue,
        default_budget: GenerationBudget | None = None,
        preparation: IPreparationRunner | None = None,
        revision_planner: PlanCreativeRevision | None = None,
    ) -> None:
        self._context_collector = context_collector
        self._idea_generator = idea_generator
        self._generator = generator
        self._qa_checker = qa_checker
        self._repository = repository
        self._approval_queue = approval_queue
        self._exception_queue = exception_queue
        self._default_budget = default_budget or GenerationBudget()
        self._preparation = preparation
        self._revision_planner = revision_planner or PlanCreativeRevision()

    async def execute(
        self,
        work_item: CreativeWorkItemInput,
        budget: GenerationBudget | None = None,
        generation_input: StaticCreativeInput | None = None,
    ) -> ProcessResult:
        """Execute the workflow for one work item."""
        existing = await self._repository.get_job_by_source_run_id(work_item.source_run_id)
        if existing is not None:
            if self._preparation is not None:
                prepared = await self._preparation.prepare(work_item)
                if not prepared.success:
                    return ProcessResult(
                        success=False,
                        job=prepared.job,
                        duplicate=True,
                        error=prepared.error,
                        exception_type=prepared.exception_type,
                    )
                current = prepared.job
                if current.status == CreativeJobStatus.BRIEF_READY:
                    if prepared.output is None:
                        return ProcessResult(
                            success=False,
                            job=current,
                            duplicate=True,
                            error="Prepared brief artifact is missing",
                            exception_type="preparation_artifact_error",
                        )
                    output = prepared.output
                    return await self._generate(
                        work_item,
                        current,
                        output.context.sku,
                        output.context.package,
                        output.ideas,
                        output.selected_idea,
                        output.brief,
                        budget,
                    )
                existing = current
            completed_states = {
                CreativeJobStatus.AWAITING_APPROVAL,
                CreativeJobStatus.APPROVED,
                CreativeJobStatus.REJECTED,
                CreativeJobStatus.ARCHIVED,
            }
            success = existing.status in completed_states
            return ProcessResult(
                success=success,
                job=existing,
                error=None if success else f"Existing job is in {existing.status.value}",
                exception_type=None if success else "existing_job_not_resumable",
                duplicate=True,
            )

        if self._preparation is not None:
            prepared = await self._preparation.prepare(work_item)
            if not prepared.success or prepared.output is None or prepared.duplicate:
                return ProcessResult(
                    success=False,
                    job=prepared.job,
                    error=prepared.error,
                    exception_type=prepared.exception_type or "existing_job_not_resumable",
                    duplicate=prepared.duplicate,
                )
            output = prepared.output
            return await self._generate(
                work_item,
                prepared.job,
                output.context.sku,
                output.context.package,
                output.ideas,
                output.selected_idea,
                output.brief,
                budget,
            )

        job = CreativeJob(
            job_id=CreativeJobId.generate(),
            status=CreativeJobStatus.PENDING,
            source_run_id=work_item.source_run_id,
        )
        job.add_audit(
            "job_created",
            work_item.created_by,
            {"source_run_id": work_item.source_run_id},
        )
        job.record_lineage(
            "work_item",
            work_item.source_run_id,
            details={"input_type": "creative_work_item"},
        )
        await self._repository.save_job(job)

        # --- VALIDATING ---
        job.transition_to(CreativeJobStatus.VALIDATING)
        await self._repository.save_job(job)

        errors = validate_work_item(work_item)
        if errors:
            return await self._fail(
                job,
                exception_type="missing_hard_input",
                error_message="Hard input validation failed: " + "; ".join(errors),
                suggested_action="Fix source data or complete the input contract",
            )

        # --- COLLECTING_CONTEXT ---
        job.transition_to(CreativeJobStatus.COLLECTING_CONTEXT)
        await self._repository.save_job(job)

        sku = work_item.target_sku_set[0]
        try:
            context = await self._context_collector.collect(work_item, sku)
        except Exception as e:
            return await self._fail(
                job,
                exception_type="context_error",
                error_message=f"Context collection failed: {e}",
                suggested_action="Check source availability, schema and access rights",
            )

        job.context_ref = context.context_id
        job.record_lineage(
            "context",
            context.context_id,
            work_item.source_run_id,
            {
                "sku_id": context.sku_id,
                "evidence_refs": [e.source_id for e in context.evidence],
            },
        )
        await self._repository.save_job(job)

        # --- IDEA_GENERATING ---
        job.transition_to(CreativeJobStatus.IDEA_GENERATING)
        await self._repository.save_job(job)

        try:
            ideas = await self._idea_generator.generate_ideas(context, work_item)
        except Exception as e:
            return await self._fail(
                job,
                exception_type="idea_error",
                error_message=f"Idea generation failed: {e}",
                suggested_action="Check idea adapter and context package",
            )

        if len(ideas) == 0:
            return await self._fail(
                job,
                exception_type="no_ideas",
                error_message="Idea generator returned no ideas",
                suggested_action="Review context evidence and idea rules",
            )

        # --- IDEA_REVIEW ---
        job.transition_to(CreativeJobStatus.IDEA_REVIEW)
        await self._repository.save_job(job)

        eligible_ideas = tuple(
            idea
            for idea in ideas
            if all(check.passed for check in idea.fidelity_checks) and not idea.risk_flags
        )
        if not eligible_ideas:
            return await self._fail(
                job,
                exception_type="no_eligible_ideas",
                error_message="All generated ideas failed fidelity checks or contain risk flags",
                suggested_action="Review idea evidence, fidelity failures and risk flags",
            )

        selected = max(eligible_ideas, key=lambda idea: idea.confidence)
        job.idea_id = selected.idea_id
        job.record_lineage(
            "idea_selected",
            selected.idea_id,
            context.context_id,
            {
                "angle": selected.angle,
                "persona": selected.persona,
                "confidence": str(selected.confidence),
            },
        )
        await self._repository.save_job(job)

        gen_input = generation_input or build_generation_input(work_item, sku, selected)
        if (
            gen_input.sku != sku.sku_id
            or gen_input.brand != work_item.marketing_scope.brand
            or gen_input.idea_id != selected.idea_id
        ):
            return await self._fail(
                job,
                exception_type="generation_input_mismatch",
                error_message="Generation input does not match selected idea and SKU",
                suggested_action="Align the supplied brief with this work item",
            )
        return await self._generate(
            work_item, job, sku, context, ideas, selected, gen_input, budget
        )

    async def _generate(
        self,
        work_item: CreativeWorkItemInput,
        job: CreativeJob,
        sku: SkuInput,
        context: ContextPackage,
        ideas: tuple[IdeaPackage, ...],
        selected: IdeaPackage,
        gen_input: StaticCreativeInput,
        budget: GenerationBudget | None,
    ) -> ProcessResult:
        generation_inputs = build_generation_inputs(work_item, sku, selected, gen_input)
        creative_set_id = generation_inputs[0].creative_set_id
        if creative_set_id is None:
            raise RuntimeError("Creative set ID was not assigned")
        job.creative_set_id = creative_set_id
        job.record_lineage(
            "creative_set",
            creative_set_id,
            selected.idea_id,
            {"variation_count": len(generation_inputs)},
        )
        await self._repository.save_job(job)
        effective_budget = budget or selected.duration_plan or self._default_budget
        input_by_variation = {
            input_data.variation_id: input_data
            for input_data in generation_inputs
            if input_data.variation_id is not None
        }
        pending: dict[str, RevisionRequest | None] = dict.fromkeys(input_by_variation)
        retry_counts = dict.fromkeys(input_by_variation, 0)
        passing: dict[str, AssetVersion] = {}
        next_version_number = len(job.versions) + 1

        while pending:
            job.transition_to(CreativeJobStatus.GENERATING)
            generated: dict[str, AssetVersion] = {}
            await self._repository.save_job(job)
            for variation_id, revision in pending.items():
                input_data = input_by_variation[variation_id]
                current_cost = job.total_cost.amount if job.total_cost else Decimal("0")
                if not effective_budget.allows_generation(current_cost):
                    return await self._fail(
                        job,
                        exception_type="budget_exceeded",
                        error_message=(
                            "Budget exceeded before generation "
                            f"(current: {current_cost}, limit: {effective_budget.max_cost})"
                        ),
                        suggested_action="Increase budget or reduce scope",
                    )
                version_id = VersionId(job.job_id, next_version_number)
                next_version_number += 1
                try:
                    version = await self._generator.generate(input_data, version_id, revision)
                except Exception as e:
                    return await self._fail(
                        job,
                        exception_type="generation_error",
                        error_message=f"Generation failed: {e}",
                        suggested_action="Check generator adapter and input data",
                    )
                input_hash = compute_input_hash(input_data, revision)
                version = replace(
                    version.with_version_metadata(
                        input_hash=input_hash,
                        prompt_version=str(input_data.prompt_version),
                        rubric_version=str(input_data.rubric_version),
                        policy_version=str(input_data.policy_version),
                        workflow_version=str(work_item.workflow_version),
                    ),
                    creative_set_id=creative_set_id,
                    variation_id=variation_id,
                    variation_attempt_number=retry_counts[variation_id] + 1,
                )
                generated[variation_id] = version
                job.add_version(version)
                job.record_lineage(
                    "version",
                    version_id.value,
                    variation_id,
                    {
                        "creative_set_id": creative_set_id,
                        "input_hash": input_hash,
                        "generator_version": version.generator_version or "unknown",
                        "variation_attempt": retry_counts[variation_id] + 1,
                        "revision_of": revision.previous_version_ref if revision else None,
                        "revision_issues": list(revision.issues) if revision else [],
                        "revision_instructions": list(revision.instructions) if revision else [],
                        "failed_criteria": list(revision.failed_criteria) if revision else [],
                        "repair_actions": (
                            [item.value for item in revision.repair_actions] if revision else []
                        ),
                        "review_evidence_refs": (list(revision.evidence_refs) if revision else []),
                    },
                )
                await self._repository.save_version(version)
                await self._repository.save_job(job)
                current_cost = job.total_cost.amount if job.total_cost else Decimal("0")
                if effective_budget.is_cost_exceeded(current_cost):
                    return await self._fail(
                        job,
                        exception_type="budget_exceeded",
                        error_message=(
                            "Budget exceeded after generation "
                            f"(current: {current_cost}, limit: {effective_budget.max_cost})"
                        ),
                        suggested_action="Review the generated attempt before increasing budget",
                    )

            job.transition_to(CreativeJobStatus.QA_CHECKING)
            await self._repository.save_job(job)
            failed: dict[str, RevisionRequest] = {}
            for variation_id, raw_version in generated.items():
                input_data = input_by_variation[variation_id]
                version = raw_version
                qa_session = QASession(
                    asset=version,
                    input_contract=input_data,
                    rubric_version=str(input_data.rubric_version),
                    policy_version=str(input_data.policy_version),
                )
                try:
                    qa_result = await self._qa_checker.check(qa_session)
                except Exception as e:
                    return await self._fail(
                        job,
                        exception_type="qa_error",
                        error_message=f"QA check failed: {e}",
                        suggested_action="Check QA adapter availability, schema and timeout",
                    )
                version = version.with_qa_result(
                    passed=qa_result.passed,
                    score=qa_result.score,
                    issues=qa_result.issues,
                    feedback=qa_result.feedback,
                    warnings=qa_result.warnings,
                    outcome=qa_result.outcome,
                    retryable=qa_result.retryable,
                    requires_human_review=qa_result.requires_human_review,
                    repair_actions=qa_result.repair_actions,
                    evidence_refs=qa_result.evidence_refs,
                    reviewer_version=qa_result.reviewer_version,
                    criteria=qa_result.criteria,
                    semantic_issues=qa_result.semantic_issues,
                    evidence=qa_result.evidence,
                )
                job.replace_version(version)
                generated[variation_id] = version
                job.record_lineage(
                    "qa",
                    f"{version.version_id.value}:qa:{input_data.rubric_version}",
                    version.version_id.value,
                    {
                        "passed": qa_result.passed,
                        "score": str(qa_result.score),
                        "variation_id": variation_id,
                        "rubric_version": str(input_data.rubric_version),
                        "policy_violations": list(qa_result.policy_violations),
                        "outcome": qa_result.outcome.value if qa_result.outcome else None,
                        "retryable": qa_result.retryable,
                        "requires_human_review": qa_result.requires_human_review,
                        "repair_actions": [item.value for item in qa_result.repair_actions],
                        "evidence_refs": list(qa_result.evidence_refs),
                        "reviewer_version": qa_result.reviewer_version,
                    },
                )
                await self._repository.save_version(version)
                if qa_result.policy_violations:
                    return await self._fail(
                        job,
                        exception_type="policy_violation",
                        error_message=(
                            "Policy violations: " + ", ".join(qa_result.policy_violations)
                        ),
                        suggested_action="Escalate to policy owner for review",
                        policy=True,
                    )
                if qa_result.requires_human_review or (
                    not qa_result.passed and not qa_result.retryable
                ):
                    reason = ", ".join(qa_result.issues) or "unknown reason"
                    return await self._fail(
                        job,
                        exception_type="qa_requires_human_review",
                        error_message=(
                            "QA could not safely approve or revise variation "
                            f"{variation_id}: {reason}"
                        ),
                        suggested_action="Review the exact asset version and QA evidence",
                    )
                if qa_result.passed:
                    passing[variation_id] = version
                else:
                    try:
                        failed[variation_id] = self._revision_planner.plan(version, qa_result, sku)
                    except RevisionPlanningError as error:
                        return await self._fail(
                            job,
                            exception_type=error.code,
                            error_message=(
                                f"Cannot safely revise variation {variation_id}: {error}"
                            ),
                            suggested_action="Review the exact asset version and QA evidence",
                        )

            set_issues = (
                self._creative_set_issues(passing, len(generation_inputs)) if not failed else {}
            )
            job.record_lineage(
                "set_qa",
                f"{creative_set_id}:qa:{len(job.versions)}",
                creative_set_id,
                {
                    "passed": not failed and not set_issues,
                    "variation_count": len(passing),
                    "issues": set_issues,
                },
            )
            for variation_id, issue in set_issues.items():
                version = passing.pop(variation_id)
                version = version.with_qa_result(
                    passed=False,
                    score=version.qa_score or Decimal("0"),
                    issues=(issue,),
                    feedback=issue,
                    warnings=version.qa_warnings,
                )
                job.replace_version(version)
                await self._repository.save_version(version)
                failed[variation_id] = self._revision_planner.plan(
                    version,
                    QACheckResult(
                        passed=False,
                        score=version.qa_score or Decimal("0"),
                        issues=(issue,),
                        feedback=issue,
                    ),
                    sku,
                )

            await self._repository.save_job(job)
            if not failed:
                final_versions = tuple(
                    passing[input_data.variation_id]
                    for input_data in generation_inputs
                    if input_data.variation_id is not None
                )
                final_refs = tuple(version.version_id.value for version in final_versions)
                warnings = tuple(
                    dict.fromkeys(
                        warning for version in final_versions for warning in version.qa_warnings
                    )
                )
                scores = [
                    version.qa_score for version in final_versions if version.qa_score is not None
                ]
                job.transition_to(CreativeJobStatus.AWAITING_APPROVAL)
                job.add_audit(
                    "creative_set_qa_passed",
                    "system",
                    {"creative_set_id": creative_set_id, "versions": list(final_refs)},
                )
                card = ApprovalCard(
                    work_item_id=job.job_id.value,
                    candidate_summary=(
                        f"{gen_input.brand} / {gen_input.sku}: {selected.angle} "
                        f"({len(final_versions)} variations)"
                    ),
                    final_version_ref=final_refs[0],
                    final_version_refs=final_refs,
                    creative_set_id=creative_set_id,
                    thumbnail_ref=final_versions[0].artifact_path or final_versions[0].artifact_url,
                    warnings=warnings,
                    score=min(scores) if scores else None,
                    evidence_refs=tuple(e.source_id for e in context.evidence)
                    + (selected.idea_id,),
                )
                job.attach_card(card)
                job.record_lineage(
                    "approval_pending",
                    f"{job.job_id.value}:approval",
                    creative_set_id,
                    {"decision": "pending", "final_version_refs": list(final_refs)},
                )
                await self._repository.save_job(job)
                await self._approval_queue.submit(card)
                return ProcessResult(success=True, job=job, context=context, ideas=ideas)

            current_cost = job.total_cost.amount if job.total_cost else Decimal("0")
            for variation_id in failed:
                if not effective_budget.allows_retry(retry_counts[variation_id], current_cost):
                    exception_type = (
                        "max_retries_exceeded"
                        if retry_counts[variation_id] >= effective_budget.max_retries
                        else "budget_exceeded"
                    )
                    return await self._fail(
                        job,
                        exception_type=exception_type,
                        error_message=f"Cannot retry variation {variation_id}",
                        suggested_action="Review QA issues and adjust input or increase budget",
                    )
                retry_counts[variation_id] += 1
            pending = failed
            job.transition_to(CreativeJobStatus.REVISE_PENDING)
            job.add_audit(
                "set_revision_requested",
                "system",
                {"variations": list(failed)},
            )
            await self._repository.save_job(job)

    @staticmethod
    def _creative_set_issues(
        passing: dict[str, AssetVersion], expected_count: int
    ) -> dict[str, str]:
        if len(passing) != expected_count:
            raise RuntimeError("Creative set is incomplete after per-variation QA")
        seen: dict[str, str] = {}
        issues: dict[str, str] = {}
        for variation_id, version in passing.items():
            artifact_ref = version.artifact_path or version.artifact_url
            if artifact_ref is None:
                issues[variation_id] = "artifact_missing"
            elif artifact_ref in seen:
                issues[variation_id] = "duplicate_artifact_in_set"
            else:
                seen[artifact_ref] = variation_id
        return issues

    async def _fail(
        self,
        job: CreativeJob,
        exception_type: str,
        error_message: str,
        suggested_action: str,
        policy: bool = False,
    ) -> ProcessResult:
        """Move the job to an exception state and create a queue entry."""
        status = (
            CreativeJobStatus.EXCEPTION_POLICY
            if policy
            else CreativeJobStatus.EXCEPTION_OPERATIONAL
        )
        job.transition_to(status)
        job.add_audit(
            "exception",
            "system",
            {
                "exception_type": exception_type,
                "error": error_message,
                "suggested_action": suggested_action,
            },
        )
        await self._repository.save_job(job)
        await self._exception_queue.create(
            job_id=job.job_id,
            exception_type=exception_type,
            error_message=error_message,
            suggested_action=suggested_action,
        )
        return ProcessResult(
            success=False,
            job=job,
            error=error_message,
            exception_type=exception_type,
        )


class ProcessApproval:
    """Use case: process an approval decision (APPROVE or REJECT).

    The decision is recorded on the job and on the submitted approval card.
    """

    def __init__(
        self,
        repository: ICreativeRepository,
        approval_queue: IApprovalQueue,
    ) -> None:
        self._repository = repository
        self._approval_queue = approval_queue

    async def execute(
        self,
        job_id: CreativeJobId,
        decision: ApprovalDecision,
        reviewer: str,
        reason: str | None = None,
    ) -> ProcessResult:
        """Process an approval decision."""
        job = await self._repository.get_job(job_id)

        if job is None:
            return ProcessResult(
                success=False,
                error="Job not found",
            )

        validation = GenerationPolicyValidator.validate_job_can_approve(job)
        if not validation.is_valid:
            return ProcessResult(
                success=False,
                job=job,
                error="; ".join(validation.errors),
            )

        try:
            if decision == ApprovalDecision.APPROVE:
                job.approve(reviewer)
            elif decision == ApprovalDecision.REJECT:
                job.reject(reviewer, reason or "No reason provided")
            else:
                return ProcessResult(
                    success=False,
                    job=job,
                    error=f"Unknown decision: {decision}",
                    exception_type="invalid_decision",
                )
        except ValueError as e:
            return ProcessResult(
                success=False,
                job=job,
                error=str(e),
            )

        if job.card is not None:
            job.attach_card(job.card.with_decision(decision, reviewer, reason))

        successful_versions = job.successful_versions
        if successful_versions:
            final_refs = (
                job.card.final_version_refs
                if job.card is not None and job.card.final_version_refs
                else (successful_versions[-1].version_id.value,)
            )
            primary_ref = job.card.final_version_ref if job.card is not None else final_refs[0]
            primary_version = next(
                version
                for version in successful_versions
                if version.version_id.value == primary_ref
            )
            job.record_lineage(
                "approval_decision",
                f"{job.job_id.value}:decision:{decision.value}",
                job.creative_set_id or primary_version.version_id.value,
                {
                    "decision": decision.value,
                    "reviewer": reviewer,
                    "reason": reason,
                    "final_version_refs": list(final_refs),
                },
            )
            await self._approval_queue.process_decision(
                job.job_id,
                primary_version.version_id,
                decision.value,
                reviewer,
                reason,
            )

        await self._repository.save_job(job)
        for version in successful_versions:
            if version.version_id.value not in final_refs:
                continue
            semantic_outcome = next(
                (
                    warning.removeprefix("semantic_shadow_outcome:")
                    for warning in version.qa_warnings
                    if warning.startswith("semantic_shadow_outcome:")
                ),
                version.qa_outcome.value if version.qa_outcome else "not_recorded",
            )
            with observe_ai_call(
                "human_evaluation",
                "human",
                "final-review",
                job_id=job.job_id.value,
                version_id=version.version_id.value,
                creative_set_id=job.creative_set_id,
                decision=decision.value,
                reason_present=reason is not None,
                semantic_reviewer_version=version.qa_reviewer_version,
                semantic_outcome=semantic_outcome,
                semantic_score=(float(version.qa_score) if version.qa_score is not None else None),
            ) as observation:
                observation.human_evaluation(decision.value, semantic_outcome)
                observation.succeed()
        return ProcessResult(success=True, job=job)


__all__ = [
    "ProcessResult",
    "RunCreativeWorkflow",
    "ProcessApproval",
    "validate_work_item",
    "build_generation_input",
    "build_generation_inputs",
    "compute_input_hash",
]
