"""Strict synthetic fixture loader for Performance decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..application.evaluation import PerformanceDecisionRequest
from ..domain.models import (
    ClassificationRule,
    ComparisonOperator,
    MetricName,
    MetricObservation,
    MetricStatus,
    PerformanceClassification,
    PerformanceRuleSet,
    PerformanceSnapshot,
    PerformanceSubject,
    RecommendationAction,
    RuleCriterion,
    RuleMode,
    RuleStatus,
    SubjectType,
)


class SubjectFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_type: SubjectType
    subject_id: str
    brand_id: str
    store_id: str
    sku_id: str
    platform: str
    creative_id: str | None = None
    angle_id: str | None = None
    concept_id: str | None = None
    persona_id: str | None = None
    raw_source_name: str | None = None


class MetricFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: MetricName
    window_id: str
    status: MetricStatus
    value: Decimal | None = None
    unit: str
    source_ref: str | None = None
    observed_at: datetime


class SnapshotFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    subject: SubjectFixture
    objective: str
    channel: str
    timezone: str
    attribution: str
    currency: str
    source_version: str
    metrics: list[MetricFixture] = Field(min_length=1)
    observed_at: datetime


class CriterionFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    metric: MetricName
    window_id: str
    operator: ComparisonOperator
    threshold: Decimal


class RuleFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    subject_type: SubjectType
    classification: PerformanceClassification
    recommendation: RecommendationAction
    criteria: list[CriterionFixture] = Field(min_length=1)
    required_passes: int = Field(ge=1)


class RuleSetFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_set_id: str
    version: str
    status: RuleStatus
    mode: RuleMode
    effective_at: datetime
    rules: list[RuleFixture] = Field(min_length=1)


class DecisionCaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_run_id: str
    snapshot: SnapshotFixture
    rule_set_ref: str

    def request(self, rule_set_fixture: RuleSetFixture) -> PerformanceDecisionRequest:
        snapshot_data = self.snapshot
        snapshot = PerformanceSnapshot(
            snapshot_id=snapshot_data.snapshot_id,
            subject=PerformanceSubject(**snapshot_data.subject.model_dump()),
            objective=snapshot_data.objective,
            channel=snapshot_data.channel,
            timezone=snapshot_data.timezone,
            attribution=snapshot_data.attribution,
            currency=snapshot_data.currency,
            source_version=snapshot_data.source_version,
            metrics=tuple(
                MetricObservation(**metric.model_dump()) for metric in snapshot_data.metrics
            ),
            observed_at=snapshot_data.observed_at,
        )
        rules = tuple(
            ClassificationRule(
                rule_id=rule.rule_id,
                subject_type=rule.subject_type,
                classification=rule.classification,
                recommendation=rule.recommendation,
                criteria=tuple(
                    RuleCriterion(**criterion.model_dump()) for criterion in rule.criteria
                ),
                required_passes=rule.required_passes,
            )
            for rule in rule_set_fixture.rules
        )
        rule_set = PerformanceRuleSet(
            rule_set_id=rule_set_fixture.rule_set_id,
            version=rule_set_fixture.version,
            status=rule_set_fixture.status,
            mode=rule_set_fixture.mode,
            effective_at=rule_set_fixture.effective_at,
            rules=rules,
        )
        canonical = json.dumps(
            {
                "case": self.model_dump(mode="json"),
                "rule_set": rule_set_fixture.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return PerformanceDecisionRequest(
            source_run_id=self.source_run_id,
            source_checksum_sha256=hashlib.sha256(canonical).hexdigest(),
            snapshot=snapshot,
            rule_set=rule_set,
        )


class PerformanceDecisionFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_sets: list[RuleSetFixture] = Field(min_length=1)
    cases: list[DecisionCaseFixture] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> PerformanceDecisionFixture:
        source_ids = [case.source_run_id for case in self.cases]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Performance decision source_run_id values must be unique")
        rules = {item.rule_set_id: item for item in self.rule_sets}
        if len(rules) != len(self.rule_sets):
            raise ValueError("Performance rule_set_id values must be unique")
        for case in self.cases:
            rule_set = rules.get(case.rule_set_ref)
            if rule_set is None:
                raise ValueError(f"Unknown rule_set_ref {case.rule_set_ref}")
            supported = {rule.subject_type for rule in rule_set.rules}
            if case.snapshot.subject.subject_type not in supported:
                raise ValueError("Rule set does not cover the snapshot subject type")
        return self

    def requests(self) -> tuple[PerformanceDecisionRequest, ...]:
        rules = {item.rule_set_id: item for item in self.rule_sets}
        return tuple(case.request(rules[case.rule_set_ref]) for case in self.cases)


def load_performance_decision_fixture(path: Path) -> PerformanceDecisionFixture:
    return PerformanceDecisionFixture.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["PerformanceDecisionFixture", "load_performance_decision_fixture"]
