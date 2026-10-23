"""Composition root for the synthetic Marketing Creative closed loop."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path

from ai_content.domains.marketing.creative.bootstrap import (
    build_runtime as build_creative_runtime,
)
from ai_content.domains.marketing.creative.domain.entities import ApprovalDecision
from ai_content.domains.marketing.creative_feedback.bootstrap import (
    build_fixture_runtime as build_feedback_runtime,
)
from ai_content.domains.marketing.creative_feedback.config.learning import (
    PerformanceLearningConfig,
)
from ai_content.domains.marketing.creative_feedback.domain.models import FeedbackDecision
from ai_content.domains.marketing.creative_intake.adapters.artifacts import (
    write_creative_intake_artifacts,
)
from ai_content.domains.marketing.creative_intake.bootstrap import (
    build_fixture_runtime as build_intake_runtime,
)
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    build_fixture_runtime as build_performance_runtime,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    PerformanceDecision,
)
from ai_content.platform.artifacts.service import ArtifactService
from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_creative_loop_artifacts
from .adapters.sqlite_repository import SqliteCreativeLoopRepository
from .application.workflow import CreativeLoopResult, RunCreativeLoop
from .config.fixtures import (
    CreativeLoopFixture,
    load_creative_loop_fixture,
    load_local_creative_loop_case,
)
from .domain.models import CreativeLoopRun
from .ports.contracts import AdsOutcome
from .ports.interfaces import ICreativeLoopRepository


@dataclass(frozen=True)
class CreativeLoopRuntimeResult:
    runs: tuple[CreativeLoopRun, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]


class CreativeLoopRuntime:
    def __init__(
        self,
        repository: ICreativeLoopRepository,
        artifact_store: ArtifactStore,
        fixture: CreativeLoopFixture,
        workflow: RunCreativeLoop,
        performance_runtime,
        intake_runtime,
        creative_runtime,
        feedback_runtime,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.fixture = fixture
        self.workflow = workflow
        self.performance_runtime = performance_runtime
        self.intake_runtime = intake_runtime
        self.creative_runtime = creative_runtime
        self.feedback_runtime = feedback_runtime
        self.artifact_service = artifact_service

    async def run(self) -> CreativeLoopRuntimeResult:
        runs: list[CreativeLoopRun] = []
        manifests: list[Path] = []
        duplicates = 0
        for case in self.fixture.cases:
            result: CreativeLoopResult = await self.workflow.start(case)
            runs.append(result.run)
            duplicates += int(result.duplicate)
            manifests.append(write_creative_loop_artifacts(self.artifact_store, result.run))
            await self._publish_artifacts(result.run)
        return CreativeLoopRuntimeResult(tuple(runs), duplicates, tuple(manifests))

    async def start_case(self, case_id: str) -> CreativeLoopRun:
        """Start one exact fixture case for event-driven execution."""
        result = await self.workflow.start(self.fixture.case(case_id))
        write_creative_loop_artifacts(self.artifact_store, result.run)
        await self._publish_artifacts(result.run)
        return result.run

    async def decide_demand(
        self,
        run_id: str,
        evaluation_id: str,
        decision: PerformanceDecision,
        reviewer_alias: str,
        reason: str,
    ) -> CreativeLoopRun:
        run = await self._run(run_id)
        updated = await self._run_with_artifact_checkpoint(
            run,
            self.workflow.decide_demand(
                run_id,
                evaluation_id,
                decision,
                reviewer_alias,
                reason,
                self.fixture.case(run.input_snapshot_id),
            ),
        )
        write_creative_loop_artifacts(self.artifact_store, updated)
        await self._publish_artifacts(updated)
        return updated

    async def decide_creative(
        self,
        run_id: str,
        decision: ApprovalDecision,
        reviewer_alias: str,
        reason: str,
    ) -> CreativeLoopRun:
        run = await self._run(run_id)
        updated = await self.workflow.decide_creative(
            run_id,
            decision,
            reviewer_alias,
            reason,
            self.fixture.case(run.input_snapshot_id),
        )
        intake = (
            await self.intake_runtime.repository.get(updated.initial_intake_run_id)
            if updated.initial_intake_run_id
            else None
        )
        if intake is not None:
            write_creative_intake_artifacts(self.intake_runtime.artifact_store, intake, None)
        write_creative_loop_artifacts(self.artifact_store, updated)
        await self._publish_artifacts(updated)
        return updated

    async def record_ads_outcome(self, run_id: str, outcome: AdsOutcome) -> CreativeLoopRun:
        run = await self._run(run_id)
        updated = await self.workflow.record_ads_outcome(
            run_id, self.fixture.case(run.input_snapshot_id), outcome
        )
        write_creative_loop_artifacts(self.artifact_store, updated)
        await self._publish_artifacts(updated)
        return updated

    async def decide_lesson(
        self,
        run_id: str,
        lesson_id: str,
        decision: FeedbackDecision,
        reviewer_alias: str,
        reason: str,
        learning_proposal_id: str | None = None,
    ) -> CreativeLoopRun:
        run = await self._run(run_id)
        updated = await self.workflow.decide_lesson(
            run_id,
            lesson_id,
            decision,
            reviewer_alias,
            reason,
            self.fixture.case(run.input_snapshot_id),
            learning_proposal_id,
        )
        write_creative_loop_artifacts(self.artifact_store, updated)
        await self._publish_artifacts(updated)
        return updated

    async def _publish_artifacts(self, run: CreativeLoopRun) -> None:
        if self.artifact_service is None:
            return
        await self.artifact_service.publish_tree(
            self.artifact_store.root,
            owner_type="creative_loop",
            owner_id=run.run_id,
        )

    async def _run_with_artifact_checkpoint(
        self,
        run: CreativeLoopRun,
        operation: Awaitable[CreativeLoopRun],
    ) -> CreativeLoopRun:
        """Publish durable partial evidence before propagating a workflow failure."""
        try:
            return await operation
        except Exception:
            await self._publish_artifacts(run)
            raise

    async def _run(self, run_id: str) -> CreativeLoopRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ValueError("Creative loop run not found")
        return run

    def close(self) -> None:
        self.repository.close()
        self.performance_runtime.repository.close()
        self.intake_runtime.repository.close()
        self.creative_runtime.repository.close()
        self.feedback_runtime.repository.close()


def build_runtime(
    db_path: Path,
    artifacts_root: Path,
    config_dir: Path = Path("config"),
    fixture_path: Path = Path("config/fixtures/creative_loop_synthetic.json"),
    preparation_config: Path = Path("config/preparation/synthetic.json"),
    preparation_api_key: str | None = None,
    learning_config: PerformanceLearningConfig | None = None,
    learning_api_key: str | None = None,
    local_loop_path: Path | None = None,
) -> CreativeLoopRuntime:
    repository = SqliteCreativeLoopRepository(db_path)
    store = ArtifactStore(artifacts_root)
    fixture = (
        load_local_creative_loop_case(local_loop_path)
        if local_loop_path is not None
        else load_creative_loop_fixture(fixture_path)
    )
    performance = build_performance_runtime(db_path, artifacts_root)
    intake = build_intake_runtime(
        db_path,
        artifacts_root,
        preparation_api_key=preparation_api_key,
    )
    creative = build_creative_runtime(db_path, artifacts_root, config_dir=config_dir)
    feedback = build_feedback_runtime(
        db_path,
        artifacts_root,
        learning_config=learning_config,
        learning_api_key=learning_api_key,
    )
    workflow = RunCreativeLoop(
        repository,
        performance,
        intake,
        creative,
        feedback,
        preparation_config=preparation_config,
        config_dir=config_dir,
    )
    return CreativeLoopRuntime(
        repository,
        store,
        fixture,
        workflow,
        performance,
        intake,
        creative,
        feedback,
    )


__all__ = ["CreativeLoopRuntime", "CreativeLoopRuntimeResult", "build_runtime"]
