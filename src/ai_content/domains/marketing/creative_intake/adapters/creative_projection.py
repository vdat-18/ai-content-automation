"""Compile a released intake into the existing M1 contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ai_content.domains.marketing.creative.ports.contracts import (
    CreativeWorkItemInput,
    ExperimentContext,
)
from ai_content.domains.marketing.creative.ports.preparation import PreparationContext

from ..domain.models import CreativeIntakeRun, IntakeState


@dataclass(frozen=True)
class CompiledCreativeTask:
    work_item: CreativeWorkItemInput
    context: PreparationContext


def compile_creative_task(
    run: CreativeIntakeRun,
    work_item_template: CreativeWorkItemInput,
    context_template: PreparationContext,
) -> CompiledCreativeTask:
    if run.state != IntakeState.RELEASED or run.release is None:
        raise ValueError("Only a released intake can compile an M1 task")
    if len(work_item_template.target_sku_set) != 1:
        raise ValueError("Creative intake supports exactly one SKU")
    sku = work_item_template.target_sku_set[0]
    if (
        work_item_template.marketing_scope.brand != run.context.brand_id
        or sku.sku_id != run.context.sku_id
        or context_template.package.brand != run.context.brand_id
        or context_template.package.sku_id != run.context.sku_id
        or context_template.sku.sku_id != run.context.sku_id
    ):
        raise ValueError("M1 templates do not match the released context identity")
    objective = run.trigger.objective or run.context.objective
    channel = run.trigger.channel or run.context.channel
    work_item = replace(
        work_item_template,
        source_run_id=run.release.source_run_id,
        objective=objective,
        channel=channel,
        experiment_context=(
            ExperimentContext(
                source_decision_ref=run.trigger.source_decision_ref,
                category=run.trigger.experiment_directive.category,
                priority=run.trigger.experiment_directive.priority,
                hypothesis=run.trigger.experiment_directive.hypothesis,
                experiment=run.trigger.experiment_directive.experiment,
                success_signal=run.trigger.experiment_directive.success_signal,
                evidence_refs=run.trigger.experiment_directive.evidence_refs,
                uncertainty=run.trigger.experiment_directive.uncertainty,
            )
            if run.trigger.experiment_directive
            else None
        ),
        created_by="creative-intake",
    )
    package = replace(
        context_template.package,
        context_id=(
            f"{run.release.source_run_id}:{run.context.sku_id}:{context_template.pack_hash[:12]}"
        ),
        source_run_id=run.release.source_run_id,
    )
    context = replace(context_template, package=package, sku=work_item.target_sku_set[0])
    return CompiledCreativeTask(work_item, context)


__all__ = ["CompiledCreativeTask", "compile_creative_task"]
