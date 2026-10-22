"""Versioned JSON and Markdown artifacts for Email performance reports."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import EmailPerformanceReport, MetricValue
from .serialization import report_to_dict


def _display(value: MetricValue) -> str:
    if value.value is None:
        return value.status.value.upper()
    return str(value.value)


def _percent(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def write_report_artifacts(
    store: ArtifactStore, report: EmailPerformanceReport
) -> tuple[EmailPerformanceReport, Path]:
    """Write one immutable report directory and return its persisted artifact ref."""
    run_dir = f"email-reports/{report.specification.source_run_id}"
    artifact_ref = f"{run_dir}/manifest.json"
    persisted = replace(report, artifact_ref=artifact_ref)
    manifest = json.dumps(report_to_dict(persisted), ensure_ascii=False, indent=2)
    manifest_path = store.write_text(manifest, *artifact_ref.split("/"))

    lines = [
        f"# Email performance report: {report.specification.subject_id}",
        "",
        f"- Status: `{report.status.value}`",
        f"- Brand: `{report.specification.brand_id}`",
        f"- Account: `{report.specification.account_id}`",
        f"- Attribution: `{report.specification.attribution.attribution_id}` "
        f"v{report.specification.attribution.version}",
        f"- Metric contract: `{report.specification.metric_version}`",
        "",
        "| Metric | Current | Baseline | Delta | Change | Source snapshot |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for metric in report.metrics:
        lines.append(
            "| "
            + " | ".join(
                (
                    metric.definition.display_name,
                    _display(metric.current),
                    _display(metric.baseline),
                    str(metric.delta) if metric.delta is not None else "n/a",
                    _percent(metric.change_rate),
                    metric.current.snapshot_id or "n/a",
                )
            )
            + " |"
        )
    if report.issues:
        lines.extend(("", "## Data exceptions", ""))
        lines.extend(
            f"- `{issue.severity.value}` `{issue.code}`: {issue.detail}" for issue in report.issues
        )
    lines.extend(
        (
            "",
            "> Aggregate synthetic/read-only report. Unknown values are not zero and no "
            "customer-level data is stored.",
        )
    )
    store.write_text("\n".join(lines) + "\n", run_dir, "report.md")
    return persisted, manifest_path


__all__ = ["write_report_artifacts"]
