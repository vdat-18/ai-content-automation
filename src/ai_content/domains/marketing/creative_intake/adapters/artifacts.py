"""Machine- and human-readable artifacts for Creative intake runs."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from ai_content.domains.marketing.creative.ports.contracts import CreativeWorkItemInput
from ai_content.domains.marketing.creative.ports.preparation import PreparationContext
from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import CreativeIntakeRun
from .creative_projection import CompiledCreativeTask
from .serialization import run_to_dict


def write_creative_intake_artifacts(
    store: ArtifactStore,
    run: CreativeIntakeRun,
    compiled: CompiledCreativeTask | None,
) -> Path:
    payload = run_to_dict(run)
    parts = ("creative-intake", run.source_run_id)
    manifest = store.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), *parts, "manifest.json"
    )
    store.write_text(
        json.dumps(payload["trigger"], ensure_ascii=False, indent=2),
        *parts,
        "input",
        "trigger.json",
    )
    store.write_text(
        json.dumps(payload["context"], ensure_ascii=False, indent=2),
        *parts,
        "input",
        "context_snapshot.json",
    )
    store.write_text(
        json.dumps(payload["issues"], ensure_ascii=False, indent=2),
        *parts,
        "validation",
        "issues.json",
    )
    if compiled is not None:
        store.write_text(
            TypeAdapter(CreativeWorkItemInput).dump_json(compiled.work_item, indent=2).decode(),
            *parts,
            "handoff",
            "work_item.json",
        )
        store.write_text(
            TypeAdapter(PreparationContext).dump_json(compiled.context, indent=2).decode(),
            *parts,
            "handoff",
            "preparation_context.json",
        )
    handoff_state = run.release.handoff_state.value if run.release else "not_applicable"
    lines = [
        f"# Creative intake {run.context.brand_id} / {run.context.sku_id}",
        "",
        "Synthetic/local pilot. No source system, Ads account or production asset was changed.",
        "",
        f"- Source: `{run.trigger.source.value}` / `{run.trigger.source_preview_id}`",
        f"- State: `{run.state.value}`",
        f"- Context snapshot: `{run.context.snapshot_id}@{run.context.version}`",
        f"- Blocking issues: `{len(run.issues)}`",
        f"- Task release: `{run.release.release_id if run.release else 'none'}`",
        f"- Creative pipeline handoff: `{handoff_state}`",
    ]
    for issue in run.issues:
        lines.append(f"- Issue `{issue.code}`: {issue.detail}")
    store.write_text("\n".join(lines) + "\n", *parts, "summary.md")
    return manifest


__all__ = ["write_creative_intake_artifacts"]
