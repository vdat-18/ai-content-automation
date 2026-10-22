"""Creative artifact and manifest writer for the local pilot harness.

Writes the per-run artifact tree under the ArtifactStore root:

    {run_dir}/input/work_item.json
    {run_dir}/context/context.json
    {run_dir}/ideas/idea-1.json ...
    {run_dir}/versions/{version_id}.json + {version_id}.artifact.txt
    {run_dir}/approval/card.json
    {run_dir}/manifest.json   (machine-readable)
    {run_dir}/summary.md      (human-readable)

Binary assets are referenced, never embedded, in job state or the manifest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.entities import AssetVersion, CreativeJob
from ..ports.contracts import (
    ContextPackage,
    CreativeWorkItemInput,
    IdeaPackage,
)

MANIFEST_VERSION = "3"


def safe_run_dir(source_run_id: str) -> str:
    """Return a collision-resistant, filesystem-safe directory name."""
    sanitized = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in source_run_id
    ).strip(". ")
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    unchanged = sanitized == source_run_id and sanitized.upper() not in reserved
    if unchanged and len(sanitized) <= 100:
        return sanitized

    digest = hashlib.sha256(source_run_id.encode("utf-8")).hexdigest()[:12]
    prefix = sanitized[:80] or "run"
    return f"{prefix}-{digest}"


def run_dir_for(job: CreativeJob) -> str:
    return safe_run_dir(job.source_run_id or job.job_id.value)


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def _work_item_dict(work_item: CreativeWorkItemInput) -> dict[str, Any]:
    return {
        "source_run_id": work_item.source_run_id,
        "marketing_scope": {
            "brand": work_item.marketing_scope.brand,
            "market": work_item.marketing_scope.market,
        },
        "objective": work_item.objective,
        "channel": work_item.channel,
        "time_window": work_item.time_window,
        "target_sku_set": [
            {
                "sku_id": sku.sku_id,
                "sku_name": sku.sku_name,
                "product_metadata": {
                    "image_refs": list(sku.product_metadata.image_refs),
                    "price": str(sku.product_metadata.price)
                    if sku.product_metadata.price is not None
                    else None,
                    "currency": sku.product_metadata.currency,
                    "offer": sku.product_metadata.offer,
                    "differentiators": list(sku.product_metadata.differentiators),
                },
                "creative_constraints": {
                    "format_constraints": {
                        "width": sku.creative_constraints.format_spec.width,
                        "height": sku.creative_constraints.format_spec.height,
                        "file_format": sku.creative_constraints.format_spec.file_format,
                        "aspect_ratio": sku.creative_constraints.format_spec.aspect_ratio,
                    },
                    "brand_guideline_ref": sku.creative_constraints.brand_guideline_ref,
                    "banned_claims": list(sku.creative_constraints.banned_claims),
                },
                "customer_context": {
                    "pain_points": list(sku.customer_context.pain_points),
                    "promises": list(sku.customer_context.promises),
                    "target_stage": sku.customer_context.target_stage,
                },
                "historical_creative_context": {
                    "tested_angles": list(
                        sku.historical_creative_context.tested_angles,
                    ),
                    "performance_notes": sku.historical_creative_context.performance_notes,
                },
                "lead_feedback_context": {
                    "common_issues": list(sku.lead_feedback_context.common_issues),
                    "recent_rejections": list(
                        sku.lead_feedback_context.recent_rejections,
                    ),
                }
                if sku.lead_feedback_context is not None
                else None,
            }
            for sku in work_item.target_sku_set
        ],
        "rubric_version": {
            "id": work_item.rubric_version.rubric_id,
            "version": work_item.rubric_version.version,
            "is_draft": work_item.rubric_version.is_draft,
        },
        "rule_version": {
            "id": work_item.rule_version.rule_id,
            "version": work_item.rule_version.version,
        },
        "prompt_version": {
            "id": work_item.prompt_version.prompt_id,
            "version": work_item.prompt_version.version,
        },
        "policy_version": {
            "id": work_item.policy_version.policy_id,
            "version": work_item.policy_version.version,
        },
        "workflow_version": {
            "id": work_item.workflow_version.workflow_id,
            "version": work_item.workflow_version.version,
        },
        "persona_override": work_item.persona_override,
        "creative_direction_override": work_item.creative_direction_override,
        "campaign_notes": work_item.campaign_notes,
        "manual_priority_weight": str(work_item.manual_priority_weight)
        if work_item.manual_priority_weight is not None
        else None,
        "variation_count": work_item.variation_count,
        "requested_image_count": work_item.requested_image_count,
        "requested_video_count": work_item.requested_video_count,
        "created_by": work_item.created_by,
        "created_at": work_item.created_at,
    }


def _context_dict(context: ContextPackage) -> dict[str, Any]:
    return {
        "context_id": context.context_id,
        "source_run_id": context.source_run_id,
        "sku_id": context.sku_id,
        "brand": context.brand,
        "evidence": [
            {
                "source_id": e.source_id,
                "data_version": e.data_version,
                "retrieved_at": e.retrieved_at,
            }
            for e in context.evidence
        ],
        "historical": {
            "tested_angles": list(context.historical.tested_angles),
            "performance_notes": context.historical.performance_notes,
        },
        "brand_guideline_ref": context.brand_guideline_ref,
        "risk_flags": list(context.risk_flags),
        "collected_at": context.collected_at,
    }


def _idea_dict(idea: IdeaPackage, selected: bool) -> dict[str, Any]:
    return {
        "idea_id": idea.idea_id,
        "brand": idea.brand,
        "sku_id": idea.sku_id,
        "objective": idea.objective,
        "market": idea.market,
        "persona": idea.persona,
        "angle": idea.angle,
        "hook": idea.hook,
        "concept": idea.concept,
        "evidence_refs": list(idea.evidence_refs),
        "fidelity_checks": [
            {"check_id": c.check_id, "passed": c.passed} for c in idea.fidelity_checks
        ],
        "risk_flags": list(idea.risk_flags),
        "confidence": str(idea.confidence),
        "duration_plan": {
            "max_retries": idea.duration_plan.max_retries,
            "max_cost": str(idea.duration_plan.max_cost)
            if idea.duration_plan.max_cost is not None
            else None,
        }
        if idea.duration_plan is not None
        else None,
        "selected": selected,
    }


def _version_dict(version: AssetVersion) -> dict[str, Any]:
    artifact_directory = Path(version.artifact_path).parent if version.artifact_path else None
    raw_artifact_path = (
        next(
            (str(path) for path in (artifact_directory / "raw").glob("image.*") if path.is_file()),
            None,
        )
        if artifact_directory
        else None
    )
    return {
        "version_id": version.version_id.value,
        "attempt_number": version.attempt_number,
        "creative_set_id": version.creative_set_id,
        "variation_id": version.variation_id,
        "variation_attempt_number": version.variation_attempt_number,
        "input_ref": version.input_ref,
        "artifact_url": version.artifact_url,
        "artifact_path": version.artifact_path,
        "generation_metadata_path": str(Path(version.artifact_path).parent / "metadata.json")
        if version.artifact_path
        else None,
        "raw_artifact_path": raw_artifact_path,
        "composition_path": (
            str(artifact_directory / "composition.json")
            if artifact_directory and (artifact_directory / "composition.json").is_file()
            else None
        ),
        "cost": {"amount": str(version.cost.amount), "currency": version.cost.currency}
        if version.cost is not None
        else None,
        "input_hash": version.input_hash,
        "prompt_version": version.prompt_version,
        "rubric_version": version.rubric_version,
        "policy_version": version.policy_version,
        "workflow_version": version.workflow_version,
        "generator_version": version.generator_version,
        "seed": version.seed,
        "qa": {
            "passed": version.qa_passed,
            "score": str(version.qa_score) if version.qa_score is not None else None,
            "issues": list(version.qa_issues),
            "warnings": list(version.qa_warnings),
            "feedback": version.qa_feedback,
            "outcome": version.qa_outcome.value if version.qa_outcome else None,
            "retryable": version.qa_retryable,
            "requires_human_review": version.qa_requires_human_review,
            "repair_actions": [item.value for item in version.qa_repair_actions],
            "evidence_refs": list(version.qa_evidence_refs),
            "reviewer_version": version.qa_reviewer_version,
            "criteria": [
                {
                    "criterion_id": item.criterion_id,
                    "status": item.status.value,
                    "reason": item.reason,
                    "score": str(item.score) if item.score is not None else None,
                    "confidence": str(item.confidence) if item.confidence is not None else None,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in version.qa_criteria
            ],
            "semantic_issues": [
                {
                    "code": item.code,
                    "criterion_id": item.criterion_id,
                    "severity": item.severity.value,
                    "repair_action": item.repair_action.value,
                    "description": item.description,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in version.qa_semantic_issues
            ],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "description": item.description,
                    "source_ref": item.source_ref,
                    "region": [str(value) for value in item.region] if item.region else None,
                }
                for item in version.qa_evidence
            ],
        },
        "created_at": version.created_at,
    }


def build_manifest(
    job: CreativeJob,
    work_item: CreativeWorkItemInput | None,
    context: ContextPackage | None,
    ideas: tuple[IdeaPackage, ...] | None,
) -> dict[str, Any]:
    """Assemble the machine-readable manifest for a job."""
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": datetime.now(UTC),
        "job": {
            "job_id": job.job_id.value,
            "source_run_id": job.source_run_id,
            "status": job.status.value,
            "context_ref": job.context_ref,
            "idea_id": job.idea_id,
            "creative_set_id": job.creative_set_id,
        },
        "versions": [_version_dict(v) for v in job.versions],
        "ideas": [_idea_dict(idea, selected=idea.idea_id == job.idea_id) for idea in (ideas or ())],
        "context": _context_dict(context) if context is not None else None,
        "input": _work_item_dict(work_item) if work_item is not None else None,
        "approval": None,
        "lineage": [
            {
                "entry_type": entry.entry_type,
                "ref": entry.ref,
                "parent_ref": entry.parent_ref,
                "details": dict(entry.details),
                "recorded_at": entry.recorded_at,
            }
            for entry in job.lineage
        ],
        "totals": {
            "versions": len(job.versions),
            "retries": job.retry_count,
            "cost": {
                "amount": str(job.total_cost.amount),
                "currency": job.total_cost.currency,
            }
            if job.total_cost is not None
            else None,
            "audit_entries": len(job.audit_log),
        },
    }
    if job.card is not None:
        manifest["approval"] = {
            "work_item_id": job.card.work_item_id,
            "candidate_summary": job.card.candidate_summary,
            "final_version_ref": job.card.final_version_ref,
            "final_version_refs": list(job.card.final_version_refs),
            "creative_set_id": job.card.creative_set_id,
            "thumbnail_ref": job.card.thumbnail_ref,
            "warnings": list(job.card.warnings),
            "score": str(job.card.score) if job.card.score is not None else None,
            "evidence_refs": list(job.card.evidence_refs),
            "decision": job.card.decision.value if job.card.decision else None,
            "reviewer_id": job.card.reviewer_id,
            "decided_at": job.card.decided_at,
            "reason": job.card.reason,
        }
    return manifest


def render_summary(manifest: dict[str, Any]) -> str:
    """Render a human-readable markdown summary of a manifest."""
    job = manifest["job"]
    lines = [
        "# Static Creative Pilot Run",
        "",
        f"- Job: `{job['job_id']}`",
        f"- Source run: `{job['source_run_id']}`",
        f"- Status: **{job['status']}**",
        f"- Context: `{job['context_ref']}`",
        f"- Selected idea: `{job['idea_id']}`",
        "",
        "## Versions",
        "",
    ]
    for version in manifest["versions"]:
        qa = version["qa"]
        outcome = "PASS" if qa["passed"] else "FAIL"
        lines.append(
            f"- `{version['version_id']}` — {outcome}"
            f" (score {qa['score']}, generator {version['generator_version']},"
            f" input `{(version['input_hash'] or '')[:12]}`)"
        )
        if qa["issues"]:
            lines.append(f"  - issues: {'; '.join(qa['issues'])}")
        if qa["feedback"]:
            lines.append(f"  - feedback: {qa['feedback']}")
        if qa["warnings"]:
            lines.append(f"  - warnings: {'; '.join(qa['warnings'])}")
    totals = manifest["totals"]
    lines += [
        "",
        "## Totals",
        "",
        f"- Versions: {totals['versions']} (retries: {totals['retries']})",
        f"- Cost: {totals['cost']['amount']} {totals['cost']['currency']}"
        if totals["cost"]
        else "- Cost: n/a",
    ]
    approval = manifest.get("approval")
    if approval:
        decision = approval["decision"] or "PENDING"
        lines += [
            "",
            "## Approval",
            "",
            f"- Creative set `{approval.get('creative_set_id')}`: **{decision}**",
            f"- Final versions: {', '.join(approval.get('final_version_refs') or [approval['final_version_ref']])}",
        ]
        if approval.get("reviewer_id"):
            lines.append(f"- Reviewer: {approval['reviewer_id']}")
        if approval.get("reason"):
            lines.append(f"- Reason: {approval['reason']}")
    lines += ["", "## Lineage", ""]
    for entry in manifest["lineage"]:
        parent = f" <- {entry['parent_ref']}" if entry.get("parent_ref") else ""
        lines.append(f"- {entry['entry_type']}: `{entry['ref']}`{parent}")
    return "\n".join(lines) + "\n"


def write_job_artifacts(
    store: ArtifactStore,
    job: CreativeJob,
    work_item: CreativeWorkItemInput,
    context: ContextPackage | None,
    ideas: tuple[IdeaPackage, ...] | None,
) -> Path:
    """Write the complete artifact tree for a finished (or failed) run."""
    run_dir = run_dir_for(job)

    store.write_text(_dump(_work_item_dict(work_item)), run_dir, "input", "work_item.json")
    if context is not None:
        store.write_text(_dump(_context_dict(context)), run_dir, "context", "context.json")
    for index, idea in enumerate(ideas or (), start=1):
        store.write_text(
            _dump(_idea_dict(idea, selected=idea.idea_id == job.idea_id)),
            run_dir,
            "ideas",
            f"idea-{index}.json",
        )
    for version in job.versions:
        store.write_text(
            _dump(_version_dict(version)),
            run_dir,
            "versions",
            f"{version.version_id.value}.json",
        )
        if version.artifact_path is None:
            store.write_text(
                f"placeholder artifact for {version.version_id.value}\n"
                f"generator: {version.generator_version}\n"
                f"artifact: {version.artifact_url or version.artifact_path}\n",
                run_dir,
                "versions",
                f"{version.version_id.value}.artifact.txt",
            )
    if job.card is not None:
        card = build_manifest(job, work_item, context, ideas)["approval"]
        store.write_text(_dump(card), run_dir, "approval", "card.json")

    manifest = build_manifest(job, work_item, context, ideas)
    manifest_path = store.write_text(_dump(manifest), run_dir, "manifest.json")
    store.write_text(render_summary(manifest), run_dir, "summary.md")
    return manifest_path


def refresh_after_decision(store: ArtifactStore, job: CreativeJob) -> Path | None:
    """Patch manifest.json and card.json after an approval decision.

    Returns the manifest path, or None when no manifest exists yet.
    """
    run_dir = run_dir_for(job)
    raw = store.read_text(run_dir, "manifest.json")
    if raw is None:
        return None
    manifest = json.loads(raw)
    manifest["generated_at"] = datetime.now(UTC)
    manifest["job"]["status"] = job.status.value
    manifest["lineage"] = [
        {
            "entry_type": entry.entry_type,
            "ref": entry.ref,
            "parent_ref": entry.parent_ref,
            "details": dict(entry.details),
            "recorded_at": entry.recorded_at,
        }
        for entry in job.lineage
    ]
    if job.card is not None:
        approval = {
            "work_item_id": job.card.work_item_id,
            "candidate_summary": job.card.candidate_summary,
            "final_version_ref": job.card.final_version_ref,
            "final_version_refs": list(job.card.final_version_refs),
            "creative_set_id": job.card.creative_set_id,
            "thumbnail_ref": job.card.thumbnail_ref,
            "warnings": list(job.card.warnings),
            "score": str(job.card.score) if job.card.score is not None else None,
            "evidence_refs": list(job.card.evidence_refs),
            "decision": job.card.decision.value if job.card.decision else None,
            "reviewer_id": job.card.reviewer_id,
            "decided_at": job.card.decided_at,
            "reason": job.card.reason,
        }
        manifest["approval"] = approval
        store.write_text(_dump(approval), run_dir, "approval", "card.json")
    manifest_path = store.write_text(_dump(manifest), run_dir, "manifest.json")
    store.write_text(render_summary(manifest), run_dir, "summary.md")
    return manifest_path


__all__ = [
    "MANIFEST_VERSION",
    "build_manifest",
    "refresh_after_decision",
    "render_summary",
    "run_dir_for",
    "safe_run_dir",
    "write_job_artifacts",
]
