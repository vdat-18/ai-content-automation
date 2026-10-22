"""Human- and machine-readable Performance decision artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import PerformanceDecisionRun
from .serialization import run_to_dict


def write_performance_decision_artifacts(store: ArtifactStore, run: PerformanceDecisionRun) -> Path:
    parts = ("performance-decisions", run.source_run_id)
    manifest = store.write_text(
        json.dumps(run_to_dict(run), ensure_ascii=False, indent=2), *parts, "manifest.json"
    )
    evaluation = run.evaluation
    lines = [
        f"# Performance decision {run.snapshot.subject.subject_id}",
        "",
        "Synthetic/read-only pilot. No Ads budget, campaign or external system was changed.",
        "",
        f"- Grain: `{run.snapshot.subject.subject_type.value}`",
        f"- Classification: `{evaluation.classification.value}`",
        f"- Recommendation: `{evaluation.recommendation.value}`",
        f"- State: `{evaluation.state.value}`",
        f"- Rule: `{evaluation.rule_set_id}@{evaluation.rule_version}` "
        f"(`{evaluation.rule_status.value}`, `{evaluation.rule_mode.value}`)",
        f"- Decision: `{run.decision.value if run.decision else 'pending'}`",
        "",
        "## Rule assessments",
        "",
    ]
    for assessment in evaluation.assessments:
        lines.append(
            f"- **{assessment.rule_id}:** `{assessment.outcome.value}` "
            f"({assessment.passed_criteria}/{assessment.required_passes} required passes)"
        )
        for criterion in assessment.criteria:
            observed = str(criterion.observed_value) if criterion.observed_value is not None else ""
            lines.append(
                f"  - `{criterion.criterion_id}`: `{criterion.outcome.value}`; "
                f"observed `{observed}`; threshold `{criterion.operator.value} "
                f"{criterion.threshold}`"
            )
    analysis = run.opportunity_analysis
    if analysis is not None:
        lines.extend(
            [
                "",
                "## Opportunity Agent (shadow)",
                "",
                f"- Category: `{analysis.category.value}`",
                f"- Priority: `{analysis.priority}`",
                f"- Rationale: {analysis.rationale}",
                f"- Uncertainty: {analysis.uncertainty}",
                f"- Counterargument: {analysis.counterargument}",
                f"- Proposal: `{analysis.proposal.proposal_id}`",
                f"- Experiment: {analysis.proposal.experiment}",
                f"- Success signal: {analysis.proposal.success_signal}",
                f"- Prompt/model/rubric: `{analysis.prompt_version}` / "
                f"`{analysis.model}` / `{analysis.rubric_version}`",
            ]
        )
    store.write_text("\n".join(lines) + "\n", *parts, "decision_card.md")
    preview = run.creative_demand_preview
    preview_lines = [
        "# Creative Demand Preview",
        "",
        "Preview only. This artifact is not a complete CreativeWorkItemInput and performs no handoff.",
        "",
    ]
    if preview is None:
        preview_lines.append("No Creative demand applies to this recommendation.")
    else:
        preview_lines.extend(
            [
                f"- State: `{preview.state.value}`",
                f"- Brand / SKU: `{preview.brand_id}` / `{preview.sku_id}`",
                f"- Action: `{preview.action.value}`",
                f"- Source evaluation: `{preview.source_evaluation_id}`",
                "- Missing M1 context: "
                + ", ".join(f"`{item}`" for item in preview.missing_context),
            ]
        )
    store.write_text("\n".join(preview_lines) + "\n", *parts, "creative_demand_preview.md")
    return manifest


__all__ = ["write_performance_decision_artifacts"]
