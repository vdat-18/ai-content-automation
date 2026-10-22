"""Stable JSON representation for Email report persistence and artifacts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ..domain.models import (
    AttributionDefinition,
    EmailPerformanceReport,
    MetricDefinition,
    MetricObservation,
    MetricResult,
    MetricUnit,
    MetricValue,
    MetricValueStatus,
    ReconciliationRule,
    ReportIssue,
    ReportIssueSeverity,
    ReportSpecification,
    ReportStatus,
    ReportType,
    ReportWindow,
    SnapshotPeriod,
    SourceSnapshot,
    SourceSystem,
)


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _window_to_dict(window: ReportWindow) -> dict[str, str]:
    return {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "timezone": window.timezone,
    }


def _window_from_dict(data: dict[str, Any]) -> ReportWindow:
    return ReportWindow(
        start=datetime.fromisoformat(data["start"]),
        end=datetime.fromisoformat(data["end"]),
        timezone=data["timezone"],
    )


def _definition_to_dict(metric: MetricDefinition) -> dict[str, Any]:
    return {
        "metric_id": metric.metric_id,
        "display_name": metric.display_name,
        "source": metric.source.value,
        "source_metric_id": metric.source_metric_id,
        "integration_id": metric.integration_id,
        "unit": metric.unit.value,
        "grain": metric.grain,
        "required": metric.required,
    }


def _definition_from_dict(data: dict[str, Any]) -> MetricDefinition:
    return MetricDefinition(
        metric_id=data["metric_id"],
        display_name=data["display_name"],
        source=SourceSystem(data["source"]),
        source_metric_id=data["source_metric_id"],
        integration_id=data["integration_id"],
        unit=MetricUnit(data["unit"]),
        grain=data["grain"],
        required=data.get("required", True),
    )


def _specification_to_dict(specification: ReportSpecification) -> dict[str, Any]:
    return {
        "source_run_id": specification.source_run_id,
        "report_type": specification.report_type.value,
        "brand_id": specification.brand_id,
        "account_id": specification.account_id,
        "subject_id": specification.subject_id,
        "current_window": _window_to_dict(specification.current_window),
        "baseline_window": _window_to_dict(specification.baseline_window),
        "attribution": {
            "attribution_id": specification.attribution.attribution_id,
            "version": specification.attribution.version,
            "description": specification.attribution.description,
        },
        "metric_version": specification.metric_version,
        "metrics": [_definition_to_dict(metric) for metric in specification.metrics],
        "reconciliation_rules": [
            {
                "rule_id": rule.rule_id,
                "left_metric_id": rule.left_metric_id,
                "right_metric_id": rule.right_metric_id,
                "absolute_tolerance": str(rule.absolute_tolerance),
                "description": rule.description,
            }
            for rule in specification.reconciliation_rules
        ],
    }


def _specification_from_dict(data: dict[str, Any]) -> ReportSpecification:
    attribution = data["attribution"]
    return ReportSpecification(
        source_run_id=data["source_run_id"],
        report_type=ReportType(data["report_type"]),
        brand_id=data["brand_id"],
        account_id=data["account_id"],
        subject_id=data["subject_id"],
        current_window=_window_from_dict(data["current_window"]),
        baseline_window=_window_from_dict(data["baseline_window"]),
        attribution=AttributionDefinition(
            attribution_id=attribution["attribution_id"],
            version=attribution["version"],
            description=attribution["description"],
        ),
        metric_version=data["metric_version"],
        metrics=tuple(_definition_from_dict(metric) for metric in data["metrics"]),
        reconciliation_rules=tuple(
            ReconciliationRule(
                rule_id=rule["rule_id"],
                left_metric_id=rule["left_metric_id"],
                right_metric_id=rule["right_metric_id"],
                absolute_tolerance=Decimal(rule["absolute_tolerance"]),
                description=rule["description"],
            )
            for rule in data.get("reconciliation_rules", ())
        ),
    )


def _snapshot_to_dict(snapshot: SourceSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "source": snapshot.source.value,
        "period": snapshot.period.value,
        "account_id": snapshot.account_id,
        "window": _window_to_dict(snapshot.window),
        "attribution_id": snapshot.attribution_id,
        "query_version": snapshot.query_version,
        "observed_at": snapshot.observed_at.isoformat(),
        "observations": [
            {
                "source_metric_id": observation.source_metric_id,
                "integration_id": observation.integration_id,
                "display_name": observation.display_name,
                "unit": observation.unit.value,
                "status": observation.status.value,
                "value": _decimal(observation.value),
                "reason": observation.reason,
            }
            for observation in snapshot.observations
        ],
    }


def _snapshot_from_dict(data: dict[str, Any]) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id=data["snapshot_id"],
        source=SourceSystem(data["source"]),
        period=SnapshotPeriod(data["period"]),
        account_id=data["account_id"],
        window=_window_from_dict(data["window"]),
        attribution_id=data.get("attribution_id"),
        query_version=data["query_version"],
        observed_at=datetime.fromisoformat(data["observed_at"]),
        observations=tuple(
            MetricObservation(
                source_metric_id=item["source_metric_id"],
                integration_id=item["integration_id"],
                display_name=item["display_name"],
                unit=MetricUnit(item["unit"]),
                status=MetricValueStatus(item["status"]),
                value=Decimal(item["value"]) if item.get("value") is not None else None,
                reason=item.get("reason"),
            )
            for item in data["observations"]
        ),
    )


def report_to_dict(report: EmailPerformanceReport) -> dict[str, Any]:
    """Convert a report into a JSON-compatible versioned payload."""
    return {
        "schema_version": 1,
        "report_id": report.report_id,
        "specification": _specification_to_dict(report.specification),
        "status": report.status.value,
        "snapshots": [_snapshot_to_dict(snapshot) for snapshot in report.snapshots],
        "metrics": [
            {
                "definition": _definition_to_dict(metric.definition),
                "current": {
                    "status": metric.current.status.value,
                    "value": _decimal(metric.current.value),
                    "snapshot_id": metric.current.snapshot_id,
                    "reason": metric.current.reason,
                },
                "baseline": {
                    "status": metric.baseline.status.value,
                    "value": _decimal(metric.baseline.value),
                    "snapshot_id": metric.baseline.snapshot_id,
                    "reason": metric.baseline.reason,
                },
                "delta": _decimal(metric.delta),
                "change_rate": _decimal(metric.change_rate),
            }
            for metric in report.metrics
        ],
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "detail": issue.detail,
                "source_ref": issue.source_ref,
            }
            for issue in report.issues
        ],
        "created_at": report.created_at.isoformat(),
        "artifact_ref": report.artifact_ref,
        "audit_log": list(report.audit_log),
    }


def _value_from_dict(data: dict[str, Any]) -> MetricValue:
    return MetricValue(
        status=MetricValueStatus(data["status"]),
        value=Decimal(data["value"]) if data.get("value") is not None else None,
        snapshot_id=data.get("snapshot_id"),
        reason=data.get("reason"),
    )


def report_from_dict(data: dict[str, Any]) -> EmailPerformanceReport:
    """Restore a report payload persisted by :func:`report_to_dict`."""
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported Email report schema version")
    return EmailPerformanceReport(
        report_id=data["report_id"],
        specification=_specification_from_dict(data["specification"]),
        status=ReportStatus(data["status"]),
        snapshots=tuple(_snapshot_from_dict(snapshot) for snapshot in data["snapshots"]),
        metrics=tuple(
            MetricResult(
                definition=_definition_from_dict(metric["definition"]),
                current=_value_from_dict(metric["current"]),
                baseline=_value_from_dict(metric["baseline"]),
                delta=Decimal(metric["delta"]) if metric.get("delta") is not None else None,
                change_rate=(
                    Decimal(metric["change_rate"])
                    if metric.get("change_rate") is not None
                    else None
                ),
            )
            for metric in data["metrics"]
        ),
        issues=tuple(
            ReportIssue(
                code=issue["code"],
                severity=ReportIssueSeverity(issue["severity"]),
                detail=issue["detail"],
                source_ref=issue.get("source_ref"),
            )
            for issue in data["issues"]
        ),
        created_at=datetime.fromisoformat(data["created_at"]),
        artifact_ref=data.get("artifact_ref"),
        audit_log=tuple(data.get("audit_log", ())),
    )


__all__ = ["report_from_dict", "report_to_dict"]
