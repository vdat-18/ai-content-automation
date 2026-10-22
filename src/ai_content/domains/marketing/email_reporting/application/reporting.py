"""Build traceable Email reports from aggregate source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ..domain.models import (
    EmailPerformanceReport,
    MetricDefinition,
    MetricResult,
    MetricValue,
    MetricValueStatus,
    ReportIssue,
    ReportIssueSeverity,
    ReportSpecification,
    ReportStatus,
    SnapshotPeriod,
    SourceSnapshot,
    SourceSystem,
)
from ..ports.interfaces import IEmailReportingSource, IEmailReportRepository, ReportingSourceError


@dataclass(frozen=True)
class EmailReportRunResult:
    report: EmailPerformanceReport
    duplicate: bool = False


class RunEmailReport:
    """Read, validate and reconcile one versioned Email report specification."""

    def __init__(
        self,
        sources: dict[SourceSystem, IEmailReportingSource],
        repository: IEmailReportRepository,
    ) -> None:
        self._sources = sources
        self._repository = repository

    async def execute(self, specification: ReportSpecification) -> EmailReportRunResult:
        existing = await self._repository.get_by_source_run_id(specification.source_run_id)
        if existing is not None:
            return EmailReportRunResult(existing, duplicate=True)

        snapshots, issues = await self._collect(specification)
        metrics = tuple(
            self._metric_result(definition, snapshots, issues)
            for definition in specification.metrics
        )
        self._reconcile(specification, metrics, issues)
        status = self._status(issues)
        report = EmailPerformanceReport(
            report_id=f"email-report-{uuid4().hex}",
            specification=specification,
            status=status,
            snapshots=tuple(snapshots),
            metrics=metrics,
            issues=tuple(issues),
            created_at=datetime.now(UTC),
            audit_log=(
                "aggregate_sources_collected",
                "metric_identity_validated",
                "reconciliation_completed",
            ),
        )
        return EmailReportRunResult(report)

    async def _collect(
        self, specification: ReportSpecification
    ) -> tuple[list[SourceSnapshot], list[ReportIssue]]:
        snapshots: list[SourceSnapshot] = []
        issues: list[ReportIssue] = []
        required_sources = {metric.source for metric in specification.metrics}
        for source_system in sorted(required_sources, key=lambda item: item.value):
            source = self._sources.get(source_system)
            if source is None:
                issues.append(
                    ReportIssue(
                        code="source_not_configured",
                        severity=ReportIssueSeverity.BLOCKING,
                        detail=f"No read-only source is configured for {source_system.value}",
                        source_ref=source_system.value,
                    )
                )
                continue
            for period, window in (
                (SnapshotPeriod.CURRENT, specification.current_window),
                (SnapshotPeriod.BASELINE, specification.baseline_window),
            ):
                try:
                    snapshot = await source.fetch(specification, period, window)
                except ReportingSourceError as exc:
                    issues.append(
                        ReportIssue(
                            code="source_read_failed",
                            severity=ReportIssueSeverity.BLOCKING,
                            detail=str(exc),
                            source_ref=f"{source_system.value}:{period.value}",
                        )
                    )
                    continue
                issues.extend(
                    self._validate_snapshot(specification, source_system, period, window, snapshot)
                )
                snapshots.append(snapshot)
        return snapshots, issues

    @staticmethod
    def _validate_snapshot(
        specification: ReportSpecification,
        source: SourceSystem,
        period: SnapshotPeriod,
        window,
        snapshot: SourceSnapshot,
    ) -> list[ReportIssue]:
        mismatches = []
        if snapshot.source != source:
            mismatches.append("source")
        if snapshot.period != period:
            mismatches.append("period")
        if snapshot.account_id != specification.account_id:
            mismatches.append("account_id")
        if snapshot.window != window:
            mismatches.append("window_or_timezone")
        if source == SourceSystem.KLAVIYO and (
            snapshot.attribution_id != specification.attribution.attribution_id
        ):
            mismatches.append("attribution_id")
        if not mismatches:
            return []
        return [
            ReportIssue(
                code="snapshot_context_mismatch",
                severity=ReportIssueSeverity.BLOCKING,
                detail=f"Snapshot context mismatch: {', '.join(mismatches)}",
                source_ref=snapshot.snapshot_id,
            )
        ]

    @staticmethod
    def _metric_result(
        definition: MetricDefinition,
        snapshots: list[SourceSnapshot],
        issues: list[ReportIssue],
    ) -> MetricResult:
        current = RunEmailReport._resolve_value(
            definition, SnapshotPeriod.CURRENT, snapshots, issues
        )
        baseline = RunEmailReport._resolve_value(
            definition, SnapshotPeriod.BASELINE, snapshots, issues
        )
        delta = None
        change_rate = None
        if (
            current.status == MetricValueStatus.KNOWN
            and baseline.status == MetricValueStatus.KNOWN
            and current.value is not None
            and baseline.value is not None
        ):
            delta = current.value - baseline.value
            if baseline.value != 0:
                change_rate = delta / baseline.value
        return MetricResult(definition, current, baseline, delta, change_rate)

    @staticmethod
    def _resolve_value(
        definition: MetricDefinition,
        period: SnapshotPeriod,
        snapshots: list[SourceSnapshot],
        issues: list[ReportIssue],
    ) -> MetricValue:
        candidates = []
        for snapshot in snapshots:
            if snapshot.source != definition.source or snapshot.period != period:
                continue
            for observation in snapshot.observations:
                if (
                    observation.source_metric_id == definition.source_metric_id
                    and observation.integration_id == definition.integration_id
                ):
                    candidates.append((snapshot, observation))
        if len(candidates) > 1:
            issues.append(
                ReportIssue(
                    code="metric_identity_collision",
                    severity=ReportIssueSeverity.BLOCKING,
                    detail=(
                        f"Metric {definition.metric_id} matched multiple observations for "
                        f"{period.value}"
                    ),
                    source_ref=definition.metric_id,
                )
            )
            return MetricValue(
                MetricValueStatus.UNKNOWN, None, None, "Metric identity is ambiguous"
            )
        if not candidates:
            issues.append(
                ReportIssue(
                    code="metric_missing",
                    severity=(
                        ReportIssueSeverity.BLOCKING
                        if definition.required
                        else ReportIssueSeverity.WARNING
                    ),
                    detail=f"Metric {definition.metric_id} is missing for {period.value}",
                    source_ref=definition.metric_id,
                )
            )
            return MetricValue(MetricValueStatus.UNKNOWN, None, None, "Metric was not observed")
        snapshot, observation = candidates[0]
        if observation.unit != definition.unit:
            issues.append(
                ReportIssue(
                    code="metric_unit_mismatch",
                    severity=ReportIssueSeverity.BLOCKING,
                    detail=f"Metric {definition.metric_id} unit does not match its definition",
                    source_ref=snapshot.snapshot_id,
                )
            )
            return MetricValue(
                MetricValueStatus.UNKNOWN, None, snapshot.snapshot_id, "Metric unit mismatch"
            )
        if observation.status != MetricValueStatus.KNOWN:
            issues.append(
                ReportIssue(
                    code="metric_unknown",
                    severity=(
                        ReportIssueSeverity.BLOCKING
                        if definition.required
                        else ReportIssueSeverity.WARNING
                    ),
                    detail=(
                        f"Metric {definition.metric_id} is {observation.status.value}: "
                        f"{observation.reason}"
                    ),
                    source_ref=snapshot.snapshot_id,
                )
            )
        return MetricValue(
            observation.status,
            observation.value,
            snapshot.snapshot_id,
            observation.reason,
        )

    @staticmethod
    def _reconcile(
        specification: ReportSpecification,
        metrics: tuple[MetricResult, ...],
        issues: list[ReportIssue],
    ) -> None:
        by_id = {metric.definition.metric_id: metric for metric in metrics}
        for rule in specification.reconciliation_rules:
            left = by_id[rule.left_metric_id].current
            right = by_id[rule.right_metric_id].current
            if left.status != MetricValueStatus.KNOWN or right.status != MetricValueStatus.KNOWN:
                issues.append(
                    ReportIssue(
                        code="reconciliation_unavailable",
                        severity=ReportIssueSeverity.BLOCKING,
                        detail=f"Cannot evaluate {rule.rule_id}: a required value is unknown",
                        source_ref=rule.rule_id,
                    )
                )
                continue
            assert left.value is not None and right.value is not None
            if abs(left.value - right.value) > rule.absolute_tolerance:
                issues.append(
                    ReportIssue(
                        code="reconciliation_mismatch",
                        severity=ReportIssueSeverity.BLOCKING,
                        detail=(
                            f"{rule.rule_id} exceeded tolerance {rule.absolute_tolerance}: "
                            f"{left.value} vs {right.value}"
                        ),
                        source_ref=rule.rule_id,
                    )
                )

    @staticmethod
    def _status(issues: list[ReportIssue]) -> ReportStatus:
        if any(issue.severity == ReportIssueSeverity.BLOCKING for issue in issues):
            return ReportStatus.BLOCKED
        if issues:
            return ReportStatus.PARTIAL
        return ReportStatus.READY
