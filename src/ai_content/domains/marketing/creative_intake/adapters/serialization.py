"""JSON serialization for Creative intake records."""

from __future__ import annotations

from datetime import datetime

from ..domain.models import (
    ComponentStatus,
    ContextComponent,
    ContextEvidence,
    CreativeContextSnapshot,
    CreativeIntakeRun,
    CreativeTaskTrigger,
    ExperimentDirective,
    HandoffState,
    IntakeIssue,
    IntakeIssueStatus,
    IntakeState,
    TaskRelease,
    TriggerSource,
)


def run_to_dict(run: CreativeIntakeRun) -> dict[str, object]:
    trigger = run.trigger
    context = run.context
    release = run.release
    return {
        "run_id": run.run_id,
        "source_run_id": run.source_run_id,
        "source_checksum_sha256": run.source_checksum_sha256,
        "trigger": {
            "trigger_id": trigger.trigger_id,
            "source": trigger.source.value,
            "source_preview_id": trigger.source_preview_id,
            "source_decision_ref": trigger.source_decision_ref,
            "source_released": trigger.source_released,
            "brand_id": trigger.brand_id,
            "sku_id": trigger.sku_id,
            "action": trigger.action,
            "objective": trigger.objective,
            "channel": trigger.channel,
            "evidence_refs": list(trigger.evidence_refs),
            "requested_at": trigger.requested_at.isoformat(),
            "source_creative_version_id": trigger.source_creative_version_id,
            "reusable_context_refs": list(trigger.reusable_context_refs),
            "experiment_directive": (
                {
                    "category": trigger.experiment_directive.category,
                    "priority": trigger.experiment_directive.priority,
                    "hypothesis": trigger.experiment_directive.hypothesis,
                    "experiment": trigger.experiment_directive.experiment,
                    "success_signal": trigger.experiment_directive.success_signal,
                    "evidence_refs": list(trigger.experiment_directive.evidence_refs),
                    "uncertainty": trigger.experiment_directive.uncertainty,
                }
                if trigger.experiment_directive
                else None
            ),
        },
        "context": {
            "snapshot_id": context.snapshot_id,
            "version": context.version,
            "brand_id": context.brand_id,
            "sku_id": context.sku_id,
            "market": context.market,
            "objective": context.objective,
            "channel": context.channel,
            "product_image_count": context.product_image_count,
            "persona_count": context.persona_count,
            "output_width": context.output_width,
            "output_height": context.output_height,
            "requested_image_count": context.requested_image_count,
            "requested_video_count": context.requested_video_count,
            "requested_video_duration_seconds": context.requested_video_duration_seconds,
            "requested_video_duration_min_seconds": context.requested_video_duration_min_seconds,
            "requested_video_duration_max_seconds": context.requested_video_duration_max_seconds,
            "requested_video_scene_duration_max_seconds": context.requested_video_scene_duration_max_seconds,
            "include_background_music": context.include_background_music,
            "execution_mode": context.execution_mode,
            "production_route": context.production_route,
            "routing_reasons": list(context.routing_reasons),
            "routing_requires_override": context.routing_requires_override,
            "version_refs": list(context.version_refs),
            "resolved_context_refs": list(context.resolved_context_refs),
            "components": [
                {
                    "component": item.component.value,
                    "status": item.status.value,
                    "evidence_refs": list(item.evidence_refs),
                    "observed_at": item.observed_at.isoformat(),
                    "valid_until": item.valid_until.isoformat() if item.valid_until else None,
                    "detail": item.detail,
                }
                for item in context.components
            ],
            "evidence_refs": list(context.evidence_refs),
            "captured_at": context.captured_at.isoformat(),
        },
        "state": run.state.value,
        "issues": [
            {
                "code": item.code,
                "component": item.component.value if item.component else None,
                "status": item.status.value,
                "detail": item.detail,
                "evidence_refs": list(item.evidence_refs),
                "required_for_release": item.required_for_release,
            }
            for item in run.issues
        ],
        "release": (
            {
                "release_id": release.release_id,
                "intake_run_id": release.intake_run_id,
                "source_trigger_id": release.source_trigger_id,
                "source_run_id": release.source_run_id,
                "work_item_ref": release.work_item_ref,
                "context_ref": release.context_ref,
                "display_name": release.display_name,
                "handoff_state": release.handoff_state.value,
                "released_at": release.released_at.isoformat(),
                "downstream_job_id": release.downstream_job_id,
                "handoff_error": release.handoff_error,
            }
            if release
            else None
        ),
        "created_at": run.created_at.isoformat(),
        "audit_log": list(run.audit_log),
    }


