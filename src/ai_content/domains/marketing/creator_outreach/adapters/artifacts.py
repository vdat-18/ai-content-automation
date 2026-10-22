"""Machine- and human-readable artifacts for Creator outreach."""

from __future__ import annotations

import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import CreatorOutreachRun
from .serialization import run_to_dict


def write_creator_outreach_artifacts(store: ArtifactStore, run: CreatorOutreachRun) -> Path:
    parts = ("creator-outreach", run.source_run_id)
    payload = run_to_dict(run)
    manifest = store.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), *parts, "manifest.json"
    )
    store.write_text(
        json.dumps(payload["trigger"], ensure_ascii=False, indent=2),
        *parts,
        "input",
        "contact_trigger.json",
    )
    for version in run.versions:
        store.write_text(
            json.dumps(
                next(
                    item for item in payload["versions"] if item["version_id"] == version.version_id
                ),
                ensure_ascii=False,
                indent=2,
            ),
            *parts,
            "versions",
            f"v{version.version_number}.json",
        )
    if run.reply is not None:
        store.write_text(
            json.dumps(payload["reply"], ensure_ascii=False, indent=2),
            *parts,
            "reply",
            "sanitized_reply.json",
        )
    if run.handoff_preview is not None:
        store.write_text(
            json.dumps(payload["handoff_preview"], ensure_ascii=False, indent=2),
            *parts,
            "handoff",
            "lark_preview.json",
        )
    lines = [
        f"# Creator outreach {run.trigger.creator_alias}",
        "",
        "Synthetic/local pilot. No real creator message, booking or Lark write occurred.",
        "",
        f"- State: `{run.state.value}`",
        f"- Candidate: `{run.trigger.candidate_id}`",
        f"- Source evaluation: `{run.trigger.evaluation_id}`",
        f"- Plan versions: `{len(run.versions)}`",
        f"- Delivery receipts: `{len(run.receipts)}` synthetic acknowledgements",
        f"- Reply: `{run.reply.outcome.value if run.reply else 'none'}`",
        f"- Next follow-up: `{run.next_followup_at.isoformat() if run.next_followup_at else 'none'}`",
    ]
    store.write_text("\n".join(lines) + "\n", *parts, "summary.md")
    return manifest


__all__ = ["write_creator_outreach_artifacts"]
