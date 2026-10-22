"""Supervised M1 preparation; no image, publishing or approval side effects."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from ..domain.entities import CreativeJob, CreativeJobId, CreativeJobStatus
from ..ports.contracts import (
    CreativeWorkItemInput,
    FidelityCheck,
    IdeaPackage,
    NormalizedRegion,
    ProductAsset,
    ProductPreservationSpec,
    ProvenanceSource,
    StaticCompositionSpec,
    StaticCreativeInput,
    StaticVariationPlan,
    TextPlacement,
)
from ..ports.interfaces import ICreativeRepository
from ..ports.preparation import (
    BriefDraft,
    BriefReview,
    CompositionDraft,
    IdeaCritique,
    IdeaDraft,
    IPreparationModel,
    ModelCallTrace,
    PreparationContext,
    PreparationError,
    RegionDraft,
    TextPlacementDraft,
    VariationBriefDraft,
)
from ..ports.preparation_store import (
    CandidateDecision,
    IPreparationStore,
    PreparationResult,
    PreparedBrief,
    StrategyPackage,
)


def check_references(
    context: PreparationContext,
    evidence_refs: tuple[str, ...],
    claim_ids: tuple[str, ...],
    reference_ids: tuple[str, ...],
    allowed_evidence_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Check source membership and approved-use constraints, not semantic truth."""
    issues: list[str] = []
    source_ids = {
        *(source.source_id for source in context.package.evidence),
        *allowed_evidence_refs,
    }
    if not evidence_refs or not set(evidence_refs).issubset(source_ids):
        issues.append("invalid_evidence_refs")
    claims = {claim.claim_id: claim for claim in context.approved_claims}
    for claim_id in claim_ids:
        claim = claims.get(claim_id)
        if claim is None or not claim.proof.verified:
            issues.append("unapproved_claim")
        elif not set(claim.evidence_refs).issubset(evidence_refs):
            issues.append("claim_evidence_missing")
    references = {reference.reference_id: reference for reference in context.references}
    for reference_id in reference_ids:
        reference = references.get(reference_id)
        if reference is None:
            issues.append("unknown_reference")
        elif not reference.asset.license_info:
            issues.append("reference_usage_unknown")
        elif reference.asset.expires_at and reference.asset.expires_at <= datetime.now(UTC):
            issues.append("reference_expired")
    return tuple(dict.fromkeys(issues))


def banned_copy_issues(context: PreparationContext, *texts: str | None) -> tuple[str, ...]:
    copy = "\n".join(text for text in texts if text).casefold()
    human_inputs = {
        claim.proof.text.casefold()
        for claim in context.approved_claims
        if claim.claim_id.startswith("human-claim:")
    }
    strategy = context.selected_strategy
    if strategy is not None and strategy.strategy_id.startswith("human-strategy:"):
        human_inputs.update(claim.casefold() for claim in strategy.claims)
        if strategy.offer:
            human_inputs.add(strategy.offer.casefold())
    return (
        ("explicit_banned_claim",)
        if any(
            claim.casefold() in copy
            and not any(claim.casefold() in human_input for human_input in human_inputs)
            for claim in context.sku.creative_constraints.banned_claims
        )
        else ()
    )


