"""Persistent command boundary for the unified Creative loop."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJobId,
)
from ai_content.domains.marketing.creative_feedback.domain.models import (
    EvidenceStatus,
    FeedbackDecision,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    MetricStatus,
    PerformanceDecision,
)
from ai_content.platform.artifacts import ObjectStorageError
from ai_content.platform.execution import (
    CommandScheduler,
    EnqueueCommand,
    ExecutionCommand,
    PermanentCommandError,
    QueueCall,
    TransientCommandError,
)

from ..bootstrap import CreativeLoopRuntime, build_runtime
from ..domain.models import CreativeLoopRun
from ..ports.contracts import AdsOutcome, CreativeLoopInput
from ..ports.interfaces import CreativeLoopEventDriftError, CreativeLoopInputDriftError


class CreativeLoopCommandName(StrEnum):
    START = "creative_loop.start"
    DEMAND_DECISION = "creative_loop.demand_decision"
    CREATIVE_DECISION = "creative_loop.creative_decision"
    ADS_OUTCOME = "creative_loop.ads_outcome"
    LESSON_DECISION = "creative_loop.lesson_decision"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartPayload(_Payload):
    input_snapshot_id: str = Field(min_length=1)
    source_checksum_sha256: str = Field(min_length=64, max_length=64)


class DemandDecisionPayload(_Payload):
    run_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    decision: PerformanceDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CreativeDecisionPayload(_Payload):
    run_id: str = Field(min_length=1)
    creative_job_id: str = Field(min_length=1)
    creative_version_ids: tuple[str, ...] = Field(min_length=1)
    decision: ApprovalDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AdsOutcomeData(_Payload):
    event_id: str = Field(min_length=1)
    creative_version_id: str | None = Field(default=None, min_length=1)
    platform: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    adset_id: str = Field(min_length=1)
    ad_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    purchases: Decimal | None = None
    roas: Decimal | None = None
    cost_per_atc: Decimal | None = None
    evidence_status: MetricStatus
    mapping_status: EvidenceStatus
    observed_at: datetime


class AdsOutcomePayload(_Payload):
    run_id: str = Field(min_length=1)
    outcome: AdsOutcomeData


class LessonDecisionPayload(_Payload):
    run_id: str = Field(min_length=1)
    lesson_id: str = Field(min_length=1)
    learning_proposal_id: str | None = Field(default=None, min_length=1)
    decision: FeedbackDecision
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CreativeLoopCommandService:
    def __init__(self, queue: CommandScheduler) -> None:
        self._queue = queue

    def enqueue_start(self, source: CreativeLoopInput) -> QueueCall[tuple[ExecutionCommand, bool]]:
        payload = StartPayload(
            input_snapshot_id=source.input_snapshot_id,
            source_checksum_sha256=source.source_checksum_sha256,
        )
        return self._enqueue(
            CreativeLoopCommandName.START,
            f"creative-loop:start:{source.source_run_id}",
            payload,
        )

    def enqueue_demand_decision(
        self,
        run: CreativeLoopRun,
        evaluation_id: str,
        decision: PerformanceDecision,
        reviewer_alias: str,
        reason: str,
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        payload = DemandDecisionPayload(
            run_id=run.run_id,
            evaluation_id=evaluation_id,
            decision=decision,
            reviewer_alias=reviewer_alias,
            reason=reason,
        )
        return self._enqueue(
            CreativeLoopCommandName.DEMAND_DECISION,
            f"creative-loop:demand:{run.run_id}:{evaluation_id}",
            payload,
            run.run_id,
        )

    def enqueue_creative_decision(
        self,
        run: CreativeLoopRun,
        creative_version_ids: tuple[str, ...],
        decision: ApprovalDecision,
        reviewer_alias: str,
        reason: str,
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        if run.creative_job_id is None:
            raise ValueError("Creative loop has no exact Creative job to decide")
        payload = CreativeDecisionPayload(
            run_id=run.run_id,
            creative_job_id=run.creative_job_id,
            creative_version_ids=creative_version_ids,
            decision=decision,
            reviewer_alias=reviewer_alias,
            reason=reason,
        )
        return self._enqueue(
            CreativeLoopCommandName.CREATIVE_DECISION,
            f"creative-loop:creative:{run.run_id}:{run.creative_job_id}",
            payload,
            run.run_id,
        )

    def enqueue_ads_outcome(
        self, run: CreativeLoopRun, outcome: AdsOutcome
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        payload = AdsOutcomePayload(
            run_id=run.run_id,
            outcome=AdsOutcomeData.model_validate(asdict(outcome)),
        )
        return self._enqueue(
            CreativeLoopCommandName.ADS_OUTCOME,
            f"creative-loop:ads:{run.run_id}:{outcome.event_id}",
            payload,
            run.run_id,
        )

    def enqueue_lesson_decision(
        self,
        run: CreativeLoopRun,
        lesson_id: str,
        decision: FeedbackDecision,
        reviewer_alias: str,
        reason: str,
        learning_proposal_id: str | None = None,
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        payload = LessonDecisionPayload(
            run_id=run.run_id,
            lesson_id=lesson_id,
            decision=decision,
            reviewer_alias=reviewer_alias,
            reason=reason,
            learning_proposal_id=learning_proposal_id,
        )
        return self._enqueue(
            CreativeLoopCommandName.LESSON_DECISION,
            f"creative-loop:lesson:{run.run_id}:{lesson_id}",
            payload,
            run.run_id,
        )

    def _enqueue(
        self,
        name: CreativeLoopCommandName,
        dedupe_key: str,
        payload: BaseModel,
        workflow_run_id: str | None = None,
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        return self._queue.enqueue(
            EnqueueCommand(
                name=name.value,
                dedupe_key=dedupe_key,
                payload=payload.model_dump(mode="json"),
                workflow_run_id=workflow_run_id,
            )
        )


class CreativeLoopCommandDispatcher:
    def __init__(
        self,
        db_path: Path | None,
        artifacts_root: Path,
        config_dir: Path,
        fixture_path: Path,
        preparation_config: Path,
        preparation_api_key: str | None = None,
        runtime_factory: Callable[[], CreativeLoopRuntime] | None = None,
    ) -> None:
        self._db_path = db_path
        self._artifacts_root = artifacts_root
        self._config_dir = config_dir
        self._fixture_path = fixture_path
        self._preparation_config = preparation_config
        self._preparation_api_key = preparation_api_key
        self._runtime_factory = runtime_factory

    async def dispatch(self, command: ExecutionCommand) -> None:
        runtime = (
            self._runtime_factory()
            if self._runtime_factory is not None
            else build_runtime(
                self._db_path,
                self._artifacts_root,
                config_dir=self._config_dir,
                fixture_path=self._fixture_path,
                preparation_config=self._preparation_config,
                preparation_api_key=self._preparation_api_key,
            )
        )
        try:
            await self._dispatch(runtime, command)
        except (CreativeLoopInputDriftError, CreativeLoopEventDriftError, ValueError) as error:
            raise PermanentCommandError("INVALID_WORKFLOW_COMMAND", str(error)) from error
        except sqlite3.OperationalError as error:
            message = str(error)
            if "locked" in message.lower() or "busy" in message.lower():
                raise TransientCommandError("SQLITE_BUSY", message) from error
            raise
        except ObjectStorageError as error:
            raise TransientCommandError(
                "ARTIFACT_STORAGE_UNAVAILABLE",
                str(error),
            ) from error
        finally:
            runtime.close()

    async def _dispatch(self, runtime: CreativeLoopRuntime, command: ExecutionCommand) -> None:
        try:
            name = CreativeLoopCommandName(command.name)
            if name == CreativeLoopCommandName.START:
                payload = StartPayload.model_validate(command.payload)
                source = runtime.fixture.case(payload.input_snapshot_id)
                if source.source_checksum_sha256 != payload.source_checksum_sha256:
                    raise ValueError("Creative loop start command input has drifted")
                await runtime.start_case(payload.input_snapshot_id)
                return
            if name == CreativeLoopCommandName.DEMAND_DECISION:
                payload = DemandDecisionPayload.model_validate(command.payload)
                await runtime.decide_demand(
                    payload.run_id,
                    payload.evaluation_id,
                    payload.decision,
                    payload.reviewer_alias,
                    payload.reason,
                )
                return
            if name == CreativeLoopCommandName.CREATIVE_DECISION:
                payload = CreativeDecisionPayload.model_validate(command.payload)
                run = await runtime.repository.get(payload.run_id)
                if run is None or run.creative_job_id != payload.creative_job_id:
                    raise ValueError("Creative command no longer matches the exact workflow job")
                job = await runtime.creative_runtime.repository.get_job(
                    CreativeJobId.from_string(payload.creative_job_id)
                )
                if job is None or job.card is None:
                    raise ValueError("Creative approval card not found")
                current_versions = job.card.final_version_refs or (job.card.final_version_ref,)
                if payload.creative_version_ids != current_versions:
                    raise ValueError(
                        "Creative command no longer matches the exact approved version"
                    )
                await runtime.decide_creative(
                    payload.run_id,
                    payload.decision,
                    payload.reviewer_alias,
                    payload.reason,
                )
                return
            if name == CreativeLoopCommandName.ADS_OUTCOME:
                payload = AdsOutcomePayload.model_validate(command.payload)
                outcome = AdsOutcome(**payload.outcome.model_dump())
                await runtime.record_ads_outcome(payload.run_id, outcome)
                return
            if name == CreativeLoopCommandName.LESSON_DECISION:
                payload = LessonDecisionPayload.model_validate(command.payload)
                await runtime.decide_lesson(
                    payload.run_id,
                    payload.lesson_id,
                    payload.decision,
                    payload.reviewer_alias,
                    payload.reason,
                    payload.learning_proposal_id,
                )
                return
        except ValidationError as error:
            raise ValueError("Execution command payload is invalid") from error
        raise ValueError(f"Unsupported execution command: {command.name}")


__all__ = [
    "CreativeLoopCommandDispatcher",
    "CreativeLoopCommandName",
    "CreativeLoopCommandService",
]
