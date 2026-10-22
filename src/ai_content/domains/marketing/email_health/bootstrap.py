"""Composition root for the synthetic Email Operations health pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_email_health_artifacts
from .adapters.sqlite_repository import SqliteEmailHealthRepository
from .application.evaluation import EmailHealthResult, RunEmailHealthEvaluation
from .config.fixtures import EmailHealthFixture
from .domain.models import (
    EmailHealthRun,
    OperationalDecision,
    VerificationOutcome,
)
from .ports.interfaces import IEmailHealthRepository


@dataclass(frozen=True)
class EmailHealthRuntimeResult:
    runs: tuple[EmailHealthRun, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]


class EmailHealthRuntime:
    def __init__(
        self,
        repository: IEmailHealthRepository,
        artifact_store: ArtifactStore,
        use_case: RunEmailHealthEvaluation | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._use_case = use_case

    async def run(self, fixture: EmailHealthFixture) -> EmailHealthRuntimeResult:
        if self._use_case is None:
            raise ValueError("This Email health runtime is read-only")
        runs: list[EmailHealthRun] = []
        manifests: list[Path] = []
        duplicates = 0
        for request in fixture.requests():
            result: EmailHealthResult = await self._use_case.execute(request)
            runs.append(result.run)
            path = self._manifest_path(result.run)
            if result.duplicate:
                duplicates += 1
                if path.exists():
                    manifests.append(path)
            else:
                manifests.append(write_email_health_artifacts(self.artifact_store, result.run))
        return EmailHealthRuntimeResult(tuple(runs), duplicates, tuple(manifests))

    async def decide(
        self,
        run_id: str,
        evaluation_id: str,
        decision: OperationalDecision,
        reviewer_alias: str,
        reason: str,
    ) -> EmailHealthRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ValueError("Email health run not found")
        updated = run.decide(decision, evaluation_id, reviewer_alias, reason, datetime.now(UTC))
        await self.repository.save(updated)
        write_email_health_artifacts(self.artifact_store, updated)
        return updated

    async def verify(
        self,
        run_id: str,
        outcome: VerificationOutcome,
        evidence_ref: str,
        reviewer_alias: str,
        note: str,
    ) -> EmailHealthRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ValueError("Email health run not found")
        updated = run.verify(outcome, evidence_ref, reviewer_alias, note, datetime.now(UTC))
        await self.repository.save(updated)
        write_email_health_artifacts(self.artifact_store, updated)
        return updated

    def _manifest_path(self, run: EmailHealthRun) -> Path:
        return self.artifact_store.path("email-health", run.source_run_id, "manifest.json")


def build_fixture_runtime(db_path: Path, artifacts_root: Path) -> EmailHealthRuntime:
    repository = SqliteEmailHealthRepository(db_path)
    return EmailHealthRuntime(
        repository, ArtifactStore(artifacts_root), RunEmailHealthEvaluation(repository)
    )


def build_read_runtime(db_path: Path, artifacts_root: Path) -> EmailHealthRuntime:
    return EmailHealthRuntime(SqliteEmailHealthRepository(db_path), ArtifactStore(artifacts_root))


__all__ = [
    "EmailHealthRuntime",
    "EmailHealthRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
