"""Composition root for the synthetic Creator Operations pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_creator_artifacts
from .adapters.sqlite_repository import SqliteCreatorRunRepository
from .application.evaluation import (
    AppendCreatorEvidence,
    AppendCreatorEvidenceRequest,
    CreatorRunResult,
    RunCreatorEvaluation,
)
from .domain.models import CandidateDecision, CreatorEvaluationRun
from .ports.interfaces import ICreatorRunRepository

if TYPE_CHECKING:
    from .config.fixtures import CreatorEvaluationFixture


@dataclass(frozen=True)
class CreatorRuntimeResult:
    run: CreatorEvaluationRun
    duplicate: bool
    manifest_path: Path | None


class CreatorRuntime:
    def __init__(
        self,
        repository: ICreatorRunRepository,
        artifact_store: ArtifactStore,
        use_case: RunCreatorEvaluation | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._use_case = use_case

    async def run(self, fixture: CreatorEvaluationFixture) -> CreatorRuntimeResult:
        if self._use_case is None:
            raise ValueError("This Creator runtime is read-only")
        result: CreatorRunResult = await self._use_case.execute(fixture.request())
        path = self._manifest_path(result.run)
        if result.duplicate:
            return CreatorRuntimeResult(result.run, True, path if path.exists() else None)
        return CreatorRuntimeResult(
            result.run, False, write_creator_artifacts(self.artifact_store, result.run)
        )

    async def decide(
        self,
        run_id: str,
        evaluation_id: str,
        decision: CandidateDecision,
        reviewer_alias: str,
        reason: str,
    ) -> CreatorEvaluationRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ValueError("Creator evaluation run not found")
        updated = run.decide(decision, evaluation_id, reviewer_alias, reason, datetime.now(UTC))
        await self.repository.save(updated)
        write_creator_artifacts(self.artifact_store, updated)
        return updated

    async def append_evidence(self, request: AppendCreatorEvidenceRequest) -> CreatorEvaluationRun:
        result = await AppendCreatorEvidence(self.repository).execute(request)
        if not result.duplicate:
            write_creator_artifacts(self.artifact_store, result.run)
        return result.run

    def _manifest_path(self, run: CreatorEvaluationRun) -> Path:
        return self.artifact_store.path("creator-operations", run.source_run_id, "manifest.json")


def build_fixture_runtime(db_path: Path, artifacts_root: Path) -> CreatorRuntime:
    repository = SqliteCreatorRunRepository(db_path)
    return CreatorRuntime(
        repository,
        ArtifactStore(artifacts_root),
        RunCreatorEvaluation(repository),
    )


def build_read_runtime(db_path: Path, artifacts_root: Path) -> CreatorRuntime:
    return CreatorRuntime(SqliteCreatorRunRepository(db_path), ArtifactStore(artifacts_root))


__all__ = [
    "CreatorRuntime",
    "CreatorRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
