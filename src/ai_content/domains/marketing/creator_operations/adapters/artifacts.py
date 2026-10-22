"""Human- and machine-readable Creator Operations artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import CreatorEvaluationRun
from .serialization import run_to_dict


def write_creator_artifacts(store: ArtifactStore, run: CreatorEvaluationRun) -> Path:
    parts = ("creator-operations", run.source_run_id)
    manifest = store.write_text(
        json.dumps(run_to_dict(run), ensure_ascii=False, indent=2), *parts, "manifest.json"
    )
    latest = run.latest_evaluation
    evaluation_lines = [
        f"# Creator evaluation {run.candidate_id}",
        "",
        "Synthetic/read-only pilot. No creator was contacted and no booking was created.",
        "",
        f"- Campaign: `{run.campaign.campaign_id}`",
        f"- Creator alias: `{run.creator.display_alias}`",
        f"- Evaluation: `v{latest.version_number}` / `{latest.state.value}`",
        f"- Policy: `{latest.policy_version}`",
        f"- Decision: `{run.decision.value if run.decision else 'pending'}`",
        "",
        "## Criteria",
        "",
    ]
    for item in latest.criteria:
        missing = f"; missing: {', '.join(item.missing_fields)}" if item.missing_fields else ""
        evaluation_lines.append(f"- **{item.criterion}:** `{item.outcome.value}`{missing}")
    store.write_text("\n".join(evaluation_lines) + "\n", *parts, "evaluation.md")
    preview_lines = [
        "# Lark Data Preview",
        "",
        "Preview only. This artifact does not write to Lark.",
        "",
        f"- Mapping: `{run.preview.mapping_version}`",
        f"- State: `{run.preview.state.value}`",
        "",
        "| Field | Current | Proposed | Action |",
        "| --- | --- | --- | --- |",
    ]
    for item in run.preview.fields:
        preview_lines.append(
            f"| {item.target_field} | {item.current_value or ''} | "
            f"{item.proposed_value or ''} | {item.action.value} |"
        )
    store.write_text("\n".join(preview_lines) + "\n", *parts, "lark_preview.md")
    return manifest


__all__ = ["write_creator_artifacts"]
