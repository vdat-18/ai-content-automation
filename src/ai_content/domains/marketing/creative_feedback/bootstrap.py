"""Composition root for the synthetic Creative feedback pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_creative_feedback_artifacts
from .adapters.baml_learning import BamlPerformanceLearningAnalyzer
from .adapters.sqlite_repository import SqliteCreativeFeedbackRepository
from .application.evaluation import (
    CreativeFeedbackRequest,
    CreativeFeedbackResult,
    RunCreativeFeedback,
)
from .config.fixtures import CreativeFeedbackFixture
from .config.learning import PerformanceLearningConfig
from .domain.models import CreativeFeedbackRun, FeedbackDecision
from .ports.interfaces import ICreativeFeedbackRepository


@dataclass(frozen=True)
class CreativeFeedbackRuntimeResult:
    runs: tuple[CreativeFeedbackRun, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]


class CreativeFeedbackRuntime:
    def __init__(
        self,
        repository: ICreativeFeedbackRepository,
        artifact_store: ArtifactStore,
        use_case: RunCreativeFeedback | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._use_case = use_case

    async def run(self, fixture: CreativeFeedbackFixture) -> CreativeFeedbackRuntimeResult:
        if self._use_case is None:
            raise ValueError("This Creative feedback runtime is read-only")
        runs: list[CreativeFeedbackRun] = []
        manifests: list[Path] = []
        duplicates = 0
        for request in fixture.requests():
            result: CreativeFeedbackResult = await self._use_case.execute(request)
            runs.append(result.run)
            manifest = self._manifest_path(result.run)
            if result.duplicate:
                duplicates += 1
                if manifest.exists():
                    manifests.append(manifest)
            else:
                manifests.append(write_creative_feedback_artifacts(self.artifact_store, result.run))
        return CreativeFeedbackRuntimeResult(tuple(runs), duplicates, tuple(manifests))

    async def execute(self, request: CreativeFeedbackRequest) -> CreativeFeedbackResult:
        """Execute one typed request for an application-level coordinator."""
        if self._use_case is None:
            raise ValueError("This Creative feedback runtime is read-only")
        result = await self._use_case.execute(request)
        if not result.duplicate:
            write_creative_feedback_artifacts(self.artifact_store, result.run)
        return result

    async def decide(
        self,
        run_id: str,
        lesson_id: str,
        decision: FeedbackDecision,
        reviewer_alias: str,
        reason: str,
        learning_proposal_id: str | None = None,
    ) -> CreativeFeedbackRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ValueError("Creative feedback run not found")
        updated = run.decide(
            decision,
            lesson_id,
            reviewer_alias,
            reason,
            datetime.now(UTC),
            learning_proposal_id,
        )
        await self.repository.save(updated)
        write_creative_feedback_artifacts(self.artifact_store, updated)
        return updated

    def _manifest_path(self, run: CreativeFeedbackRun) -> Path:
        return self.artifact_store.path("creative-feedback", run.source_run_id, "manifest.json")


def build_fixture_runtime(
    db_path: Path,
    artifacts_root: Path,
    *,
    learning_config: PerformanceLearningConfig | None = None,
    learning_api_key: str | None = None,
) -> CreativeFeedbackRuntime:
    repository = SqliteCreativeFeedbackRepository(db_path)
    analyzer = (
        BamlPerformanceLearningAnalyzer(learning_config, api_key=learning_api_key)
        if learning_config is not None
        else None
    )
    return CreativeFeedbackRuntime(
        repository, ArtifactStore(artifacts_root), RunCreativeFeedback(repository, analyzer)
    )


def build_read_runtime(db_path: Path, artifacts_root: Path) -> CreativeFeedbackRuntime:
    return CreativeFeedbackRuntime(
        SqliteCreativeFeedbackRepository(db_path), ArtifactStore(artifacts_root)
    )


__all__ = [
    "CreativeFeedbackRuntime",
    "CreativeFeedbackRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
