"""Typed, aggregate-only fixtures for the Email reporting walking skeleton."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.models import (
    AttributionDefinition,
    MetricDefinition,
    MetricObservation,
    MetricUnit,
    MetricValueStatus,
    ReconciliationRule,
    ReportSpecification,
    ReportType,
    ReportWindow,
    SnapshotPeriod,
    SourceSnapshot,
    SourceSystem,
)


class WindowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    timezone: str = Field(min_length=1)

    def to_domain(self) -> ReportWindow:
        return ReportWindow(self.start, self.end, self.timezone)


class AttributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribution_id: str
    version: str
    description: str


class MetricDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str
    display_name: str
    source: SourceSystem
    source_metric_id: str
    integration_id: str
    unit: MetricUnit
    grain: str
    required: bool = True


class ReconciliationRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    left_metric_id: str
    right_metric_id: str
    absolute_tolerance: Decimal = Field(ge=0)
    description: str


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_metric_id: str
    integration_id: str
    display_name: str
    unit: MetricUnit
    status: MetricValueStatus
    value: Decimal | None = None
    reason: str | None = None


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    source: SourceSystem
    period: SnapshotPeriod
    account_id: str
    window: WindowInput
    attribution_id: str | None = None
    query_version: str
    observed_at: datetime
    observations: list[ObservationInput]

    def to_domain(self) -> SourceSnapshot:
        return SourceSnapshot(
            snapshot_id=self.snapshot_id,
            source=self.source,
            period=self.period,
            account_id=self.account_id,
            window=self.window.to_domain(),
            attribution_id=self.attribution_id,
            query_version=self.query_version,
            observed_at=self.observed_at,
            observations=tuple(
                MetricObservation(
                    source_metric_id=item.source_metric_id,
                    integration_id=item.integration_id,
                    display_name=item.display_name,
                    unit=item.unit,
                    status=item.status,
                    value=item.value,
                    reason=item.reason,
                )
                for item in self.observations
            ),
        )


class EmailReportFixture(BaseModel):
    """Complete synthetic input for a deterministic Email report run."""

    model_config = ConfigDict(extra="forbid")

    source_run_id: str
    report_type: ReportType
    brand_id: str
    account_id: str
    subject_id: str
    current_window: WindowInput
    baseline_window: WindowInput
    attribution: AttributionInput
    metric_version: str
    metrics: list[MetricDefinitionInput]
    reconciliation_rules: list[ReconciliationRuleInput] = Field(default_factory=list)
    snapshots: list[SnapshotInput]

    @model_validator(mode="after")
    def validate_aggregate_fixture(self) -> EmailReportFixture:
        required = {
            (source, period)
            for source in {metric.source for metric in self.metrics}
            for period in SnapshotPeriod
        }
        available = {(snapshot.source, snapshot.period) for snapshot in self.snapshots}
        if required != available:
            raise ValueError(
                "Fixture must contain exactly one current and baseline snapshot per source"
            )
        if len(available) != len(self.snapshots):
            raise ValueError("Fixture contains duplicate source-period snapshots")
        return self

    def specification(self) -> ReportSpecification:
        return ReportSpecification(
            source_run_id=self.source_run_id,
            report_type=self.report_type,
            brand_id=self.brand_id,
            account_id=self.account_id,
            subject_id=self.subject_id,
            current_window=self.current_window.to_domain(),
            baseline_window=self.baseline_window.to_domain(),
            attribution=AttributionDefinition(
                attribution_id=self.attribution.attribution_id,
                version=self.attribution.version,
                description=self.attribution.description,
            ),
            metric_version=self.metric_version,
            metrics=tuple(
                MetricDefinition(
                    metric_id=metric.metric_id,
                    display_name=metric.display_name,
                    source=metric.source,
                    source_metric_id=metric.source_metric_id,
                    integration_id=metric.integration_id,
                    unit=metric.unit,
                    grain=metric.grain,
                    required=metric.required,
                )
                for metric in self.metrics
            ),
            reconciliation_rules=tuple(
                ReconciliationRule(
                    rule_id=rule.rule_id,
                    left_metric_id=rule.left_metric_id,
                    right_metric_id=rule.right_metric_id,
                    absolute_tolerance=rule.absolute_tolerance,
                    description=rule.description,
                )
                for rule in self.reconciliation_rules
            ),
        )


def load_email_report_fixture(path: Path) -> EmailReportFixture:
    """Read and strictly validate one local aggregate fixture."""
    return EmailReportFixture.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["EmailReportFixture", "load_email_report_fixture"]
