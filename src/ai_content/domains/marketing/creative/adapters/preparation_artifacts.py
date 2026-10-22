"""Local, versioned preparation artifacts; no remote reads or model calls."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from ai_content.platform.artifacts.store import ArtifactStore

from ..ports.preparation import PreparationError
from ..ports.preparation_store import PreparedBrief
from .artifacts import safe_run_dir


class FilePreparationStore:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts

    def write_snapshot(self, source_run_id: str, name: str, value: object) -> str:
        relative = Path(safe_run_dir(source_run_id)) / "preparation" / f"{name}.json"
        path = self.artifacts.write_text(
            json.dumps(to_jsonable_python(value), ensure_ascii=False, indent=2),
            relative.as_posix(),
        )
        if isinstance(value, PreparedBrief):
            self.artifacts.write_text(
                render_preparation_summary(value), str(relative.parent), "summary.md"
            )
        return path.relative_to(self.artifacts.root.resolve()).as_posix()

    def load_brief(self, reference: str) -> PreparedBrief:
        raw = self.artifacts.read_text(reference)
        if raw is None:
            raise PreparationError("Prepared brief artifact is missing", code="artifact_missing")
        try:
            result = TypeAdapter(PreparedBrief).validate_json(raw)
        except ValidationError as error:
            raise PreparationError(
                "Prepared brief artifact has invalid schema", code="artifact_invalid"
            ) from error
        if result.schema_version not in {"1", "2", "3"}:
            raise PreparationError("Unsupported prepared brief version", code="artifact_version")
        return result


def render_preparation_summary(output: PreparedBrief) -> str:
    brief = output.brief
    lines = [
        "# Static Creative — Prepared Brief",
        "",
        "Preparation output only; not image QA, approval or verified semantic quality.",
        "",
        f"Brand/SKU: {brief.brand} / {brief.sku}",
        f"Idea: {brief.idea_id}",
        f"Selection rule: {output.selection_rule_version}",
        f"Strategy package: {output.strategy.strategy_id if output.strategy else '(legacy)'}",
        "",
        "## Brief",
        "",
        f"Heading: {brief.heading}",
        f"Subtext: {brief.subtext or '(none)'}",
        f"Visual: {brief.visual_direction}",
        f"Format: {brief.output_spec.width}x{brief.output_spec.height} {brief.output_spec.file_format}",
        f"Guideline: {brief.brand_guideline_ref or '(none)'}",
        f"Banned claims: {', '.join(brief.banned_claims) or '(none)'}",
        f"Composition: {brief.composition.composition_id if brief.composition else '(legacy)'}",
        "",
        "## Candidates",
        "",
    ]
    for idea, decision in zip(output.ideas, output.decisions, strict=True):
        lines.append(
            f"- {idea.idea_id}: {idea.angle}; selected={decision.selected}; {', '.join(decision.reasons)}"
        )
    if output.strategy is not None:
        lines += [
            "",
            "## Strategy evaluation",
            "",
            f"Strategy schema: {output.strategy.schema_version}",
        ]
    lines += ["", "## Warnings", "", *(f"- {warning}" for warning in output.warnings), ""]
    return "\n".join(lines)
