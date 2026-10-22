"""Composition root for the synthetic Performance decision pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_performance_decision_artifacts
from .adapters.baml_opportunity import BamlCreativeOpportunityAnalyzer
from .adapters.sqlite_repository import SqlitePerformanceDecisionRepository
from .application.evaluation import (
    PerformanceDecisionRequest,
    PerformanceDecisionResult,
    RunPerformanceDecision,
)
from .config.fixtures import PerformanceDecisionFixture
from .config.opportunity import OpportunityConfig
from .domain.models import ExperimentProposal, PerformanceDecision, PerformanceDecisionRun
from .ports.interfaces import IPerformanceDecisionRepository


@dataclass(frozen=True)
class PerformanceRuntimeResult:
    runs: tuple[PerformanceDecisionRun, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]


class PerformanceDecisionRuntime:
    def __init__(
        self,
        repository: IPerformanceDecisionRepository,
        artifact_store: ArtifactStore,
        use_case: RunPerformanceDecision | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._use_case = use_case

    async def run(self, fixture: PerformanceDecisionFixture) -> PerformanceRuntimeResult:
        if self._use_case is None:
            raise ValueError("This Performance decision runtime is read-only")
        runs: list[PerformanceDecisionRun] = []
        manifests: list[Path] = []
        duplicates = 0
        for request in fixture.requests():
            result: PerformanceDecisionResult = await self._use_case.execute(request)
            runs.append(result.run)
            path = self._manifest_path(result.run)
            if result.duplicate:
                duplicates += 1
                if path.exists():
                    manifests.append(path)
            else:
                manifests.append(
                    write_performance_decision_artifacts(self.artifact_store, result.run)
                )
        return PerformanceRuntimeResult(tuple(runs), duplicates, tuple(manifests))

    async def execute(self, request: PerformanceDecisionRequest) -> PerformanceDecisionResult:
        """Execute one typed request for an application-level coordinator."""
        if self._use_case is None:
            raise ValueError("This Performance decision runtime is read-only")
        result = await self._use_case.execute(request)
        if not result.duplicate:
            write_performance_decision_artifacts(self.artifact_store, result.run)
        return result

    async def decide(
        self,
        run_id: str,
        evaluation_id: str,
        decision: PerformanceDecision,
        reviewer_alias: str,
        reason: str,
        proposal_id: str | None = None,
        edited_proposal: ExperimentProposal | None = None,
    ) -> PerformanceDecisionRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ValueError("Performance decision run not found")
        updated = run.decide(
            decision,
            evaluation_id,
            reviewer_alias,
            reason,
            datetime.now(UTC),
            proposal_id,
            edited_proposal,
        )
        await self.repository.save(updated)
        write_performance_decision_artifacts(self.artifact_store, updated)
        return updated

    def _manifest_path(self, run: PerformanceDecisionRun) -> Path:
        return self.artifact_store.path("performance-decisions", run.source_run_id, "manifest.json")


def build_fixture_runtime(
    db_path: Path,
    artifacts_root: Path,
    *,
    opportunity_config: OpportunityConfig | None = None,
    opportunity_api_key: str | None = None,
) -> PerformanceDecisionRuntime:
    repository = SqlitePerformanceDecisionRepository(db_path)
    analyzer = (
        BamlCreativeOpportunityAnalyzer(opportunity_config, api_key=opportunity_api_key)
        if opportunity_config is not None
        else None
    )
    return PerformanceDecisionRuntime(
        repository,
        ArtifactStore(artifacts_root),
        RunPerformanceDecision(repository, analyzer),
    )


def build_read_runtime(db_path: Path, artifacts_root: Path) -> PerformanceDecisionRuntime:
    return PerformanceDecisionRuntime(
        SqlitePerformanceDecisionRepository(db_path), ArtifactStore(artifacts_root)
    )


__all__ = [
    "PerformanceDecisionRuntime",
    "PerformanceRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
