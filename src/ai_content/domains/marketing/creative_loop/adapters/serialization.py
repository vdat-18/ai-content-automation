"""Serialization helpers for Creative loop records."""

from datetime import datetime

from ..domain.models import CreativeLoopRun, CreativeLoopState


def run_to_dict(run: CreativeLoopRun) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "source_run_id": run.source_run_id,
        "source_checksum_sha256": run.source_checksum_sha256,
        "input_snapshot_id": run.input_snapshot_id,
        "context_snapshot_id": run.context_snapshot_id,
        "state": run.state.value,
        "initial_performance_run_id": run.initial_performance_run_id,
        "initial_evaluation_id": run.initial_evaluation_id,
        "initial_intake_run_id": run.initial_intake_run_id,
        "creative_job_id": run.creative_job_id,
        "approved_creative_version_id": run.approved_creative_version_id,
        "ads_event_id": run.ads_event_id,
        "ads_event_checksum_sha256": run.ads_event_checksum_sha256,
        "post_ads_performance_run_id": run.post_ads_performance_run_id,
        "feedback_run_id": run.feedback_run_id,
        "lesson_id": run.lesson_id,
        "next_intake_run_id": run.next_intake_run_id,
        "next_creative_job_id": run.next_creative_job_id,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "audit_log": list(run.audit_log),
    }


def run_from_dict(data: dict[str, object]) -> CreativeLoopRun:
    return CreativeLoopRun(
        run_id=str(data["run_id"]),
        source_run_id=str(data["source_run_id"]),
        source_checksum_sha256=str(data["source_checksum_sha256"]),
        input_snapshot_id=str(data.get("input_snapshot_id", data.get("fixture_case_id"))),
        context_snapshot_id=str(data["context_snapshot_id"]),
        state=CreativeLoopState(str(data["state"])),
        initial_performance_run_id=str(data["initial_performance_run_id"]),
        initial_evaluation_id=str(data["initial_evaluation_id"]),
        initial_intake_run_id=_optional(data.get("initial_intake_run_id")),
        creative_job_id=_optional(data.get("creative_job_id")),
        approved_creative_version_id=_optional(data.get("approved_creative_version_id")),
        ads_event_id=_optional(data.get("ads_event_id")),
        ads_event_checksum_sha256=_optional(data.get("ads_event_checksum_sha256")),
        post_ads_performance_run_id=_optional(data.get("post_ads_performance_run_id")),
        feedback_run_id=_optional(data.get("feedback_run_id")),
        lesson_id=_optional(data.get("lesson_id")),
        next_intake_run_id=_optional(data.get("next_intake_run_id")),
        next_creative_job_id=_optional(data.get("next_creative_job_id")),
        created_at=datetime.fromisoformat(str(data["created_at"])),
        updated_at=datetime.fromisoformat(str(data["updated_at"])),
        audit_log=tuple(str(item) for item in data.get("audit_log", [])),
    )


def _optional(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = ["run_from_dict", "run_to_dict"]
