"""Human- and machine-readable Email Operations health artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import EmailHealthRun
from .serialization import run_to_dict


def write_email_health_artifacts(store: ArtifactStore, run: EmailHealthRun) -> Path:
    parts = ("email-health", run.source_run_id)
    manifest = store.write_text(
        json.dumps(run_to_dict(run), ensure_ascii=False, indent=2), *parts, "manifest.json"
    )
    evaluation = run.evaluation
    subject = run.snapshot.subject
    lines = [
        f"# Email Operations health: {subject.subject_id}",
        "",
        "Synthetic/local guardrail. No campaign, flow, segment, suppression or coupon was changed.",
        "",
        f"- Brand / account: `{subject.brand_id}` / `{subject.account_id}`",
        f"- Subject: `{subject.subject_type.value}` / `{subject.subject_id}`",
        f"- Classification: `{evaluation.classification.value}`",
        f"- Evaluation state: `{evaluation.state.value}`",
        f"- Issue state: `{run.issue_state.value}`",
        f"- Rule: `{evaluation.rule_set_id}@{evaluation.rule_version}` "
        f"(`{evaluation.rule_status.value}`)",
        f"- Rule source: {evaluation.rule_source}",
        f"- Decision: `{run.decision.value if run.decision else 'pending'}`",
        f"- Fingerprint: `{run.issue_fingerprint}`",
        "",
        "## Checks",
        "",
    ]
    for assessment in evaluation.assessments:
        lines.append(
            f"- `{assessment.rule_id}`: `{assessment.outcome.value}` "
            f"(`{assessment.severity.value}`); observed "
            f"`{assessment.observed_value or 'UNKNOWN'}`; expected "
            f"`{assessment.operator.value} {assessment.expected_value}` - {assessment.detail}"
        )
    store.write_text("\n".join(lines) + "\n", *parts, "health_report.md")
    preview = run.remediation_preview
    preview_payload: dict[str, object] = {
        "available": preview is not None,
        "note": "Preview only; this artifact performs no external action.",
    }
    if preview is not None:
        preview_payload.update(
            {
                "preview_id": preview.preview_id,
                "state": preview.state.value,
                "action": preview.action.value,
                "checklist": list(preview.checklist),
                "evidence_refs": list(preview.evidence_refs),
                "missing_evidence": [item.value for item in preview.missing_evidence],
                "prohibited_external_actions": list(preview.prohibited_external_actions),
            }
        )
    store.write_text(
        json.dumps(preview_payload, ensure_ascii=False, indent=2),
        *parts,
        "remediation_preview.json",
    )
    return manifest


__all__ = ["write_email_health_artifacts"]