class PrepareCreativeBrief:
    """Prepare one brief, preserving intermediate evidence on expected failures."""

    def __init__(
        self,
        repository: ICreativeRepository,
        store: IPreparationStore,
        context: PreparationContext,
        model: IPreparationModel,
        *,
        max_ideas: int,
        max_brief_revisions: int,
        max_critique_attempts: int = 1,
        selection_rule_version: str,
        configuration: object,
    ) -> None:
        self.repository = repository
        self.store = store
        self.context = context
        self.model = model
        self.max_ideas = max_ideas
        self.max_brief_revisions = max_brief_revisions
        self.max_critique_attempts = max_critique_attempts
        self.selection_rule_version = selection_rule_version
        self.configuration = configuration

    async def execute(
        self, work_item: CreativeWorkItemInput, preparation_hash: str
    ) -> PreparationResult:
        existing = await self.repository.get_job_by_source_run_id(work_item.source_run_id)
        if existing is not None:
            if existing.preparation_hash != preparation_hash:
                return PreparationResult(
                    False,
                    existing,
                    duplicate=True,
                    exception_type="preparation_conflict",
                    error="Source run already exists with different input/config or legacy workflow",
                )
            completed_states = {
                CreativeJobStatus.BRIEF_READY,
                CreativeJobStatus.AWAITING_APPROVAL,
                CreativeJobStatus.APPROVED,
                CreativeJobStatus.REJECTED,
                CreativeJobStatus.ARCHIVED,
            }
            resumable_states = {
                CreativeJobStatus.PENDING,
                CreativeJobStatus.VALIDATING,
                CreativeJobStatus.COLLECTING_CONTEXT,
                CreativeJobStatus.IDEA_GENERATING,
                CreativeJobStatus.IDEA_REVIEW,
            }
            if existing.status in resumable_states:
                try:
                    existing.restart_preparation()
                except ValueError as error:
                    return PreparationResult(
                        False,
                        existing,
                        duplicate=True,
                        exception_type="existing_job_not_resumable",
                        error=str(error),
                    )
                await self.repository.save_job(existing)
                job = existing
            elif existing.status not in completed_states:
                return PreparationResult(
                    False,
                    existing,
                    duplicate=True,
                    exception_type="existing_job_not_resumable",
                    error="Inspect the existing job; use a new source run for a new attempt",
                )
            else:
                if not existing.brief_ref:
                    return PreparationResult(
                        False,
                        existing,
                        duplicate=True,
                        exception_type="preparation_artifact_error",
                        error="Prepared brief artifact reference is missing",
                    )
                try:
                    output = self.store.load_brief(existing.brief_ref)
                except (OSError, PreparationError):
                    return PreparationResult(
                        False,
                        existing,
                        duplicate=True,
                        exception_type="preparation_artifact_error",
                        error="Cannot read saved brief; restore the artifact before continuing",
                    )
                if output.preparation_hash != preparation_hash:
                    return PreparationResult(
                        False,
                        existing,
                        duplicate=True,
                        exception_type="preparation_artifact_error",
                        error="Saved brief does not match the job fingerprint",
                    )
                return PreparationResult(True, existing, output, duplicate=True)
        else:
            job = CreativeJob(
                CreativeJobId.generate(),
                CreativeJobStatus.PENDING,
                source_run_id=work_item.source_run_id,
                preparation_hash=preparation_hash,
            )
            job.record_lineage("work_item", work_item.source_run_id)
            await self.repository.save_job(job)
        traces: list[ModelCallTrace] = []
        try:
            job.transition_to(CreativeJobStatus.VALIDATING)
            await self.repository.save_job(job)
            self.store.write_snapshot(work_item.source_run_id, "input", work_item)
            self.store.write_snapshot(work_item.source_run_id, "config", self.configuration)
            if len(work_item.target_sku_set) != 1:
                raise PreparationError("Preparation requires exactly one SKU", code="invalid_scope")
            context = self.context
            if (
                context.sku != work_item.target_sku_set[0]
                or context.package.brand != work_item.marketing_scope.brand
                or context.package.sku_id != context.sku.sku_id
                or context.package.source_run_id != work_item.source_run_id
            ):
                raise PreparationError("Context does not match work item", code="invalid_scope")
            if not context.sku.product_metadata.image_refs:
                raise PreparationError(
                    "Product image references missing", code="missing_hard_input"
                )

            job.transition_to(CreativeJobStatus.COLLECTING_CONTEXT)
            await self.repository.save_job(job)
            self.store.write_snapshot(work_item.source_run_id, "context", context)
            job.context_ref = context.package.context_id
            job.record_lineage("context", job.context_ref, work_item.source_run_id)
            job.transition_to(CreativeJobStatus.IDEA_GENERATING)
            await self.repository.save_job(job)

            response = await self.model.propose(context, work_item)
            traces.append(response.trace)
            self.store.write_snapshot(work_item.source_run_id, "calls", tuple(traces))
            drafts = response.output
            self.store.write_snapshot(work_item.source_run_id, "candidates", drafts)
            if not 1 <= len(drafts) <= self.max_ideas:
                raise PreparationError("Unexpected idea count", code="invalid_idea_count")
            job.transition_to(CreativeJobStatus.IDEA_REVIEW)
            await self.repository.save_job(job)
            ideas, decisions = self._screen(drafts, work_item, job)
            eligible_indices = tuple(
                index for index, decision in enumerate(decisions, 1) if decision.eligible
            )
            if not eligible_indices:
                self.store.write_snapshot(work_item.source_run_id, "decisions", decisions)
                raise PreparationError(
                    "No candidate passes the configured checks", code="no_eligible_ideas"
                )
            critique, selected_index = await self._critique_with_validation_retry(
                context,
                work_item,
                drafts,
                eligible_indices,
                traces,
            )
            decisions = self._apply_critique(decisions, critique, selected_index)
            self.store.write_snapshot(work_item.source_run_id, "idea_critique", critique)
            self.store.write_snapshot(work_item.source_run_id, "decisions", decisions)
            selected = ideas[selected_index - 1]
            selected_draft = drafts[selected_index - 1]
            job.idea_id = selected.idea_id
            job.record_lineage(
                "idea_selected",
                selected.idea_id,
                job.context_ref,
                {"selection_rule_version": self.selection_rule_version},
            )
            await self.repository.save_job(job)

            response = await self.model.write_brief(context, work_item, selected_draft)
            traces.append(response.trace)
            self.store.write_snapshot(work_item.source_run_id, "calls", tuple(traces))
            self.store.write_snapshot(work_item.source_run_id, "brief_draft", response.output)
            draft = response.output
            self._compile(work_item, selected, selected_draft, draft)
            reviews: list[BriefReview] = []
            for review_number in range(self.max_brief_revisions + 1):
                review_response = await self.model.review_brief(
                    context, work_item, selected_draft, draft
                )
                traces.append(review_response.trace)
                self.store.write_snapshot(work_item.source_run_id, "calls", tuple(traces))
                review = review_response.output
                self._validate_brief_review(review, work_item)
                reviews.append(review)
                self.store.write_snapshot(work_item.source_run_id, "brief_reviews", tuple(reviews))
                if review.outcome == "pass":
                    break
                if review.outcome == "blocked":
                    raise PreparationError(
                        "Brief review is blocked by unresolved evidence",
                        code="strategy_review_blocked",
                    )
                if review_number >= self.max_brief_revisions:
                    raise PreparationError(
                        "Brief did not pass within the revision limit",
                        code="strategy_revision_exhausted",
                    )
                if review.revised_brief is None:
                    raise PreparationError(
                        "Brief reviewer omitted the required revision",
                        code="model_invalid_output",
                    )
                draft = review.revised_brief
                self._compile(work_item, selected, selected_draft, draft)
            brief = self._compile(work_item, selected, selected_draft, draft)
            compiled_plans = list(brief.variation_plans)
            compositions: list[StaticCompositionSpec] = []
            draft_variations = self._brief_variations(draft, work_item)
            for index, (plan, variation) in enumerate(
                zip(
                    brief.variation_plans[: work_item.requested_image_count],
                    draft_variations[: work_item.requested_image_count],
                    strict=True,
                ),
                start=1,
            ):
                variation_brief = BriefDraft(
                    heading=variation.heading,
                    subtext=variation.subtext,
                    visual_direction=variation.visual_direction,
                    evidence_refs=variation.evidence_refs,
                    claim_ids=variation.claim_ids,
                    reference_ids=variation.reference_ids,
                    variations=(variation,),
                )
                composition = await self._composition_with_validation_retry(
                    context,
                    work_item,
                    selected_draft,
                    variation_brief,
                    job,
                    index,
                    traces,
                )
                compositions.append(composition)
                compiled_plans[index - 1] = replace(plan, composition=composition)
            self.store.write_snapshot(work_item.source_run_id, "calls", tuple(traces))
            brief = replace(
                brief,
                composition=compositions[0] if compositions else None,
                variation_plans=tuple(compiled_plans),
            )
            self.store.write_snapshot(work_item.source_run_id, "compositions", tuple(compositions))
            strategy_id = f"{job.job_id.value}:strategy-1"
            strategy = StrategyPackage(
                strategy_id=strategy_id,
                selected_idea_id=selected.idea_id,
                critique=critique,
                brief_reviews=tuple(reviews),
                evidence_refs=tuple(
                    dict.fromkeys(
                        (
                            *critique.evidence_refs,
                            *(ref for review in reviews for ref in review.evidence_refs),
                        )
                    )
                ),
                prompt_versions=tuple(dict.fromkeys(trace.prompt_version for trace in traces)),
                composition=compositions[0] if compositions else None,
                compositions=tuple(compositions),
            )
            output = PreparedBrief(
                context=context,
                ideas=ideas,
                decisions=decisions,
                selected_idea=selected,
                brief=brief,
                traces=tuple(traces),
                warnings=tuple(
                    dict.fromkeys(
                        (
                            *context.warnings,
                            "creative_artifact_semantics_not_reviewed",
                        )
                    )
                ),
                preparation_hash=preparation_hash,
                selection_rule_version=self.selection_rule_version,
                strategy=strategy,
            )
            self.store.write_snapshot(work_item.source_run_id, "brief", brief)
            self.store.write_snapshot(work_item.source_run_id, "strategy", strategy)
            reference = self.store.write_snapshot(work_item.source_run_id, "prepared", output)
            job.brief_ref = reference
            job.record_lineage(
                "strategy",
                strategy_id,
                selected.idea_id,
                {"schema_version": strategy.schema_version},
            )
            for composition in compositions:
                job.record_lineage(
                    "composition",
                    composition.composition_id,
                    strategy_id,
                    {"version": composition.version},
                )
            job.record_lineage(
                "brief", reference, strategy_id, {"preparation_hash": preparation_hash}
            )
            job.transition_to(CreativeJobStatus.BRIEF_READY)
            await self.repository.save_job(job)
            return PreparationResult(True, job, output)
        except PreparationError as error:
            if error.trace is not None:
                traces.append(error.trace)
            return await self.record_failure(job, error.code, str(error), traces)
        except OSError:
            return await self.record_failure(
                job, "preparation_storage_error", "Cannot persist preparation artifacts", traces
            )
        except TimeoutError:
            return await self.record_failure(
                job, "preparation_timeout", "Preparation deadline exceeded", traces
            )

    async def _critique_with_validation_retry(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        drafts: tuple[IdeaDraft, ...],
        eligible_indices: tuple[int, ...],
        traces: list[ModelCallTrace],
    ) -> tuple[IdeaCritique, int]:
        for attempt in range(1, self.max_critique_attempts + 1):
            critique_response = await self.model.critique_ideas(
                context, work_item, drafts, eligible_indices
            )
            traces.append(critique_response.trace)
            self.store.write_snapshot(work_item.source_run_id, "calls", tuple(traces))
            critique = critique_response.output
            self.store.write_snapshot(
                work_item.source_run_id,
                f"idea_critique_attempt_{attempt}",
                critique,
            )
            try:
                selected_index = self._validate_critique(
                    critique,
                    drafts,
                    eligible_indices,
                    work_item,
                )
            except PreparationError as error:
                if error.code != "model_invalid_output" or attempt == self.max_critique_attempts:
                    raise
                continue
            return critique, selected_index
        raise AssertionError("Critique validation retry loop exhausted unexpectedly")

    async def _composition_with_validation_retry(
        self,
        context: PreparationContext,
        work_item: CreativeWorkItemInput,
        selected: IdeaDraft,
        brief: BriefDraft,
        job: CreativeJob,
        variation_index: int,
        traces: list[ModelCallTrace],
    ) -> StaticCompositionSpec:
        for attempt in range(1, self.max_critique_attempts + 1):
            composition_response = await self.model.plan_composition(
                context, work_item, selected, brief
            )
            traces.append(composition_response.trace)
            self.store.write_snapshot(work_item.source_run_id, "calls", tuple(traces))
            self.store.write_snapshot(
                work_item.source_run_id,
                f"composition_{variation_index}_attempt_{attempt}",
                composition_response.output,
            )
            try:
                return self._compile_composition(
                    composition_response.output,
                    brief,
                    work_item,
                    job,
                    composition_response.trace.prompt_version,
                    variation_index,
                )
            except PreparationError as error:
                if error.code != "invalid_composition" or attempt == self.max_critique_attempts:
                    raise
        raise AssertionError("Composition validation retry loop exhausted unexpectedly")

    def _compile_composition(
        self,
        draft: CompositionDraft,
        brief: BriefDraft,
        work_item: CreativeWorkItemInput,
        job: CreativeJob,
        version: str,
        variation_index: int,
    ) -> StaticCompositionSpec:
        issues = check_references(
            self.context,
            draft.evidence_refs,
            (),
            (),
            self._experiment_evidence(work_item),
        )
        if issues:
            raise PreparationError(
                "Composition contains invalid evidence references",
                code="invalid_composition",
            )
        if brief.subtext and draft.subtext is None:
            raise PreparationError(
                "Composition omitted the approved subtext region",
                code="invalid_composition",
            )
        if banned_copy_issues(self.context, draft.visual_prompt):
            raise PreparationError(
                "Composition visual prompt contains a banned claim",
                code="invalid_composition",
            )
        if draft.product_source_index is None or not draft.segmentation_prompt:
            raise PreparationError(
                "Composition omitted product preservation instructions",
                code="invalid_composition",
            )
        product_count = len(self.context.sku.product_metadata.image_refs)
        if not 0 <= draft.product_source_index < product_count:
            raise PreparationError(
                "Composition selected an invalid product source",
                code="invalid_composition",
            )
        visual_prompt = (
            f"{draft.visual_prompt.strip()}\n"
            "Generate the background and environment only. Leave the planned product region "
            "clear for deterministic placement of the original product pixels. "
            "Do not render the product. Do not render words, letters, typography, "
            "watermarks, or logos."
        )
        try:
            return StaticCompositionSpec(
                composition_id=f"{job.job_id.value}:composition-{variation_index}",
                version=version,
                visual_prompt=visual_prompt,
                product_region=self._region(draft.product_region),
                heading=self._text_placement(draft.heading),
                subtext=self._text_placement(draft.subtext) if draft.subtext else None,
                logo_region=self._region(draft.logo_region) if draft.logo_region else None,
                product_preservation=ProductPreservationSpec(
                    source_index=draft.product_source_index,
                    segmentation_prompt=draft.segmentation_prompt.strip(),
                ),
                rationale=draft.rationale,
                evidence_refs=draft.evidence_refs,
            )
        except ValueError as error:
            raise PreparationError(
                f"Composition layout is invalid: {error}", "invalid_composition"
            ) from error

    @staticmethod
    def _region(draft: RegionDraft) -> NormalizedRegion:
        return NormalizedRegion(
            x=draft.x,
            y=draft.y,
            width=draft.width,
            height=draft.height,
        )

    @classmethod
    def _text_placement(cls, draft: TextPlacementDraft) -> TextPlacement:
        return TextPlacement(
            region=cls._region(draft.region),
            alignment=draft.alignment,
            text_color=draft.text_color,
            background_color=draft.background_color,
        )

    async def record_failure(
        self, job: CreativeJob, code: str, message: str, traces: list[ModelCallTrace]
    ) -> PreparationResult:
        job.transition_to(CreativeJobStatus.EXCEPTION_OPERATIONAL)
        job.add_audit("preparation_failed", "system", {"code": code, "message": message})
        await self.repository.save_job(job)
        # The database retains the failure when filesystem storage is unavailable.
        with suppress(OSError):
            self.store.write_snapshot(
                job.source_run_id or "",
                "failure",
                {"code": code, "message": message, "calls": traces},
            )
        return PreparationResult(False, job, error=message, exception_type=code)

    def _screen(
        self, drafts: tuple[IdeaDraft, ...], work_item: CreativeWorkItemInput, job: CreativeJob
    ) -> tuple[tuple[IdeaPackage, ...], tuple[CandidateDecision, ...]]:
        personas = {persona.persona_id: persona for persona in self.context.personas}
        ideas: list[IdeaPackage] = []
        decisions: list[CandidateDecision] = []
        seen: set[tuple[str, str]] = set()
        for index, draft in enumerate(drafts, 1):
            reasons = list(
                check_references(
                    self.context,
                    draft.evidence_refs,
                    draft.claim_ids,
                    draft.reference_ids,
                    self._experiment_evidence(work_item),
                )
            )
            reasons.extend(banned_copy_issues(self.context, draft.angle, draft.hook, draft.concept))
            if draft.persona_id not in personas:
                reasons.append("unknown_persona")
            if work_item.persona_override and draft.persona_id != work_item.persona_override:
                reasons.append("persona_override_mismatch")
            key = (draft.angle.strip().casefold(), draft.concept.strip().casefold())
            if key in seen:
                reasons.append("duplicate_idea")
            eligible = not reasons
            if eligible:
                seen.add(key)
            idea = IdeaPackage(
                idea_id=f"{job.job_id.value}:idea-{index}",
                brand=work_item.marketing_scope.brand,
                sku_id=self.context.sku.sku_id,
                objective=work_item.objective,
                market=work_item.marketing_scope.market,
                persona=draft.persona_id,
                angle=draft.angle,
                hook=draft.hook,
                concept=draft.concept,
                evidence_refs=draft.evidence_refs,
                fidelity_checks=(FidelityCheck("source_membership_and_constraints", eligible),),
                risk_flags=tuple(reasons),
                confidence=Decimal("0"),
            )
            ideas.append(idea)
            decisions.append(
                CandidateDecision(
                    idea.idea_id,
                    eligible,
                    False,
                    tuple(reasons) if reasons else ("eligible",),
                )
            )
        return tuple(ideas), tuple(decisions)

    def _validate_critique(
        self,
        critique: IdeaCritique,
        drafts: tuple[IdeaDraft, ...],
        eligible_indices: tuple[int, ...],
        work_item: CreativeWorkItemInput,
    ) -> int:
        source_ids = {
            *(source.source_id for source in self.context.package.evidence),
            *self._experiment_evidence(work_item),
        }
        assessment_indices = tuple(
            assessment.candidate_index for assessment in critique.assessments
        )
        expected_indices = tuple(range(1, len(drafts) + 1))
        if sorted(assessment_indices) != list(expected_indices):
            raise PreparationError(
                "Idea critique must assess every candidate exactly once",
                code="model_invalid_output",
            )
        referenced = (
            *critique.evidence_refs,
            *(ref for assessment in critique.assessments for ref in assessment.evidence_refs),
        )
        if not critique.evidence_refs or not set(referenced).issubset(source_ids):
            raise PreparationError(
                "Idea critique contains invalid evidence references",
                code="model_invalid_output",
            )
        selected = critique.selected_candidate_index
        if selected is None:
            raise PreparationError(
                "Strategy evaluator did not recommend an eligible idea",
                code="strategy_evidence_insufficient",
            )
        recommendations = {
            assessment.candidate_index: assessment.recommendation
            for assessment in critique.assessments
        }
        if selected not in eligible_indices or recommendations.get(selected) != "select":
            raise PreparationError(
                "Strategy evaluator selected an ineligible or inconsistent candidate",
                code="model_invalid_output",
            )
        if sum(value == "select" for value in recommendations.values()) != 1:
            raise PreparationError(
                "Idea critique must select exactly one candidate",
                code="model_invalid_output",
            )
        return selected

    @staticmethod
    def _apply_critique(
        decisions: tuple[CandidateDecision, ...],
        critique: IdeaCritique,
        selected_index: int,
    ) -> tuple[CandidateDecision, ...]:
        recommendations = {
            assessment.candidate_index: assessment.recommendation
            for assessment in critique.assessments
        }
        return tuple(
            CandidateDecision(
                idea_id=decision.idea_id,
                eligible=decision.eligible,
                selected=index == selected_index,
                reasons=(
                    decision.reasons
                    if not decision.eligible
                    else (f"strategy_{recommendations[index]}",)
                ),
            )
            for index, decision in enumerate(decisions, 1)
        )

    def _validate_brief_review(self, review: BriefReview, work_item: CreativeWorkItemInput) -> None:
        source_ids = {
            *(source.source_id for source in self.context.package.evidence),
            *self._experiment_evidence(work_item),
        }
        if not review.evidence_refs or not set(review.evidence_refs).issubset(source_ids):
            raise PreparationError(
                "Brief review contains invalid evidence references",
                code="model_invalid_output",
            )
        if review.outcome == "pass" and review.revised_brief is not None:
            raise PreparationError(
                "Passing brief review cannot include a revision",
                code="model_invalid_output",
            )
        if review.outcome == "pass" and (review.issues or review.revision_instructions):
            raise PreparationError(
                "Passing brief review cannot include unresolved issues",
                code="model_invalid_output",
            )
        if review.outcome == "revise" and (
            review.revised_brief is None or not review.issues or not review.revision_instructions
        ):
            raise PreparationError(
                "Brief revision requires issues, instructions and a complete revised draft",
                code="model_invalid_output",
            )
        if review.outcome == "blocked" and review.revised_brief is not None:
            raise PreparationError(
                "Blocked brief review cannot include a revision",
                code="model_invalid_output",
            )

    @staticmethod
    def _experiment_evidence(work_item: CreativeWorkItemInput) -> tuple[str, ...]:
        return (
            work_item.experiment_context.evidence_refs
            if work_item.experiment_context is not None
            else ()
        )

    @staticmethod
    def _brief_variations(
        draft: BriefDraft, work_item: CreativeWorkItemInput
    ) -> tuple[VariationBriefDraft, ...]:
        if draft.variations:
            if len(draft.variations) != work_item.variation_count:
                raise PreparationError(
                    "Brief must contain exactly one plan per requested variation",
                    code="invalid_brief",
                )
            keys = [variation.variation_key for variation in draft.variations]
            if len(keys) != len(set(keys)):
                raise PreparationError("Brief variation keys must be unique", code="invalid_brief")
            first = replace(
                draft.variations[0],
                heading=draft.heading,
                subtext=draft.subtext,
                visual_direction=draft.visual_direction,
                evidence_refs=draft.evidence_refs,
                claim_ids=draft.claim_ids,
                reference_ids=draft.reference_ids,
            )
            return (first, *draft.variations[1:])
        if work_item.variation_count != 1:
            raise PreparationError(
                "Creative Sets require explicit per-variation briefs", code="invalid_brief"
            )
        return (
            VariationBriefDraft(
                variation_key="variation-01",
                heading=draft.heading,
                subtext=draft.subtext,
                visual_direction=draft.visual_direction,
                evidence_refs=draft.evidence_refs,
                claim_ids=draft.claim_ids,
                reference_ids=draft.reference_ids,
            ),
        )

    def _compile(
        self,
        work_item: CreativeWorkItemInput,
        idea: IdeaPackage,
        selected: IdeaDraft,
        draft: BriefDraft,
    ) -> StaticCreativeInput:
        variations = self._brief_variations(draft, work_item)
        issues: list[str] = []
        plans: list[StaticVariationPlan] = []
        reference_ids: list[str] = []
        claim_ids: list[str] = []
        for variation in variations:
            issues.extend(
                check_references(
                    self.context,
                    variation.evidence_refs,
                    variation.claim_ids,
                    variation.reference_ids,
                    self._experiment_evidence(work_item),
                )
            )
            visual_direction = variation.visual_direction
            if work_item.creative_direction_override:
                visual_direction = (
                    f"{work_item.creative_direction_override.strip()}\n"
                    f"Variation direction: {visual_direction.strip()}"
                )
            issues.extend(
                banned_copy_issues(
                    self.context,
                    variation.heading,
                    variation.subtext,
                    visual_direction,
                )
            )
            if set(variation.claim_ids) != set(selected.claim_ids):
                issues.append("brief_changed_claims")
            if not set(variation.reference_ids).issubset(selected.reference_ids):
                issues.append("brief_changed_references")
            reference_ids.extend(variation.reference_ids)
            claim_ids.extend(variation.claim_ids)
            try:
                plans.append(
                    StaticVariationPlan(
                        variation_key=variation.variation_key,
                        heading=variation.heading,
                        subtext=variation.subtext,
                        visual_direction=visual_direction,
                        awareness_stage=variation.awareness_stage,
                        angle=variation.angle or selected.angle,
                        offer=variation.offer,
                        production_level=variation.production_level,
                        evidence_refs=variation.evidence_refs,
                    )
                )
            except ValueError as error:
                raise PreparationError(
                    "Brief response violates the required Creative contract",
                    code="invalid_brief",
                ) from error
        if issues:
            raise PreparationError(
                "Brief rejected: " + ", ".join(dict.fromkeys(issues)),
                code="invalid_brief",
            )
        sku = self.context.sku
        claims = {claim.claim_id: claim.proof for claim in self.context.approved_claims}
        references = {
            reference.reference_id: reference.asset for reference in self.context.references
        }
        first = plans[0]
        return StaticCreativeInput(
            brand=work_item.marketing_scope.brand,
            sku=sku.sku_id,
            objective=work_item.objective,
            idea_id=idea.idea_id,
            heading=first.heading,
            subtext=first.subtext,
            visual_direction=first.visual_direction,
            product_assets=tuple(
                ProductAsset(ref, "product", ProvenanceSource.SOURCE_OF_TRUTH)
                for ref in sku.product_metadata.image_refs
            ),
            reference_assets=tuple(references[ref] for ref in dict.fromkeys(reference_ids)),
            proof_references=tuple(claims[ref] for ref in dict.fromkeys(claim_ids)),
            output_spec=sku.creative_constraints.format_spec,
            prompt_version=work_item.prompt_version,
            rubric_version=work_item.rubric_version,
            policy_version=work_item.policy_version,
            created_by=work_item.created_by,
            brand_guideline_ref=sku.creative_constraints.brand_guideline_ref,
            banned_claims=sku.creative_constraints.banned_claims,
            variation_plans=tuple(plans),
        )
