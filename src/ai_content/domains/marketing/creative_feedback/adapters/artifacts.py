"""Machine- and human-readable artifacts for Creative feedback runs."""

from __future__ import annotations

import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import CreativeFeedbackRun
from .serialization import run_to_dict


def write_creative_feedback_artifacts(store: ArtifactStore, run: CreativeFeedbackRun) -> Path:
    parts = ("creative-feedback", run.source_run_id)
    manifest = store.write_text(
        json.dumps(run_to_dict(run), ensure_ascii=False, indent=2), *parts, "manifest.json"
    )
    store.write_text(
        json.dumps(run_to_dict(run)["release"], ensure_ascii=False, indent=2),
        *parts,
        "input",
        "creative_release.json",
    )
    store.write_text(
        json.dumps(run_to_dict(run)["ad_mapping"], ensure_ascii=False, indent=2),
        *parts,
        "input",
        "ad_mapping.json",
    )
    store.write_text(
        json.dumps(run_to_dict(run)["performance"], ensure_ascii=False, indent=2),
        *parts,
        "input",
        "performance_outcome.json",
    )
    if run.human_feedback is not None:
        store.write_text(
            json.dumps(run_to_dict(run)["human_feedback"], ensure_ascii=False, indent=2),
            *parts,
            "input",
            "human_feedback.json",
        )
    if run.lesson is not None:
        store.write_text(
            json.dumps(run_to_dict(run)["lesson"], ensure_ascii=False, indent=2),
            *parts,
            "lesson",
            "lesson.json",
        )
    if run.ads_evidence_pack is not None:
        store.write_text(
            json.dumps(run_to_dict(run)["ads_evidence_pack"], ensure_ascii=False, indent=2),
            *parts,
            "learning",
            "evidence_pack.json",
        )
    if run.learning_analysis is not None:
        store.write_text(
            json.dumps(run_to_dict(run)["learning_analysis"], ensure_ascii=False, indent=2),
            *parts,
            "learning",
            "analysis.json",
        )
    if run.next_task_preview is not None:
        store.write_text(
            json.dumps(run_to_dict(run)["next_task_preview"], ensure_ascii=False, indent=2),
            *parts,
            "handoff",
            "next_task_preview.json",
        )
    lesson_summary = run.lesson.summary if run.lesson else "No lesson was created."
    lines = [
        f"# Creative feedback {run.release.creative_version_id}",
        "",
        "Synthetic/local pilot. No Ads, Creative production or external system was changed.",
        "",
        f"- State: `{run.state.value}`",
        f"- Creative version: `{run.release.creative_version_id}`",
        f"- Current version at ingestion: `{run.release.current_version_id}`",
        f"- Ad mapping: `{run.ad_mapping.status.value}`",
        f"- Performance: `{run.performance.classification.value}` / "
        f"`{run.performance.recommendation.value}`",
        f"- Lesson: {lesson_summary}",
        f"- Decision: `{run.decision.value if run.decision else 'pending'}`",
        f"- Learning analysis: "
        f"`{run.learning_analysis.analysis_id if run.learning_analysis else 'not_configured'}`",
    ]
    if run.next_task_preview:
        lines.extend(
            [
                f"- Task preview: `{run.next_task_preview.state.value}`",
                "- Missing M1 context: "
                + ", ".join(f"`{item}`" for item in run.next_task_preview.missing_context),
            ]
        )
    store.write_text("\n".join(lines) + "\n", *parts, "summary.md")
    return manifest


__all__ = ["write_creative_feedback_artifacts"]
