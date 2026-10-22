"""Strict synthetic fixture loader for Email Operations health."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..application.evaluation import EmailHealthRequest
from ..domain.models import (
    EmailHealthClassification,
    EmailHealthRule,
    EmailHealthRuleSet,
    EmailHealthSubject,
    EmailHealthSubjectType,
    EmailOperationsSnapshot,
    HealthObservation,
    HealthObservationName,
    HealthRuleOperator,
    HealthRuleStatus,
    HealthSeverity,
    ObservationStatus,
    ObservationValueType,
    RemediationAction,
)


class SubjectFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_type: EmailHealthSubjectType
    subject_id: str
    brand_id: str
    account_id: str
    source_system: str
    integration_id: str | None = None


class ObservationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: HealthObservationName
    status: ObservationStatus
    value_type: ObservationValueType
    account_id: str | None = None
    source_system: str | None = None
    integration_id: str | None = None
    source_ref: str | None = None
    observed_at: datetime
    boolean_value: bool | None = None
    decimal_value: Decimal | None = None
    text_value: str | None = None
    reason: str | None = None


class SnapshotFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    subject: SubjectFixture
    timezone: str
    source_version: str
    observations: list[ObservationFixture] = Field(min_length=1)
    observed_at: datetime
    upstream_report_refs: list[str] = Field(default_factory=list)


class RuleFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    subject_type: EmailHealthSubjectType
    observation: HealthObservationName
    operator: HealthRuleOperator
    severity: HealthSeverity
    failure_classification: EmailHealthClassification
    recommendation: RemediationAction
    description: str
    expected_boolean: bool | None = None
    threshold_decimal: Decimal | None = None
    expected_text: str | None = None
    sample_observation: HealthObservationName | None = None
    minimum_sample: Decimal | None = None


class RuleSetFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_set_id: str
    version: str
    status: HealthRuleStatus
    effective_at: datetime
    source: str
    rules: list[RuleFixture] = Field(min_length=1)


class EmailHealthCaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_run_id: str
    snapshot: SnapshotFixture
    rule_set_ref: str

    def request(self, rule_set_fixture: RuleSetFixture) -> EmailHealthRequest:
        snapshot = EmailOperationsSnapshot(
            snapshot_id=self.snapshot.snapshot_id,
            subject=EmailHealthSubject(**self.snapshot.subject.model_dump()),
            timezone=self.snapshot.timezone,
            source_version=self.snapshot.source_version,
            observations=tuple(
                HealthObservation(
                    **item.model_dump(exclude={"account_id", "source_system", "integration_id"}),
                    account_id=item.account_id or self.snapshot.subject.account_id,
                    source_system=item.source_system or self.snapshot.subject.source_system,
                    integration_id=(
                        item.integration_id
                        if item.integration_id is not None
                        else self.snapshot.subject.integration_id
                    ),
                )
                for item in self.snapshot.observations
            ),
            observed_at=self.snapshot.observed_at,
            upstream_report_refs=tuple(self.snapshot.upstream_report_refs),
        )
        rule_set = EmailHealthRuleSet(
            rule_set_id=rule_set_fixture.rule_set_id,
            version=rule_set_fixture.version,
            status=rule_set_fixture.status,
            effective_at=rule_set_fixture.effective_at,
            source=rule_set_fixture.source,
            rules=tuple(EmailHealthRule(**item.model_dump()) for item in rule_set_fixture.rules),
        )
        canonical = json.dumps(
            {
                "case": self.model_dump(mode="json"),
                "rule_set": rule_set_fixture.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return EmailHealthRequest(
            source_run_id=self.source_run_id,
            source_checksum_sha256=hashlib.sha256(canonical).hexdigest(),
            snapshot=snapshot,
            rule_set=rule_set,
        )


class EmailHealthFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_sets: list[RuleSetFixture] = Field(min_length=1)
    cases: list[EmailHealthCaseFixture] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> EmailHealthFixture:
        source_ids = [item.source_run_id for item in self.cases]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Email health source_run_id values must be unique")
        rule_sets = {item.rule_set_id: item for item in self.rule_sets}
        if len(rule_sets) != len(self.rule_sets):
            raise ValueError("Email health rule_set_id values must be unique")
        for case in self.cases:
            rule_set = rule_sets.get(case.rule_set_ref)
            if rule_set is None:
                raise ValueError(f"Unknown rule_set_ref {case.rule_set_ref}")
            if case.snapshot.subject.subject_type not in {
                item.subject_type for item in rule_set.rules
            }:
                raise ValueError("Rule set does not cover the snapshot subject type")
        return self

    def requests(self) -> tuple[EmailHealthRequest, ...]:
        rule_sets = {item.rule_set_id: item for item in self.rule_sets}
        return tuple(case.request(rule_sets[case.rule_set_ref]) for case in self.cases)


def load_email_health_fixture(path: Path) -> EmailHealthFixture:
    return EmailHealthFixture.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["EmailHealthFixture", "load_email_health_fixture"]
