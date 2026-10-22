"""Typed synthetic fixture loader for Creative intake."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_content.domains.marketing.creative.bootstrap import load_preparation_case
from ai_content.domains.marketing.creative.ports.contracts import CreativeWorkItemInput
from ai_content.domains.marketing.creative.ports.preparation import PreparationContext

from ..application.contracts import (
    CreativeIntakeCase,
    CreativeIntakeFixture,
    case_for_trigger,
    intake_fingerprint,
)
from ..application.resolution import CreativeIntakeRequest
from ..domain.models import (
    ComponentStatus,
    ContextComponent,
    ContextEvidence,
    CreativeContextSnapshot,
    CreativeTaskTrigger,
    TriggerSource,
)


class ComponentFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: ContextComponent
    status: ComponentStatus
    evidence_refs: tuple[str, ...] = ()
    observed_at: datetime
    valid_until: datetime | None = None
    detail: str | None = None


class ContextFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    work_item_fixture: Path
    context_fixture: Path
    captured_at: datetime
    components: tuple[ComponentFixture, ...]
    product_image_count: int | None = Field(default=None, ge=0)
    persona_count: int | None = Field(default=None, ge=0)
    output_width: int | None = Field(default=None, ge=0)
    output_height: int | None = Field(default=None, ge=0)
    version_ref_count: int | None = Field(default=None, ge=0, le=5)
    resolved_context_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_components(self) -> ContextFixture:
        values = [item.component for item in self.components]
        if len(values) != len(set(values)):
            raise ValueError("Context fixture components must be unique")
        return self


class TriggerFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_id: str = Field(min_length=1)
    source: TriggerSource
    source_preview_id: str = Field(min_length=1)
    source_decision_ref: str = Field(min_length=1)
    source_released: bool
    brand_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    objective: str | None = None
    channel: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    requested_at: datetime
    source_creative_version_id: str | None = None
    reusable_context_refs: tuple[str, ...] = ()


class CaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_snapshot_id: str
    trigger: TriggerFixture


class _FixtureFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contexts: tuple[ContextFixture, ...]
    cases: tuple[CaseFixture, ...]

    @model_validator(mode="after")
    def valid_references(self) -> _FixtureFile:
        context_ids = [item.snapshot_id for item in self.contexts]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("Context snapshot IDs must be unique")
        if any(case.context_snapshot_id not in context_ids for case in self.cases):
            raise ValueError("Every case must reference an existing context snapshot")
        source_keys = [(case.trigger.source, case.trigger.source_preview_id) for case in self.cases]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("Fixture cases must use unique upstream preview identities")
        return self


def load_creative_intake_fixture(path: Path) -> CreativeIntakeFixture:
    fixture = _FixtureFile.model_validate_json(path.read_text(encoding="utf-8"))
    root = path.resolve().parent
    loaded_contexts: dict[
        str, tuple[CreativeContextSnapshot, CreativeWorkItemInput, PreparationContext]
    ] = {}
    for item in fixture.contexts:
        work_path = (root / item.work_item_fixture).resolve()
        context_path = (root / item.context_fixture).resolve()
        local_case = load_preparation_case(
            work_path,
            context_path,
            max_context_bytes=131072,
        )
        work_item = local_case.work_item
        preparation = local_case.context
        available_context_refs = {source.source_id for source in preparation.sources}
        supplied_context_refs = {
            ref for component in item.components for ref in component.evidence_refs
        }
        if not supplied_context_refs.issubset(available_context_refs):
            raise ValueError("Context component references must exist in the preparation pack")
        sku = work_item.target_sku_set[0]
        version_refs = (
            str(work_item.prompt_version),
            str(work_item.rubric_version),
            str(work_item.policy_version),
            str(work_item.rule_version),
            str(work_item.workflow_version),
        )
        evidence_refs = tuple(source.source_id for source in preparation.sources)
        snapshot = CreativeContextSnapshot(
            snapshot_id=item.snapshot_id,
            version=item.version,
            brand_id=work_item.marketing_scope.brand,
            sku_id=sku.sku_id,
            market=work_item.marketing_scope.market,
            objective=work_item.objective,
            channel=work_item.channel,
            product_image_count=(
                item.product_image_count
                if item.product_image_count is not None
                else len(sku.product_metadata.image_refs)
            ),
            persona_count=(
                item.persona_count if item.persona_count is not None else len(preparation.personas)
            ),
            output_width=(
                item.output_width
                if item.output_width is not None
                else sku.creative_constraints.format_spec.width
            ),
            output_height=(
                item.output_height
                if item.output_height is not None
                else sku.creative_constraints.format_spec.height
            ),
            version_refs=(
                version_refs[: item.version_ref_count]
                if item.version_ref_count is not None
                else version_refs
            ),
            resolved_context_refs=item.resolved_context_refs,
            components=tuple(
                ContextEvidence(
                    component=component.component,
                    status=component.status,
                    evidence_refs=component.evidence_refs,
                    observed_at=component.observed_at,
                    valid_until=component.valid_until,
                    detail=component.detail,
                )
                for component in item.components
            ),
            evidence_refs=evidence_refs,
            captured_at=item.captured_at,
        )
        loaded_contexts[item.snapshot_id] = (snapshot, work_item, preparation)

    cases: list[CreativeIntakeCase] = []
    for item in fixture.cases:
        snapshot, work_item, preparation = loaded_contexts[item.context_snapshot_id]
        data = item.trigger
        trigger = CreativeTaskTrigger(
            trigger_id=data.trigger_id,
            source=data.source,
            source_preview_id=data.source_preview_id,
            source_decision_ref=data.source_decision_ref,
            source_released=data.source_released,
            brand_id=data.brand_id,
            sku_id=data.sku_id,
            action=data.action,
            objective=data.objective,
            channel=data.channel,
            evidence_refs=data.evidence_refs,
            requested_at=data.requested_at,
            source_creative_version_id=data.source_creative_version_id,
            reusable_context_refs=data.reusable_context_refs,
        )
        cases.append(
            CreativeIntakeCase(
                request=CreativeIntakeRequest(
                    trigger,
                    snapshot,
                    intake_fingerprint(trigger, snapshot, work_item, preparation),
                ),
                work_item_template=work_item,
                context_template=preparation,
            )
        )
    return CreativeIntakeFixture(tuple(cases))


__all__ = [
    "CreativeIntakeCase",
    "CreativeIntakeFixture",
    "case_for_trigger",
    "load_creative_intake_fixture",
]
