"""Resolve approved demand into an exact, context-complete Creative task."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from ..domain.models import (
    ComponentStatus,
    ContextComponent,
    CreativeContextSnapshot,
    CreativeIntakeRun,
    CreativeTaskTrigger,
    HandoffState,
    IntakeIssue,
    IntakeIssueStatus,
    IntakeState,
    TaskRelease,
    TriggerSource,
)
from ..ports.interfaces import CreativeIntakeInputDriftError, ICreativeIntakeRepository

# Only hard inputs block intake; brand, persona and policy gaps are resolved by the agent.
_REQUIRED_COMPONENTS = {
    ContextComponent.PRODUCT,
    ContextComponent.OUTPUT,
}


@dataclass(frozen=True)
class CreativeIntakeRequest:
    trigger: CreativeTaskTrigger
    context: CreativeContextSnapshot
    source_checksum_sha256: str


@dataclass(frozen=True)
class CreativeIntakeResult:
    run: CreativeIntakeRun
    duplicate: bool = False


def _issue(
    code: str,
    status: IntakeIssueStatus,
    detail: str,
    component: ContextComponent | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> IntakeIssue:
    return IntakeIssue(code, component, status, detail, evidence_refs)


def _resolve_issues(
    trigger: CreativeTaskTrigger,
    context: CreativeContextSnapshot,
    now: datetime,
) -> tuple[IntakeIssue, ...]:
    issues: list[IntakeIssue] = []
    if not trigger.source_released:
        issues.append(
            _issue(
                "source-preview-not-released",
                IntakeIssueStatus.INVALID,
                "The upstream decision has not released this exact preview.",
            )
        )
    if trigger.brand_id != context.brand_id or trigger.sku_id != context.sku_id:
        issues.append(
            _issue(
                "trigger-context-identity-conflict",
                IntakeIssueStatus.CONFLICT,
                "Trigger and context must reference the same Brand and SKU.",
            )
        )
    if trigger.objective and trigger.objective != context.objective:
        issues.append(
            _issue(
                "objective-conflict",
                IntakeIssueStatus.CONFLICT,
                "Trigger and context objective disagree.",
            )
        )
    if trigger.channel and trigger.channel.casefold() != context.channel.casefold():
        issues.append(
            _issue(
                "channel-conflict",
                IntakeIssueStatus.CONFLICT,
                "Trigger and context channel disagree.",
            )
        )
    if trigger.source == TriggerSource.FEEDBACK_LESSON:
        if not trigger.source_creative_version_id:
            issues.append(
                _issue(
                    "historical-creative-version-missing",
                    IntakeIssueStatus.MISSING,
                    "Feedback intake must pin the tested historical Creative version.",
                    ContextComponent.HISTORY,
                )
            )
        if not trigger.reusable_context_refs:
            issues.append(
                _issue(
                    "historical-context-reference-missing",
                    IntakeIssueStatus.MISSING,
                    "Feedback intake requires exact reusable context references.",
                    ContextComponent.HISTORY,
                )
            )
        elif not set(trigger.reusable_context_refs).issubset(context.resolved_context_refs):
            issues.append(
                _issue(
                    "historical-context-unresolved",
                    IntakeIssueStatus.CONFLICT,
                    "The snapshot does not resolve every context reference pinned by X1.",
                    ContextComponent.HISTORY,
                    trigger.reusable_context_refs,
                )
            )
    components = {item.component: item for item in context.components}
    for component in sorted(_REQUIRED_COMPONENTS, key=lambda item: item.value):
        observation = components.get(component)
        if observation is None:
            issues.append(
                _issue(
                    f"{component.value}-missing",
                    IntakeIssueStatus.MISSING,
                    f"Required context component {component.value} is absent.",
                    component,
                )
            )
            continue
        if observation.status == ComponentStatus.UNKNOWN:
            issues.append(
                _issue(
                    f"{component.value}-unknown",
                    IntakeIssueStatus.UNKNOWN,
                    observation.detail
                    or f"Required context component {component.value} is unknown.",
                    component,
                    observation.evidence_refs,
                )
            )
        elif observation.status == ComponentStatus.CONFLICT:
            issues.append(
                _issue(
                    f"{component.value}-conflict",
                    IntakeIssueStatus.CONFLICT,
                    observation.detail
                    or f"Required context component {component.value} has conflicting values.",
                    component,
                    observation.evidence_refs,
                )
            )
        if observation.valid_until is not None and observation.valid_until <= now:
            issues.append(
                _issue(
                    f"{component.value}-expired",
                    IntakeIssueStatus.EXPIRED,
                    f"Required context component {component.value} has expired.",
                    component,
                    observation.evidence_refs,
                )
            )
    if context.product_image_count < 1:
        issues.append(
            _issue(
                "product-image-missing",
                IntakeIssueStatus.MISSING,
                "At least one product image is required.",
                ContextComponent.PRODUCT,
            )
        )
    if context.output_width < 1 or context.output_height < 1:
        issues.append(
            _issue(
                "output-spec-invalid",
                IntakeIssueStatus.INVALID,
                "Positive output dimensions are required.",
                ContextComponent.OUTPUT,
            )
        )
    return tuple(issues)


def _state(issues: tuple[IntakeIssue, ...]) -> IntakeState:
    codes = {issue.code for issue in issues}
    statuses = {issue.status for issue in issues}
    if "source-preview-not-released" in codes:
        return IntakeState.SOURCE_BLOCKED
    if any(
        issue.component == ContextComponent.POLICY
        and issue.status in {IntakeIssueStatus.CONFLICT, IntakeIssueStatus.EXPIRED}
        for issue in issues
    ):
        return IntakeState.BLOCKED_POLICY
    if IntakeIssueStatus.CONFLICT in statuses:
        return IntakeState.BLOCKED_CONFLICT
    return IntakeState.NEEDS_CONTEXT


class ResolveCreativeIntake:
    def __init__(self, repository: ICreativeIntakeRepository) -> None:
        self._repository = repository

    async def execute(self, request: CreativeIntakeRequest) -> CreativeIntakeResult:
        existing = await self._repository.get_by_source_run_id(request.trigger.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise CreativeIntakeInputDriftError(
                    "Creative intake trigger was reused with different context"
                )
            return CreativeIntakeResult(existing, duplicate=True)

        now = datetime.now(UTC)
        issues = _resolve_issues(request.trigger, request.context, now)
        run_id = f"ci-{hashlib.sha256(request.trigger.source_run_id.encode()).hexdigest()[:20]}"
        release = None
        state = _state(issues) if issues else IntakeState.RELEASED
        if state == IntakeState.RELEASED:
            task_source_run_id = (
                "creative-task-"
                + hashlib.sha256(request.trigger.source_run_id.encode()).hexdigest()[:20]
            )
            release = TaskRelease(
                release_id=f"rel-{hashlib.sha256(task_source_run_id.encode()).hexdigest()[:20]}",
                intake_run_id=run_id,
                source_trigger_id=request.trigger.trigger_id,
                source_run_id=task_source_run_id,
                work_item_ref=(
                    f"creative-intake/{request.trigger.source_run_id}/handoff/work_item.json"
                ),
                context_ref=(
                    f"creative-intake/{request.trigger.source_run_id}/handoff/"
                    "preparation_context.json"
                ),
                display_name=(
                    f"{request.context.brand_id} | {request.context.sku_id} | "
                    f"{request.trigger.action}"
                ),
                handoff_state=HandoffState.READY,
                released_at=now,
            )
        run = CreativeIntakeRun(
            run_id=run_id,
            source_run_id=request.trigger.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            trigger=request.trigger,
            context=request.context,
            state=state,
            issues=issues,
            release=release,
            created_at=now,
            audit_log=(f"resolved:{state.value}",),
        )
        await self._repository.save(run)
        return CreativeIntakeResult(run)


__all__ = ["CreativeIntakeRequest", "CreativeIntakeResult", "ResolveCreativeIntake"]
