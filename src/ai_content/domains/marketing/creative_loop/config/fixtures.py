"""Strict fixture contract for a bounded synthetic Creative loop."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_content.domains.marketing.creative.bootstrap import load_preparation_case
from ai_content.domains.marketing.creative_feedback.domain.models import EvidenceStatus
from ai_content.domains.marketing.creative_intake.application.contracts import intake_fingerprint
from ai_content.domains.marketing.creative_intake.application.resolution import (
    CreativeIntakeRequest,
)
from ai_content.domains.marketing.creative_intake.config.fixtures import (
    ComponentFixture,
    ContextFixture,
    CreativeIntakeCase,
    CreativeIntakeFixture,
    TriggerFixture,
    load_creative_intake_fixture,
)
from ai_content.domains.marketing.creative_intake.domain.models import (
    ComponentStatus,
    ContextComponent,
    ContextEvidence,
    CreativeContextSnapshot,
    CreativeTaskTrigger,
)
from ai_content.domains.marketing.performance_decisions.application.evaluation import (
    PerformanceDecisionRequest,
)
from ai_content.domains.marketing.performance_decisions.config.fixtures import (
    PerformanceDecisionFixture,
    load_performance_decision_fixture,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    MetricStatus,
    SubjectType,
)

from ..ports.contracts import AdsOutcome, CreativeLoopInput


class AdsOutcomeFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    adset_id: str = Field(min_length=1)
    ad_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    purchases: Decimal | None = Field(default=None, ge=0)
    roas: Decimal | None = Field(default=None, ge=0)
    cost_per_atc: Decimal | None = Field(default=None, ge=0)
    evidence_status: MetricStatus = MetricStatus.KNOWN
    mapping_status: EvidenceStatus = EvidenceStatus.KNOWN
    observed_at: datetime

    @model_validator(mode="after")
    def known_values_are_complete(self) -> AdsOutcomeFixture:
        values = (self.purchases, self.roas, self.cost_per_atc)
        if self.evidence_status == MetricStatus.KNOWN and any(value is None for value in values):
            raise ValueError("Known Ads outcome requires purchases, ROAS and cost per ATC")
        if self.evidence_status != MetricStatus.KNOWN and any(
            value is not None for value in values
        ):
            raise ValueError("Unknown or conflicting Ads outcome cannot select metric values")
        return self


class LoopCaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    initial_performance_source_run_id: str = Field(min_length=1)
    context_snapshot_id: str = Field(min_length=1)
    ads_outcome: AdsOutcomeFixture


class _FixtureFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    performance_fixture: Path
    intake_fixture: Path
    cases: tuple[LoopCaseFixture, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> _FixtureFile:
        for values in (
            [item.case_id for item in self.cases],
            [item.source_run_id for item in self.cases],
            [item.ads_outcome.event_id for item in self.cases],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Creative loop fixture identities must be unique")
        return self


class _LocalLoopFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    captured_at: datetime
    ads_outcome: AdsOutcomeFixture


@dataclass(frozen=True)
class CreativeLoopFixture:
    cases: tuple[CreativeLoopInput, ...]
    ads_outcomes: tuple[tuple[str, AdsOutcome], ...]

    def case(self, input_snapshot_id: str) -> CreativeLoopInput:
        case = next(
            (item for item in self.cases if item.input_snapshot_id == input_snapshot_id), None
        )
        if case is None:
            raise ValueError("Creative loop fixture case not found")
        return case

    def ads_outcome(self, input_snapshot_id: str) -> AdsOutcome:
        outcome = next(
            (item for case_id, item in self.ads_outcomes if case_id == input_snapshot_id),
            None,
        )
        if outcome is None:
            raise ValueError("Creative loop fixture Ads outcome not found")
        return outcome


def _checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _build_local_performance(
    local: _LocalLoopFile,
    *,
    work_item,
    sku,
    preparation_pack_hash: str,
) -> PerformanceDecisionRequest:
    observed_at = local.captured_at
    fixture = PerformanceDecisionFixture.model_validate(
        {
            "rule_sets": [
                {
                    "rule_set_id": "local-product-demand-rules",
                    "version": "local-v1",
                    "status": "draft",
                    "mode": "strict",
                    "effective_at": observed_at.isoformat(),
                    "rules": [
                        {
                            "rule_id": "local-product-strong",
                            "subject_type": "product",
                            "classification": "product_strong_candidate",
                            "recommendation": "request_new_creative",
                            "required_passes": 2,
                            "criteria": [
                                {
                                    "criterion_id": "purchases-last-3",
                                    "metric": "purchases",
                                    "window_id": "last-3",
                                    "operator": "gt",
                                    "threshold": 4,
                                },
                                {
                                    "criterion_id": "purchases-last-6",
                                    "metric": "purchases",
                                    "window_id": "last-6",
                                    "operator": "gt",
                                    "threshold": 4,
                                },
                            ],
                        },
                        {
                            "rule_id": "local-creative-win",
                            "subject_type": "creative",
                            "classification": "creative_win",
                            "recommendation": "retest_creative",
                            "required_passes": 3,
                            "criteria": [
                                {
                                    "criterion_id": "creative-win-purchases",
                                    "metric": "purchases",
                                    "window_id": "creative-window",
                                    "operator": "gt",
                                    "threshold": 2,
                                },
                                {
                                    "criterion_id": "creative-win-roas",
                                    "metric": "roas",
                                    "window_id": "creative-window",
                                    "operator": "gt",
                                    "threshold": 6,
                                },
                                {
                                    "criterion_id": "creative-win-cost-atc",
                                    "metric": "cost_per_atc",
                                    "window_id": "creative-window",
                                    "operator": "lt",
                                    "threshold": 60,
                                },
                            ],
                        },
                    ],
                }
            ],
            "cases": [
                {
                    "source_run_id": f"{local.source_run_id}-initial-performance",
                    "rule_set_ref": "local-product-demand-rules",
                    "snapshot": {
                        "snapshot_id": f"{local.case_id}-initial-snapshot",
                        "subject": {
                            "subject_type": "product",
                            "subject_id": sku.sku_id,
                            "brand_id": work_item.marketing_scope.brand,
                            "store_id": f"{work_item.marketing_scope.brand}-store",
                            "sku_id": sku.sku_id,
                            "platform": "cross-channel",
                        },
                        "objective": work_item.objective,
                        "channel": work_item.channel,
                        "timezone": "UTC",
                        "attribution": "local-pilot-draft",
                        "currency": "USD",
                        "source_version": "local-pilot@1",
                        "observed_at": observed_at.isoformat(),
                        "metrics": [
                            {
                                "name": "purchases",
                                "window_id": "last-3",
                                "status": "known",
                                "value": 7,
                                "unit": "count",
                                "source_ref": "local://performance/last-3",
                                "observed_at": observed_at.isoformat(),
                            },
                            {
                                "name": "purchases",
                                "window_id": "last-6",
                                "status": "known",
                                "value": 11,
                                "unit": "count",
                                "source_ref": "local://performance/last-6",
                                "observed_at": observed_at.isoformat(),
                            },
                        ],
                    },
                }
            ],
        }
    )
    request = fixture.requests()[0]
    return replace(
        request,
        source_checksum_sha256=_checksum(
            {
                "base_checksum": request.source_checksum_sha256,
                "preparation_pack_hash": preparation_pack_hash,
            }
        ),
    )


def _initial_request(
    base: PerformanceDecisionRequest,
    case: LoopCaseFixture,
    intake: CreativeIntakeFixture,
) -> PerformanceDecisionRequest:
    context_case = next(
        (
            item
            for item in intake.cases
            if item.request.context.snapshot_id == case.context_snapshot_id
        ),
        None,
    )
    if context_case is None:
        raise ValueError("Creative loop context snapshot not found")
    context = context_case.request.context
    subject = replace(
        base.snapshot.subject,
        subject_type=SubjectType.PRODUCT,
        subject_id=context.sku_id,
        brand_id=context.brand_id,
        store_id=f"{context.brand_id}-synthetic-store",
        sku_id=context.sku_id,
        platform="cross-channel",
        creative_id=None,
        angle_id=None,
        concept_id=None,
        persona_id=None,
        raw_source_name=None,
    )
    snapshot = replace(
        base.snapshot,
        snapshot_id=f"{case.case_id}-initial-snapshot",
        subject=subject,
        objective=context.objective,
        channel=context.channel,
    )
    return PerformanceDecisionRequest(
        source_run_id=f"{case.source_run_id}-initial-performance",
        source_checksum_sha256=_checksum(
            {
                "loop_checksum": _checksum(case.model_dump(mode="json", exclude={"ads_outcome"})),
                "step": "initial",
            }
        ),
        snapshot=snapshot,
        rule_set=base.rule_set,
    )


def _build_local_intake_fixture(
    context_fixture: ContextFixture,
    trigger_fixture: TriggerFixture,
    work_item,
    preparation_context,
) -> CreativeIntakeFixture:
    sku = work_item.target_sku_set[0]
    version_refs = (
        str(work_item.prompt_version),
        str(work_item.rubric_version),
        str(work_item.policy_version),
        str(work_item.rule_version),
        str(work_item.workflow_version),
    )
    context = CreativeContextSnapshot(
        snapshot_id=context_fixture.snapshot_id,
        version=context_fixture.version,
        brand_id=work_item.marketing_scope.brand,
        sku_id=sku.sku_id,
        market=work_item.marketing_scope.market,
        objective=work_item.objective,
        channel=work_item.channel,
        product_image_count=context_fixture.product_image_count or 0,
        persona_count=context_fixture.persona_count or 0,
        output_width=context_fixture.output_width or 0,
        output_height=context_fixture.output_height or 0,
        version_refs=version_refs,
        resolved_context_refs=context_fixture.resolved_context_refs,
        components=tuple(
            ContextEvidence(
                component=component.component,
                status=component.status,
                evidence_refs=component.evidence_refs,
                observed_at=component.observed_at,
                valid_until=component.valid_until,
                detail=component.detail,
            )
            for component in context_fixture.components
        ),
        evidence_refs=tuple(source.source_id for source in preparation_context.sources),
        captured_at=context_fixture.captured_at,
    )
    trigger_data = trigger_fixture.model_dump(mode="json")
    trigger_data["requested_at"] = trigger_fixture.requested_at
    trigger = CreativeTaskTrigger(**trigger_data)
    return CreativeIntakeFixture(
        (
            CreativeIntakeCase(
                request=CreativeIntakeRequest(
                    trigger=trigger,
                    context=context,
                    source_checksum_sha256=intake_fingerprint(
                        trigger,
                        context,
                        work_item,
                        preparation_context,
                    ),
                ),
                work_item_template=work_item,
                context_template=preparation_context,
            ),
        )
    )


def load_creative_loop_fixture(path: Path) -> CreativeLoopFixture:
    raw = path.read_text(encoding="utf-8")
    data = _FixtureFile.model_validate_json(raw)
    root = path.resolve().parent
    performance = load_performance_decision_fixture((root / data.performance_fixture).resolve())
    intake = load_creative_intake_fixture((root / data.intake_fixture).resolve())
    performance_by_source = {item.source_run_id: item for item in performance.requests()}
    cases: list[CreativeLoopInput] = []
    ads_outcomes: list[tuple[str, AdsOutcome]] = []
    for item in data.cases:
        base = performance_by_source.get(item.initial_performance_source_run_id)
        if base is None:
            raise ValueError("Initial Performance fixture case not found")
        checksum = _checksum(item.model_dump(mode="json", exclude={"ads_outcome"}))
        cases.append(
            CreativeLoopInput(
                input_snapshot_id=item.case_id,
                source_run_id=item.source_run_id,
                source_checksum_sha256=checksum,
                context_snapshot_id=item.context_snapshot_id,
                initial_performance=_initial_request(base, item, intake),
                intake_template=intake,
            )
        )
        ads_outcomes.append(
            (
                item.case_id,
                AdsOutcome(
                    creative_version_id=None,
                    **item.ads_outcome.model_dump(),
                ),
            )
        )
    return CreativeLoopFixture(tuple(cases), tuple(ads_outcomes))


def load_local_creative_loop_case(
    case_path: Path,
    *,
    max_context_bytes: int = 131072,
) -> CreativeLoopFixture:
    """Build one local loop from an M1 case and one explicit Ads event."""
    if not case_path.is_file():
        raise ValueError(f"Local Creative loop file does not exist: {case_path}")
    local = _LocalLoopFile.model_validate_json(case_path.read_text(encoding="utf-8"))
    preparation = load_preparation_case(
        case_path.parent / "work-item.json",
        case_path.parent / "context.json",
        max_context_bytes=max_context_bytes,
    )
    work_item = preparation.work_item
    preparation_context = preparation.context
    sku = work_item.target_sku_set[0]
    observed_at = local.captured_at
    source_by_category = {
        source.category: source.source_id for source in preparation_context.sources
    }
    component_evidence = {
        ContextComponent.BRAND: source_by_category["brand"],
        ContextComponent.PRODUCT: f"work-item:{sku.sku_id}",
        ContextComponent.PERSONA: source_by_category["persona"],
        ContextComponent.POLICY: source_by_category["brand"],
        ContextComponent.OUTPUT: f"work-item:{sku.sku_id}",
        ContextComponent.VERSIONS: source_by_category["brand"],
    }
    components = tuple(
        ComponentFixture(
            component=component,
            status=ComponentStatus.KNOWN,
            evidence_refs=(component_evidence[component],),
            observed_at=observed_at,
        )
        for component in component_evidence
    )
    trigger = TriggerFixture(
        trigger_id=f"{local.case_id}-performance-trigger",
        source="performance_demand",
        source_preview_id=f"{local.case_id}-performance-preview",
        source_decision_ref=f"{local.case_id}-performance-decision",
        source_released=True,
        brand_id=work_item.marketing_scope.brand,
        sku_id=sku.sku_id,
        action="request_new_creative",
        objective=work_item.objective,
        channel=work_item.channel,
        evidence_refs=(f"{local.case_id}-performance-evidence",),
        requested_at=observed_at,
    )
    intake_fixture = _build_local_intake_fixture(
        ContextFixture(
            snapshot_id=f"{local.case_id}-context",
            version="local-v1",
            work_item_fixture=Path("work-item.json"),
            context_fixture=Path("context.json"),
            captured_at=observed_at,
            components=components,
            product_image_count=len(sku.product_metadata.image_refs),
            persona_count=len(preparation_context.personas),
            output_width=sku.creative_constraints.format_spec.width,
            output_height=sku.creative_constraints.format_spec.height,
            version_ref_count=5,
            resolved_context_refs=(
                f"idea:{work_item.source_run_id}",
                f"creative_version:{work_item.source_run_id}-v1",
            ),
        ),
        trigger,
        work_item,
        preparation_context,
    )
    checksum = _checksum(local.model_dump(mode="json", exclude={"ads_outcome"}))
    return CreativeLoopFixture(
        cases=(
            CreativeLoopInput(
                input_snapshot_id=local.case_id,
                source_run_id=local.source_run_id,
                source_checksum_sha256=checksum,
                context_snapshot_id=f"{local.case_id}-context",
                initial_performance=_build_local_performance(
                    local,
                    work_item=work_item,
                    sku=sku,
                    preparation_pack_hash=preparation_context.pack_hash,
                ),
                intake_template=intake_fixture,
            ),
        ),
        ads_outcomes=(
            (
                local.case_id,
                AdsOutcome(creative_version_id=None, **local.ads_outcome.model_dump()),
            ),
        ),
    )


__all__ = [
    "AdsOutcomeFixture",
    "CreativeLoopFixture",
    "load_creative_loop_fixture",
    "load_local_creative_loop_case",
]
