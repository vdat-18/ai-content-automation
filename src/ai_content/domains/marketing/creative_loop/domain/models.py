"""State and exact child references for one bounded Creative feedback loop."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")


def _identifier(value: str, name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


class CreativeLoopState(StrEnum):
    AWAITING_DEMAND_APPROVAL = "awaiting_demand_approval"
    AWAITING_CREATIVE_APPROVAL = "awaiting_creative_approval"
    AWAITING_ADS_OUTCOME = "awaiting_ads_outcome"
    AWAITING_LESSON_APPROVAL = "awaiting_lesson_approval"
    NEXT_BRIEF_READY = "next_brief_ready"
    NEEDS_EVIDENCE = "needs_evidence"
    BLOCKED_CONFLICT = "blocked_conflict"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    COMPLETED = "completed"


@dataclass(frozen=True)
class CreativeLoopRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    input_snapshot_id: str
    context_snapshot_id: str
    state: CreativeLoopState
    initial_performance_run_id: str
    initial_evaluation_id: str
    created_at: datetime
    updated_at: datetime
    initial_intake_run_id: str | None = None
    creative_job_id: str | None = None
    approved_creative_version_id: str | None = None
    ads_event_id: str | None = None
    ads_event_checksum_sha256: str | None = None
    post_ads_performance_run_id: str | None = None
    feedback_run_id: str | None = None
    lesson_id: str | None = None
    next_intake_run_id: str | None = None
    next_creative_job_id: str | None = None
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "source_run_id",
            "input_snapshot_id",
            "context_snapshot_id",
            "initial_performance_run_id",
            "initial_evaluation_id",
        ):
            _identifier(getattr(self, name), name)
        for name in (
            "initial_intake_run_id",
            "creative_job_id",
            "approved_creative_version_id",
            "ads_event_id",
            "post_ads_performance_run_id",
            "feedback_run_id",
            "lesson_id",
            "next_intake_run_id",
            "next_creative_job_id",
        ):
            value = getattr(self, name)
            if value is not None:
                _identifier(value, name)
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        if self.ads_event_checksum_sha256 is not None and len(self.ads_event_checksum_sha256) != 64:
            raise ValueError("ads_event_checksum_sha256 must be SHA-256")
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        required_by_state = {
            CreativeLoopState.AWAITING_CREATIVE_APPROVAL: (
                self.initial_intake_run_id,
                self.creative_job_id,
            ),
            CreativeLoopState.AWAITING_ADS_OUTCOME: (
                self.initial_intake_run_id,
                self.creative_job_id,
                self.approved_creative_version_id,
            ),
            CreativeLoopState.AWAITING_LESSON_APPROVAL: (
                self.ads_event_id,
                self.post_ads_performance_run_id,
                self.feedback_run_id,
                self.lesson_id,
            ),
            CreativeLoopState.NEXT_BRIEF_READY: (
                self.next_intake_run_id,
                self.next_creative_job_id,
            ),
        }
        if any(value is None for value in required_by_state.get(self.state, ())):
            raise ValueError(f"State {self.state.value} is missing required exact references")

    def advance(
        self, state: CreativeLoopState, at: datetime, event: str, **changes
    ) -> CreativeLoopRun:
        _aware(at, "at")
        return replace(
            self,
            state=state,
            updated_at=at,
            audit_log=(*self.audit_log, event),
            **changes,
        )


__all__ = ["CreativeLoopRun", "CreativeLoopState"]
