"""Evidence-aware records for resolving a Creative task before M1 starts."""

from __future__ import annotations

import hashlib
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


class TriggerSource(StrEnum):
    PERFORMANCE_DEMAND = "performance_demand"
    MARKETING_REQUEST = "marketing_request"
    FEEDBACK_LESSON = "feedback_lesson"


class ContextComponent(StrEnum):
    BRAND = "brand"
    PRODUCT = "product"
    PERSONA = "persona"
    POLICY = "policy"
    OUTPUT = "output"
    VERSIONS = "versions"
    HISTORY = "history"
    FEEDBACK = "feedback"


class ComponentStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class IntakeIssueStatus(StrEnum):
    MISSING = "missing"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    EXPIRED = "expired"
    INVALID = "invalid"


class IntakeState(StrEnum):
    RELEASED = "released"
    SOURCE_BLOCKED = "source_blocked"
    NEEDS_CONTEXT = "needs_context"
    BLOCKED_CONFLICT = "blocked_conflict"
    BLOCKED_POLICY = "blocked_policy"


class HandoffState(StrEnum):
    READY = "ready"
    BRIEF_READY = "brief_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    FAILED = "failed"


@dataclass(frozen=True)
class ExperimentDirective:
    category: str
    priority: int
    hypothesis: str
    experiment: str
    success_signal: str
    evidence_refs: tuple[str, ...]
    uncertainty: str

    def __post_init__(self) -> None:
        if not 1 <= self.priority <= 5:
            raise ValueError("Experiment priority must be between 1 and 5")
        if not all(
            value.strip()
            for value in (
                self.category,
                self.hypothesis,
                self.experiment,
                self.success_signal,
            )
        ):
            raise ValueError("Experiment strategy fields are required")
        if not self.evidence_refs:
            raise ValueError("Experiment strategy requires evidence")


@dataclass(frozen=True)
class CreativeTaskTrigger:
    trigger_id: str
    source: TriggerSource
    source_preview_id: str
    source_decision_ref: str
    source_released: bool
    brand_id: str
    sku_id: str
    action: str
    objective: str | None
    channel: str | None
    evidence_refs: tuple[str, ...]
    requested_at: datetime
    source_creative_version_id: str | None = None
    reusable_context_refs: tuple[str, ...] = ()
    experiment_directive: ExperimentDirective | None = None

    def __post_init__(self) -> None:
        for name in (
            "trigger_id",
            "source_preview_id",
            "source_decision_ref",
            "brand_id",
            "sku_id",
        ):
            _identifier(getattr(self, name), name)
        if self.source_creative_version_id is not None:
            _identifier(self.source_creative_version_id, "source_creative_version_id")
        if not self.action.strip() or not self.evidence_refs:
            raise ValueError("Trigger action and evidence are required")
        if self.experiment_directive and not set(self.experiment_directive.evidence_refs).issubset(
            self.evidence_refs
        ):
            raise ValueError("Experiment evidence must belong to the trigger")
        _aware(self.requested_at, "requested_at")

    @property
    def source_run_id(self) -> str:
        source_key = f"{self.source.value}:{self.source_preview_id}"
        return f"creative-intake-{hashlib.sha256(source_key.encode()).hexdigest()[:20]}"


@dataclass(frozen=True)
class ContextEvidence:
    component: ContextComponent
    status: ComponentStatus
    evidence_refs: tuple[str, ...]
    observed_at: datetime
    valid_until: datetime | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        if self.valid_until is not None:
            _aware(self.valid_until, "valid_until")
            if self.valid_until <= self.observed_at:
                raise ValueError("valid_until must be later than observed_at")
        if self.status != ComponentStatus.UNKNOWN and not self.evidence_refs:
            raise ValueError("Known or conflicting context requires evidence")


