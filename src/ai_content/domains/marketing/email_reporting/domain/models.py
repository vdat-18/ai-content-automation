"""Business records for aggregate, read-only Email Marketing reports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _require_identifier(value: str, field_name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a non-empty stable identifier")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")


class SourceSystem(StrEnum):
    KLAVIYO = "klaviyo"
    SHOPIFY = "shopify"


class SnapshotPeriod(StrEnum):
    CURRENT = "current"
    BASELINE = "baseline"


class ReportType(StrEnum):
    CAMPAIGN_POST_SEND = "campaign_post_send"
    MONTHLY_BRAND = "monthly_brand"


class ReportStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class MetricValueStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class MetricUnit(StrEnum):
    MONEY = "money"
    COUNT = "count"
    RATE = "rate"


class ReportIssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class ReportWindow:
    start: datetime
    end: datetime
    timezone: str

    def __post_init__(self) -> None:
        _require_aware(self.start, "window.start")
        _require_aware(self.end, "window.end")
        if self.end <= self.start:
            raise ValueError("Report window end must be after start")
        if not self.timezone.strip():
            raise ValueError("Report window timezone is required")


@dataclass(frozen=True)
class AttributionDefinition:
    attribution_id: str
    version: str
    description: str

    def __post_init__(self) -> None:
        _require_identifier(self.attribution_id, "attribution_id")
        if not self.version.strip() or not self.description.strip():
            raise ValueError("Attribution version and description are required")


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    display_name: str
    source: SourceSystem
    source_metric_id: str
    integration_id: str
    unit: MetricUnit
    grain: str
    required: bool = True

    def __post_init__(self) -> None:
        _require_identifier(self.metric_id, "metric_id")
        _require_identifier(self.source_metric_id, "source_metric_id")
        _require_identifier(self.integration_id, "integration_id")
        if not self.display_name.strip() or not self.grain.strip():
            raise ValueError("Metric display name and grain are required")


@dataclass(frozen=True)
class ReconciliationRule:
    rule_id: str
    left_metric_id: str
    right_metric_id: str
    absolute_tolerance: Decimal
    description: str

    def __post_init__(self) -> None:
        _require_identifier(self.rule_id, "rule_id")
        if self.absolute_tolerance < 0:
            raise ValueError("Reconciliation tolerance cannot be negative")
        if not self.description.strip():
            raise ValueError("Reconciliation rule description is required")


@dataclass(frozen=True)
class ReportSpecification:
    source_run_id: str
    report_type: ReportType
    brand_id: str
    account_id: str
    subject_id: str
    current_window: ReportWindow
    baseline_window: ReportWindow
    attribution: AttributionDefinition
    metric_version: str
    metrics: tuple[MetricDefinition, ...]
    reconciliation_rules: tuple[ReconciliationRule, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("source_run_id", "brand_id", "account_id", "subject_id"):
            _require_identifier(getattr(self, field_name), field_name)
        if not self.metric_version.strip():
            raise ValueError("metric_version is required")
        if not self.metrics:
            raise ValueError("At least one metric definition is required")
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("Metric IDs must be unique")
        known = set(metric_ids)
        for rule in self.reconciliation_rules:
            if rule.left_metric_id not in known or rule.right_metric_id not in known:
                raise ValueError(f"Reconciliation rule {rule.rule_id} references an unknown metric")


@dataclass(frozen=True)
class MetricObservation:
    source_metric_id: str
    integration_id: str
    display_name: str
    unit: MetricUnit
    status: MetricValueStatus
    value: Decimal | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.source_metric_id, "source_metric_id")
        _require_identifier(self.integration_id, "integration_id")
        if self.status == MetricValueStatus.KNOWN and self.value is None:
            raise ValueError("Known metric observations require a value")
        if self.status != MetricValueStatus.KNOWN and self.value is not None:
            raise ValueError("Unknown or not-applicable observations cannot carry a value")
        if self.status != MetricValueStatus.KNOWN and not self.reason:
            raise ValueError("Unknown or not-applicable observations require a reason")


@dataclass(frozen=True)
class SourceSnapshot:
    snapshot_id: str
    source: SourceSystem
    period: SnapshotPeriod
    account_id: str
    window: ReportWindow
    attribution_id: str | None
    query_version: str
    observed_at: datetime
    observations: tuple[MetricObservation, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.snapshot_id, "snapshot_id")
        _require_identifier(self.account_id, "account_id")
        _require_aware(self.observed_at, "observed_at")
        if not self.query_version.strip():
            raise ValueError("query_version is required")


@dataclass(frozen=True)
class MetricValue:
    status: MetricValueStatus
    value: Decimal | None
    snapshot_id: str | None
    reason: str | None = None


@dataclass(frozen=True)
class MetricResult:
    definition: MetricDefinition
    current: MetricValue
    baseline: MetricValue
    delta: Decimal | None
    change_rate: Decimal | None


@dataclass(frozen=True)
class ReportIssue:
    code: str
    severity: ReportIssueSeverity
    detail: str
    source_ref: str | None = None


@dataclass(frozen=True)
class EmailPerformanceReport:
    report_id: str
    specification: ReportSpecification
    status: ReportStatus
    snapshots: tuple[SourceSnapshot, ...]
    metrics: tuple[MetricResult, ...]
    issues: tuple[ReportIssue, ...]
    created_at: datetime
    artifact_ref: str | None = None
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_identifier(self.report_id, "report_id")
        _require_aware(self.created_at, "created_at")
