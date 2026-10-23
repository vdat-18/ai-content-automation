"""Composition root for the synthetic Creative intake and M1 handoff pilot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ai_content.domains.marketing.creative.bootstrap import (
    build_runtime as build_creative_runtime,
)
from ai_content.domains.marketing.creative.config.preparation import (
    PreparationConfig,
    load_preparation_config,
)
from ai_content.domains.marketing.creative.domain.entities import CreativeJobStatus
from ai_content.domains.marketing.creative.ports.interfaces import ICreativeRepository
from ai_content.domains.marketing.creative.ports.preparation_store import PreparedBrief
from ai_content.domains.marketing.creative.preparation_runtime import (
    build_preparation_runtime,
)
from ai_content.platform.ai_usage import AIUsageTracker
from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_creative_intake_artifacts
from .adapters.creative_projection import CompiledCreativeTask, compile_creative_task
from .adapters.sqlite_repository import SqliteCreativeIntakeRepository
from .application.contracts import CreativeIntakeFixture
from .application.resolution import ResolveCreativeIntake
from .domain.models import CreativeIntakeRun, HandoffState, IntakeState
from .ports.interfaces import ICreativeIntakeRepository


@dataclass(frozen=True)
class CreativeIntakeRuntimeResult:
    runs: tuple[CreativeIntakeRun, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]
    prepared_briefs: tuple[PreparedBrief | None, ...]


class CreativeIntakeRuntime:
    def __init__(
        self,
        repository: ICreativeIntakeRepository,
        artifact_store: ArtifactStore,
        use_case: ResolveCreativeIntake | None,
        db_path: Path | None,
        artifacts_root: Path,
        creative_repository: ICreativeRepository | None = None,
        preparation_api_key: str | None = None,
        usage_tracker: AIUsageTracker | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._use_case = use_case
        self._db_path = db_path
        self._artifacts_root = artifacts_root
        self._creative_repository = creative_repository
        self._preparation_api_key = preparation_api_key
        self._usage_tracker = usage_tracker

    async def run(
        self,
        fixture: CreativeIntakeFixture,
        *,
        dispatch_m1: bool = False,
        dispatch_creative: bool = False,
        preparation_config: Path | PreparationConfig = Path("config/preparation/synthetic.json"),
        config_dir: Path = Path("config"),
        image_reader: Callable[[str], bytes] | None = None,
    ) -> CreativeIntakeRuntimeResult:
        if self._use_case is None:
            raise ValueError("This Creative intake runtime is read-only")
        runs: list[CreativeIntakeRun] = []
        manifests: list[Path] = []
        prepared_briefs: list[PreparedBrief | None] = []
        duplicates = 0
        dispatch_preparation = dispatch_m1 or dispatch_creative
        config = (
            (
                preparation_config
                if isinstance(preparation_config, PreparationConfig)
                else load_preparation_config(preparation_config)
            )
            if dispatch_preparation
            else None
        )
        for case in fixture.cases:
            prepared_brief: PreparedBrief | None = None
            result = await self._use_case.execute(case.request)
            run = result.run
            if result.duplicate:
                duplicates += 1
            compiled: CompiledCreativeTask | None = None
            if run.state == IntakeState.RELEASED:
                compiled = compile_creative_task(
                    run, case.work_item_template, case.context_template
                )
                if dispatch_preparation and config is not None and run.release is not None:
                    if not dispatch_creative and run.release.handoff_state not in {
                        HandoffState.READY,
                        HandoffState.BRIEF_READY,
                    }:
                        manifests.append(
                            write_creative_intake_artifacts(self.artifact_store, run, compiled)
                        )
                        runs.append(run)
                        prepared_briefs.append(None)
                        continue
                    preparation = build_preparation_runtime(
                        self._db_path,
                        self._artifacts_root,
                        config,
                        compiled.context,
                        api_key=self._preparation_api_key,
                        config_dir=config_dir,
                        repository=self._creative_repository,
                        usage_tracker=self._usage_tracker,
                        image_reader=image_reader,
                    )
                    try:
                        preparation_result = await preparation.prepare(compiled.work_item)
                        if preparation_result.success:
                            prepared_brief = preparation_result.output
                            run = run.record_handoff(
                                HandoffState.BRIEF_READY,
                                downstream_job_id=str(preparation_result.job.job_id),
                            )
                            if dispatch_creative:
                                creative = build_creative_runtime(
                                    self._db_path,
                                    self._artifacts_root,
                                    config_dir=config_dir,
                                    preparation=preparation,
                                    repository=self._creative_repository,
                                )
                                try:
                                    creative_result = await creative.run(compiled.work_item)
                                finally:
                                    creative.repository.close()
                                job = creative_result.result.job
                                if creative_result.result.success and job is not None:
                                    state_by_status = {
                                        CreativeJobStatus.AWAITING_APPROVAL: (
                                            HandoffState.AWAITING_APPROVAL
                                        ),
                                        CreativeJobStatus.APPROVED: HandoffState.APPROVED,
                                        CreativeJobStatus.REJECTED: HandoffState.REJECTED,
                                        CreativeJobStatus.ARCHIVED: HandoffState.ARCHIVED,
                                    }
                                    handoff_state = state_by_status.get(job.status)
                                    if handoff_state is None:
                                        raise RuntimeError(
                                            "Successful Creative workflow ended in an invalid state"
                                        )
                                    run = run.record_handoff(
                                        handoff_state,
                                        downstream_job_id=str(job.job_id),
                                    )
                                else:
                                    run = run.record_handoff(
                                        HandoffState.FAILED,
                                        downstream_job_id=(
                                            str(job.job_id) if job is not None else None
                                        ),
                                        error=(
                                            creative_result.result.exception_type
                                            or "creative-workflow-failed"
                                        ),
                                    )
                        else:
                            run = run.record_handoff(
                                HandoffState.FAILED,
                                downstream_job_id=str(preparation_result.job.job_id),
                                error=preparation_result.exception_type or "m1-preparation-failed",
                            )
                    finally:
                        preparation.repository.close()
                    await self.repository.save(run)
            manifests.append(write_creative_intake_artifacts(self.artifact_store, run, compiled))
            runs.append(run)
            prepared_briefs.append(prepared_brief)
        return CreativeIntakeRuntimeResult(
            tuple(runs), duplicates, tuple(manifests), tuple(prepared_briefs)
        )


def build_fixture_runtime(
    db_path: Path,
    artifacts_root: Path,
    *,
    preparation_api_key: str | None = None,
) -> CreativeIntakeRuntime:
    repository = SqliteCreativeIntakeRepository(db_path)
    return CreativeIntakeRuntime(
        repository,
        ArtifactStore(artifacts_root),
        ResolveCreativeIntake(repository),
        db_path,
        artifacts_root,
        preparation_api_key=preparation_api_key,
    )


def build_read_runtime(db_path: Path, artifacts_root: Path) -> CreativeIntakeRuntime:
    return CreativeIntakeRuntime(
        SqliteCreativeIntakeRepository(db_path),
        ArtifactStore(artifacts_root),
        None,
        db_path,
        artifacts_root,
    )


__all__ = [
    "CreativeIntakeRuntime",
    "CreativeIntakeRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