@dataclass(frozen=True)
class CreativeContextSnapshot:
    snapshot_id: str
    version: str
    brand_id: str
    sku_id: str
    market: str
    objective: str
    channel: str
    product_image_count: int
    persona_count: int
    output_width: int
    output_height: int
    version_refs: tuple[str, ...]
    resolved_context_refs: tuple[str, ...]
    components: tuple[ContextEvidence, ...]
    evidence_refs: tuple[str, ...]
    captured_at: datetime
    requested_image_count: int = 1
    requested_video_count: int = 0
    requested_video_duration_seconds: int | None = None
    requested_video_duration_min_seconds: int = 15
    requested_video_duration_max_seconds: int = 60
    requested_video_scene_duration_max_seconds: int = 15
    include_background_music: bool = False
    execution_mode: str = "generate_once"
    production_route: str = "manual"
    routing_reasons: tuple[str, ...] = ()
    routing_requires_override: bool = False

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "brand_id", "sku_id"):
            _identifier(getattr(self, name), name)
        if not all(
            value.strip() for value in (self.version, self.market, self.objective, self.channel)
        ):
            raise ValueError("Context scope and version are required")
        if self.product_image_count < 0 or self.persona_count < 0:
            raise ValueError("Context counts cannot be negative")
        if self.output_width < 0 or self.output_height < 0:
            raise ValueError("Output dimensions cannot be negative")
        if self.requested_image_count < 0:
            raise ValueError("Requested image count cannot be negative")
        if self.requested_video_count < 0:
            raise ValueError("Requested video count cannot be negative")
        if self.requested_video_duration_min_seconds < 1:
            raise ValueError("Requested video duration minimum must be positive")
        if self.requested_video_duration_max_seconds < self.requested_video_duration_min_seconds:
            raise ValueError("Requested video duration range is invalid")
        if self.requested_video_scene_duration_max_seconds < 1:
            raise ValueError("Requested video scene duration maximum must be positive")
        if (
            self.requested_video_count > 0
            and self.requested_video_duration_seconds is not None
            and not (
                self.requested_video_duration_min_seconds
                <= self.requested_video_duration_seconds
                <= self.requested_video_duration_max_seconds
            )
        ):
            raise ValueError("Requested video duration must be within the configured range")
        if self.execution_mode not in {"brief_only", "generate_once"}:
            raise ValueError("Unsupported Creative automation execution mode")
        if self.requested_image_count == 0 and self.requested_video_count == 0:
            raise ValueError("At least one Creative output must be requested")
        if self.production_route not in {"manual", "assisted", "automated"}:
            raise ValueError("Unsupported production route")
        keys = [item.component for item in self.components]
        if len(keys) != len(set(keys)):
            raise ValueError("Context components must be unique")
        if not self.evidence_refs:
            raise ValueError("Context snapshot requires evidence")
        available_evidence = set(self.evidence_refs)
        if any(
            not set(item.evidence_refs).issubset(available_evidence) for item in self.components
        ):
            raise ValueError("Context component evidence must belong to the snapshot")
        _aware(self.captured_at, "captured_at")


@dataclass(frozen=True)
class IntakeIssue:
    code: str
    component: ContextComponent | None
    status: IntakeIssueStatus
    detail: str
    evidence_refs: tuple[str, ...] = ()
    required_for_release: bool = True

    def __post_init__(self) -> None:
        _identifier(self.code, "issue code")
        if not self.detail.strip():
            raise ValueError("Issue detail is required")


@dataclass(frozen=True)
class TaskRelease:
    release_id: str
    intake_run_id: str
    source_trigger_id: str
    source_run_id: str
    work_item_ref: str
    context_ref: str
    display_name: str
    handoff_state: HandoffState
    released_at: datetime
    downstream_job_id: str | None = None
    handoff_error: str | None = None

    def __post_init__(self) -> None:
        for name in ("release_id", "intake_run_id", "source_trigger_id", "source_run_id"):
            _identifier(getattr(self, name), name)
        if not all(
            value.strip() for value in (self.work_item_ref, self.context_ref, self.display_name)
        ):
            raise ValueError("Task release references and display name are required")
        _aware(self.released_at, "released_at")
        downstream_states = {
            HandoffState.BRIEF_READY,
            HandoffState.AWAITING_APPROVAL,
            HandoffState.APPROVED,
            HandoffState.REJECTED,
            HandoffState.ARCHIVED,
        }
        if self.handoff_state in downstream_states and not self.downstream_job_id:
            raise ValueError("Downstream handoff state requires downstream_job_id")
        if self.handoff_state == HandoffState.FAILED and not self.handoff_error:
            raise ValueError("Failed handoff requires an error code")


@dataclass(frozen=True)
class CreativeIntakeRun:
    run_id: str
    source_run_id: str
    source_checksum_sha256: str
    trigger: CreativeTaskTrigger
    context: CreativeContextSnapshot
    state: IntakeState
    issues: tuple[IntakeIssue, ...]
    release: TaskRelease | None
    created_at: datetime
    audit_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("run_id", "source_run_id"):
            _identifier(getattr(self, name), name)
        if self.source_run_id != self.trigger.source_run_id:
            raise ValueError("Run source identity must be derived from the trigger")
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        _aware(self.created_at, "created_at")
        blocking = any(issue.required_for_release for issue in self.issues)
        if self.state == IntakeState.RELEASED:
            if blocking or self.release is None:
                raise ValueError("Released intake requires a task and no blocking issues")
        elif self.release is not None:
            raise ValueError("Blocked intake cannot carry a task release")
        if self.release is not None and (
            self.release.intake_run_id != self.run_id
            or self.release.source_trigger_id != self.trigger.trigger_id
        ):
            raise ValueError("Task release must belong to its intake run and trigger")

    def record_handoff(
        self,
        state: HandoffState,
        *,
        downstream_job_id: str | None = None,
        error: str | None = None,
    ) -> CreativeIntakeRun:
        if self.release is None:
            raise ValueError("Blocked intake cannot be handed off")
        updated = replace(
            self.release,
            handoff_state=state,
            downstream_job_id=downstream_job_id,
            handoff_error=error,
        )
        return replace(
            self,
            release=updated,
            audit_log=(*self.audit_log, f"handoff:{state.value}"),
        )


__all__ = [
    "ComponentStatus",
    "ContextComponent",
    "ContextEvidence",
    "CreativeContextSnapshot",
    "CreativeIntakeRun",
    "CreativeTaskTrigger",
    "ExperimentDirective",
    "HandoffState",
    "IntakeIssue",
    "IntakeIssueStatus",
    "IntakeState",
    "TaskRelease",
    "TriggerSource",
]
