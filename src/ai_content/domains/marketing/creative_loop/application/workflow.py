"""Coordinate one bounded H2 -> M1/M2 -> X1 -> next-brief cycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJobId,
    CreativeJobStatus,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    EvidenceStatus,
    FeedbackDecision,
    FeedbackRunState,
)
from ai_content.domains.marketing.creative_intake.application.contracts import (
    CreativeIntakeFixture,
)
from ai_content.domains.marketing.creative_intake.application.projections import (
    project_feedback_trigger,
    project_performance_trigger,
)
from ai_content.domains.marketing.creative_intake.domain.models import (
    HandoffState,
    IntakeState,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    EvaluationState,
    PerformanceDecision,
)

from ..domain.models import CreativeLoopRun, CreativeLoopState
from ..ports.contracts import AdsOutcome, CreativeLoopInput
from ..ports.interfaces import (
    CreativeLoopEventDriftError,
    CreativeLoopInputDriftError,
    ICreativeLoopRepository,
)
from .projections import (
    build_intake_case,
    build_next_intake_case,
    build_post_ads_request,
    project_creative_release,
    project_feedback_request,
)


@dataclass(frozen=True)
class CreativeLoopResult:
    run: CreativeLoopRun
    duplicate: bool = False


class RunCreativeLoop:
    def __init__(
        self,
        repository: ICreativeLoopRepository,
        performance_runtime,
        intake_runtime,
        creative_runtime,
        feedback_runtime,
        *,
        preparation_config,
        config_dir,
    ) -> None:
        self._repository = repository
        self._performance = performance_runtime
        self._intake = intake_runtime
        self._creative = creative_runtime
        self._feedback = feedback_runtime
        self._preparation_config = preparation_config
        self._config_dir = config_dir

    async def start(self, case: CreativeLoopInput) -> CreativeLoopResult:
        existing = await self._repository.get_by_source_run_id(case.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != case.source_checksum_sha256:
                raise CreativeLoopInputDriftError(
                    "Creative loop source_run_id was reused with changed input"
                )
            return CreativeLoopResult(existing, True)
        performance = (await self._performance.execute(case.initial_performance)).run
        state = self._initial_state(performance.evaluation.state)
        now = datetime.now(UTC)
        run = CreativeLoopRun(
            run_id=str(uuid5(NAMESPACE_URL, f"creative-loop:{case.source_run_id}")),
            source_run_id=case.source_run_id,
            source_checksum_sha256=case.source_checksum_sha256,
            input_snapshot_id=case.input_snapshot_id,
            context_snapshot_id=case.context_snapshot_id,
            state=state,
            initial_performance_run_id=performance.run_id,
            initial_evaluation_id=performance.evaluation.evaluation_id,
            created_at=now,
            updated_at=now,
            audit_log=(f"initial-performance:{performance.run_id}:{state.value}",),
        )
        await self._repository.save(run)
        return CreativeLoopResult(run)

    async def decide_demand(
        self,
        run_id: str,
        evaluation_id: str,
        decision: PerformanceDecision,
        reviewer_alias: str,
        reason: str,
        case: CreativeLoopInput,
    ) -> CreativeLoopRun:
        run = await self._require(run_id, case)
        if run.state != CreativeLoopState.AWAITING_DEMAND_APPROVAL:
            return await self._reconcile_demand_decision(run, evaluation_id, decision)
        performance = await self._performance.repository.get(run.initial_performance_run_id)
        if performance is None:
            raise ValueError("Initial Performance run not found")
        if performance.decision is None:
            performance = await self._performance.decide(
                performance.run_id, evaluation_id, decision, reviewer_alias, reason
            )
        elif (
            performance.decision != decision or performance.decision_evaluation_id != evaluation_id
        ):
            raise ValueError("Initial Performance decision conflicts with the recorded decision")
        if decision == PerformanceDecision.REJECT:
            return await self._save(
                run.advance(CreativeLoopState.REJECTED, datetime.now(UTC), "demand:rejected")
            )
        if decision == PerformanceDecision.DEFER:
            return await self._save(
                run.advance(CreativeLoopState.DEFERRED, datetime.now(UTC), "demand:deferred")
            )
        trigger = project_performance_trigger(performance)
        intake_case = build_intake_case(case.intake_template, case.context_snapshot_id, trigger)
        outcome = await self._intake.run(
            CreativeIntakeFixture((intake_case,)),
            dispatch_creative=True,
            preparation_config=self._preparation_config,
            config_dir=self._config_dir,
        )
        intake = outcome.runs[0]
        state = self._intake_state(intake)
        return await self._save(
            run.advance(
                state,
                datetime.now(UTC),
                f"initial-intake:{intake.run_id}:{state.value}",
                initial_intake_run_id=intake.run_id,
                creative_job_id=(intake.release.downstream_job_id if intake.release else None),
            )
        )

    async def decide_creative(
        self,
        run_id: str,
        decision: ApprovalDecision,
        reviewer_alias: str,
        reason: str,
        case: CreativeLoopInput,
    ) -> CreativeLoopRun:
        run = await self._require(run_id, case)
        if run.state != CreativeLoopState.AWAITING_CREATIVE_APPROVAL:
            if run.creative_job_id is not None:
                recorded = await self._creative.repository.get_job(
                    CreativeJobId.from_string(run.creative_job_id)
                )
                if recorded is not None and recorded.approval_decision == decision:
                    return run
            raise ValueError("Creative loop is not awaiting a Creative decision")
        if run.creative_job_id is None or run.initial_intake_run_id is None:
            raise ValueError("Creative loop is missing its exact Creative references")
        job = await self._creative.repository.get_job(
            CreativeJobId.from_string(run.creative_job_id)
        )
        if job is None:
            raise ValueError("Creative job not found")
        if job.approval_decision is None:
            outcome = await self._creative.decide(
                job.job_id.value, decision, reviewer_alias, reason
            )
            if not outcome.result.success or outcome.result.job is None:
                raise ValueError(outcome.result.error or "Creative decision failed")
            job = outcome.result.job
        elif job.approval_decision != decision:
            raise ValueError("Creative decision conflicts with the recorded decision")
        intake = await self._intake.repository.get(run.initial_intake_run_id)
        if intake is None or intake.release is None:
            raise ValueError("Creative intake release not found")
        handoff = (
            HandoffState.APPROVED
            if job.status == CreativeJobStatus.APPROVED
            else HandoffState.REJECTED
        )
        intake = intake.record_handoff(handoff, downstream_job_id=job.job_id.value)
        await self._intake.repository.save(intake)
        if decision == ApprovalDecision.REJECT:
            return await self._save(
                run.advance(CreativeLoopState.REJECTED, datetime.now(UTC), "creative:rejected")
            )
        release = project_creative_release(intake, job)
        return await self._save(
            run.advance(
                CreativeLoopState.AWAITING_ADS_OUTCOME,
                datetime.now(UTC),
                f"creative:approved:{release.creative_version_id}",
                approved_creative_version_id=release.creative_version_id,
            )
        )

    async def record_ads_outcome(
        self,
        run_id: str,
        case: CreativeLoopInput,
        outcome: AdsOutcome,
    ) -> CreativeLoopRun:
        run = await self._require(run_id, case)
        event_checksum = _checksum(asdict(outcome))
        if run.ads_event_id is not None:
            if (
                run.ads_event_id != outcome.event_id
                or run.ads_event_checksum_sha256 != event_checksum
            ):
                raise CreativeLoopEventDriftError(
                    "Ads event identity was reused with changed evidence"
                )
            return run
        if run.state != CreativeLoopState.AWAITING_ADS_OUTCOME:
            raise ValueError("Creative loop is not awaiting an Ads outcome")
        if run.creative_job_id is None or run.initial_intake_run_id is None:
            raise ValueError("Creative loop is missing its Creative release")
        intake = await self._intake.repository.get(run.initial_intake_run_id)
        job = await self._creative.repository.get_job(
            CreativeJobId.from_string(run.creative_job_id)
        )
        if intake is None or job is None:
            raise ValueError("Creative release records not found")
        release = project_creative_release(intake, job)
        if (
            outcome.mapping_status == EvidenceStatus.KNOWN
            and outcome.creative_version_id != release.creative_version_id
        ):
            raise ValueError("Ads outcome does not match the approved Creative version")
        performance_request = build_post_ads_request(
            case,
            outcome,
            creative_id=release.creative_id,
            brand_id=release.brand_id,
            sku_id=release.sku_id,
        )
        performance = (await self._performance.execute(performance_request)).run
        feedback_request = project_feedback_request(
            case.source_run_id,
            release,
            performance,
            outcome,
        )
        feedback = (await self._feedback.execute(feedback_request)).run
        state = self._feedback_state(feedback.state)
        return await self._save(
            run.advance(
                state,
                datetime.now(UTC),
                f"ads-outcome:{outcome.event_id}:{state.value}",
                ads_event_id=outcome.event_id,
                ads_event_checksum_sha256=event_checksum,
                post_ads_performance_run_id=performance.run_id,
                feedback_run_id=feedback.run_id,
                lesson_id=feedback.lesson.lesson_id if feedback.lesson else None,
            )
        )

    async def decide_lesson(
        self,
        run_id: str,
        lesson_id: str,
        decision: FeedbackDecision,
        reviewer_alias: str,
        reason: str,
        case: CreativeLoopInput,
        learning_proposal_id: str | None = None,
    ) -> CreativeLoopRun:
        run = await self._require(run_id, case)
        if run.feedback_run_id is None:
            raise ValueError("Creative loop is not awaiting a lesson decision")
        feedback = await self._feedback.repository.get(run.feedback_run_id)
        if feedback is None:
            raise ValueError("Creative feedback run not found")
        if run.state != CreativeLoopState.AWAITING_LESSON_APPROVAL:
            if feedback.decision == decision and feedback.decision_lesson_id == lesson_id:
                return run
            raise ValueError("Creative loop is not awaiting a lesson decision")
        if feedback.decision is None:
            feedback = await self._feedback.decide(
                feedback.run_id,
                lesson_id,
                decision,
                reviewer_alias,
                reason,
                learning_proposal_id,
            )
        elif (
            feedback.decision != decision
            or feedback.decision_lesson_id != lesson_id
            or feedback.decision_learning_proposal_id != learning_proposal_id
        ):
            raise ValueError("Lesson decision conflicts with the recorded decision")
        if decision == FeedbackDecision.REJECT:
            return await self._save(
                run.advance(CreativeLoopState.COMPLETED, datetime.now(UTC), "lesson:rejected")
            )
        if decision == FeedbackDecision.DEFER:
            return await self._save(
                run.advance(CreativeLoopState.DEFERRED, datetime.now(UTC), "lesson:deferred")
            )
        trigger = project_feedback_trigger(feedback)
        intake_case = build_next_intake_case(
            case.intake_template, case.context_snapshot_id, trigger
        )
        outcome = await self._intake.run(
            CreativeIntakeFixture((intake_case,)),
            dispatch_m1=True,
            preparation_config=self._preparation_config,
            config_dir=self._config_dir,
        )
        intake = outcome.runs[0]
        state = self._next_intake_state(intake)
        return await self._save(
            run.advance(
                state,
                datetime.now(UTC),
                f"next-intake:{intake.run_id}:{state.value}",
                next_intake_run_id=intake.run_id,
                next_creative_job_id=(intake.release.downstream_job_id if intake.release else None),
            )
        )

    async def _require(self, run_id: str, case: CreativeLoopInput) -> CreativeLoopRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise ValueError("Creative loop run not found")
        if run.input_snapshot_id != case.input_snapshot_id:
            raise ValueError("Creative loop input snapshot does not match the persisted run")
        if run.source_checksum_sha256 != case.source_checksum_sha256:
            raise CreativeLoopInputDriftError("Persisted Creative loop input has drifted")
        return run

    async def _reconcile_demand_decision(
        self,
        run: CreativeLoopRun,
        evaluation_id: str,
        decision: PerformanceDecision,
    ) -> CreativeLoopRun:
        performance = await self._performance.repository.get(run.initial_performance_run_id)
        if (
            performance is not None
            and performance.decision == decision
            and performance.decision_evaluation_id == evaluation_id
        ):
            return run
        raise ValueError("Creative loop is not awaiting a demand decision")

    async def _save(self, run: CreativeLoopRun) -> CreativeLoopRun:
        await self._repository.save(run)
        return run

    @staticmethod
    def _initial_state(state: EvaluationState) -> CreativeLoopState:
        if state == EvaluationState.NEEDS_EVIDENCE:
            return CreativeLoopState.NEEDS_EVIDENCE
        if state == EvaluationState.BLOCKED_CONFLICT:
            return CreativeLoopState.BLOCKED_CONFLICT
        return CreativeLoopState.AWAITING_DEMAND_APPROVAL

    @staticmethod
    def _intake_state(intake) -> CreativeLoopState:
        if intake.state == IntakeState.BLOCKED_CONFLICT:
            return CreativeLoopState.BLOCKED_CONFLICT
        if intake.state != IntakeState.RELEASED or intake.release is None:
            return CreativeLoopState.NEEDS_EVIDENCE
        if intake.release.handoff_state != HandoffState.AWAITING_APPROVAL:
            raise ValueError("Initial Creative dispatch did not reach final approval")
        return CreativeLoopState.AWAITING_CREATIVE_APPROVAL

    @staticmethod
    def _feedback_state(state: FeedbackRunState) -> CreativeLoopState:
        if state == FeedbackRunState.READY_FOR_REVIEW:
            return CreativeLoopState.AWAITING_LESSON_APPROVAL
        if state == FeedbackRunState.BLOCKED_CONFLICT:
            return CreativeLoopState.BLOCKED_CONFLICT
        if state == FeedbackRunState.NEEDS_EVIDENCE:
            return CreativeLoopState.NEEDS_EVIDENCE
        return CreativeLoopState.COMPLETED

    @staticmethod
    def _next_intake_state(intake) -> CreativeLoopState:
        if intake.state == IntakeState.BLOCKED_CONFLICT:
            return CreativeLoopState.BLOCKED_CONFLICT
        if (
            intake.state == IntakeState.RELEASED
            and intake.release is not None
            and intake.release.handoff_state == HandoffState.BRIEF_READY
        ):
            return CreativeLoopState.NEXT_BRIEF_READY
        return CreativeLoopState.NEEDS_EVIDENCE


def _checksum(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["CreativeLoopResult", "RunCreativeLoop"]
