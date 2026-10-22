"""Composition root for the synthetic-first Email reporting pilot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_report_artifacts
from .adapters.fakes import FixtureReportingSource
from .adapters.sqlite_repository import SqliteEmailReportRepository
from .application.reporting import EmailReportRunResult, RunEmailReport
from .config.fixtures import EmailReportFixture
from .domain.models import EmailPerformanceReport
from .ports.interfaces import IEmailReportRepository


@dataclass(frozen=True)
class EmailReportRuntimeResult:
    report: EmailPerformanceReport
    duplicate: bool
    manifest_path: Path | None


class EmailReportRuntime:
    """Thin facade for run, inspect and replay operations."""

    def __init__(
        self,
        repository: IEmailReportRepository,
        artifact_store: ArtifactStore,
        use_case: RunEmailReport | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._use_case = use_case

    async def run(self, fixture: EmailReportFixture) -> EmailReportRuntimeResult:
        if self._use_case is None:
            raise ValueError("This runtime is read-only; no reporting sources are configured")
        outcome: EmailReportRunResult = await self._use_case.execute(fixture.specification())
        if outcome.duplicate:
            path = self._manifest_path(outcome.report)
            return EmailReportRuntimeResult(outcome.report, True, path if path.exists() else None)
        persisted, path = write_report_artifacts(self.artifact_store, outcome.report)
        await self.repository.save(persisted)
        return EmailReportRuntimeResult(persisted, False, path)

    def _manifest_path(self, report: EmailPerformanceReport) -> Path:
        return self.artifact_store.path(
            "email-reports", report.specification.source_run_id, "manifest.json"
        )


def build_fixture_runtime(
    db_path: Path,
    artifacts_root: Path,
    fixture: EmailReportFixture,
) -> EmailReportRuntime:
    repository = SqliteEmailReportRepository(db_path)
    store = ArtifactStore(artifacts_root)
    snapshots = tuple(snapshot.to_domain() for snapshot in fixture.snapshots)
    sources = {
        source: FixtureReportingSource(
            source, tuple(snapshot for snapshot in snapshots if snapshot.source == source)
        )
        for source in {snapshot.source for snapshot in snapshots}
    }
    return EmailReportRuntime(repository, store, RunEmailReport(sources, repository))


def build_read_runtime(db_path: Path, artifacts_root: Path) -> EmailReportRuntime:
    """Build the API's read-only report runtime without external connectors."""
    return EmailReportRuntime(SqliteEmailReportRepository(db_path), ArtifactStore(artifacts_root))


__all__ = [
    "EmailReportRuntime",
    "EmailReportRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