def run_from_dict(data: dict[str, object]) -> CreativeIntakeRun:
    trigger_data = data["trigger"]
    context_data = data["context"]
    issue_data = data["issues"]
    assert isinstance(trigger_data, dict)
    assert isinstance(context_data, dict)
    assert isinstance(issue_data, list)
    components_data = context_data["components"]
    assert isinstance(components_data, list)
    trigger = CreativeTaskTrigger(
        trigger_id=str(trigger_data["trigger_id"]),
        source=TriggerSource(trigger_data["source"]),
        source_preview_id=str(trigger_data["source_preview_id"]),
        source_decision_ref=str(trigger_data["source_decision_ref"]),
        source_released=bool(trigger_data["source_released"]),
        brand_id=str(trigger_data["brand_id"]),
        sku_id=str(trigger_data["sku_id"]),
        action=str(trigger_data["action"]),
        objective=trigger_data.get("objective"),
        channel=trigger_data.get("channel"),
        evidence_refs=tuple(trigger_data["evidence_refs"]),
        requested_at=datetime.fromisoformat(str(trigger_data["requested_at"])),
        source_creative_version_id=trigger_data.get("source_creative_version_id"),
        reusable_context_refs=tuple(trigger_data.get("reusable_context_refs", [])),
        experiment_directive=(
            ExperimentDirective(
                category=str(trigger_data["experiment_directive"]["category"]),
                priority=int(trigger_data["experiment_directive"]["priority"]),
                hypothesis=str(trigger_data["experiment_directive"]["hypothesis"]),
                experiment=str(trigger_data["experiment_directive"]["experiment"]),
                success_signal=str(trigger_data["experiment_directive"]["success_signal"]),
                evidence_refs=tuple(trigger_data["experiment_directive"]["evidence_refs"]),
                uncertainty=str(trigger_data["experiment_directive"].get("uncertainty", "")),
            )
            if isinstance(trigger_data.get("experiment_directive"), dict)
            else None
        ),
    )
    context = CreativeContextSnapshot(
        snapshot_id=str(context_data["snapshot_id"]),
        version=str(context_data["version"]),
        brand_id=str(context_data["brand_id"]),
        sku_id=str(context_data["sku_id"]),
        market=str(context_data["market"]),
        objective=str(context_data["objective"]),
        channel=str(context_data["channel"]),
        product_image_count=int(context_data["product_image_count"]),
        persona_count=int(context_data["persona_count"]),
        output_width=int(context_data["output_width"]),
        output_height=int(context_data["output_height"]),
        requested_image_count=int(context_data.get("requested_image_count", 1)),
        requested_video_count=int(context_data.get("requested_video_count", 0)),
        requested_video_duration_seconds=(
            int(context_data["requested_video_duration_seconds"])
            if context_data.get("requested_video_duration_seconds") is not None
            else None
        ),
        requested_video_duration_min_seconds=int(
            context_data.get("requested_video_duration_min_seconds", 15)
        ),
        requested_video_duration_max_seconds=int(
            context_data.get("requested_video_duration_max_seconds", 25)
        ),
        requested_video_scene_duration_max_seconds=int(
            context_data.get("requested_video_scene_duration_max_seconds", 15)
        ),
        include_background_music=bool(context_data.get("include_background_music", False)),
        execution_mode=str(context_data.get("execution_mode", "generate_once")),
        production_route=str(context_data.get("production_route", "manual")),
        routing_reasons=tuple(context_data.get("routing_reasons", [])),
        routing_requires_override=bool(context_data.get("routing_requires_override", False)),
        version_refs=tuple(context_data["version_refs"]),
        resolved_context_refs=tuple(context_data.get("resolved_context_refs", [])),
        components=tuple(
            ContextEvidence(
                component=ContextComponent(item["component"]),
                status=ComponentStatus(item["status"]),
                evidence_refs=tuple(item["evidence_refs"]),
                observed_at=datetime.fromisoformat(str(item["observed_at"])),
                valid_until=(
                    datetime.fromisoformat(str(item["valid_until"]))
                    if item.get("valid_until")
                    else None
                ),
                detail=item.get("detail"),
            )
            for item in components_data
        ),
        evidence_refs=tuple(context_data["evidence_refs"]),
        captured_at=datetime.fromisoformat(str(context_data["captured_at"])),
    )
    issues = tuple(
        IntakeIssue(
            code=str(item["code"]),
            component=(ContextComponent(item["component"]) if item.get("component") else None),
            status=IntakeIssueStatus(item["status"]),
            detail=str(item["detail"]),
            evidence_refs=tuple(item.get("evidence_refs", [])),
            required_for_release=bool(item.get("required_for_release", True)),
        )
        for item in issue_data
    )
    release_data = data.get("release")
    release = None
    if isinstance(release_data, dict):
        release = TaskRelease(
            release_id=str(release_data["release_id"]),
            intake_run_id=str(release_data["intake_run_id"]),
            source_trigger_id=str(release_data["source_trigger_id"]),
            source_run_id=str(release_data["source_run_id"]),
            work_item_ref=str(release_data["work_item_ref"]),
            context_ref=str(release_data["context_ref"]),
            display_name=str(release_data["display_name"]),
            handoff_state=HandoffState(release_data["handoff_state"]),
            released_at=datetime.fromisoformat(str(release_data["released_at"])),
            downstream_job_id=release_data.get("downstream_job_id"),
            handoff_error=release_data.get("handoff_error"),
        )
    return CreativeIntakeRun(
        run_id=str(data["run_id"]),
        source_run_id=str(data["source_run_id"]),
        source_checksum_sha256=str(data["source_checksum_sha256"]),
        trigger=trigger,
        context=context,
        state=IntakeState(data["state"]),
        issues=issues,
        release=release,
        created_at=datetime.fromisoformat(str(data["created_at"])),
        audit_log=tuple(data.get("audit_log", [])),
    )


__all__ = ["run_from_dict", "run_to_dict"]
