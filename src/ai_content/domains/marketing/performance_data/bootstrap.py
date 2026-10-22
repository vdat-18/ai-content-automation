"""Composition root for the synthetic GMC ingestion pilot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.catalog import JsonProductCatalog
from .adapters.csv_source import CsvGmcSource
from .adapters.output_writer import CsvGmcOutputWriter
from .adapters.sqlite_repository import SqliteGmcRunRepository
from .application.ingestion import GmcRunResult, RunGmcIngestion
from .config.fixtures import GmcFixture
from .domain.models import GmcIngestionRun
from .ports.interfaces import IGmcRunRepository


@dataclass(frozen=True)
class GmcRuntimeResult:
    run: GmcIngestionRun
    duplicate: bool


class GmcRuntime:
    """Thin facade for fixture run and read-only inspection."""

    def __init__(self, repository: IGmcRunRepository, use_case: RunGmcIngestion) -> None:
        self.repository = repository
        self._use_case = use_case

    async def run(self, fixture: GmcFixture) -> GmcRuntimeResult:
        result: GmcRunResult = await self._use_case.execute(fixture.specification())
        return GmcRuntimeResult(result.run, result.duplicate)


def build_fixture_runtime(db_path: Path, artifacts_root: Path, fixture: GmcFixture) -> GmcRuntime:
    repository = SqliteGmcRunRepository(db_path)
    store = ArtifactStore(artifacts_root)
    return GmcRuntime(
        repository,
        RunGmcIngestion(
            source=CsvGmcSource(fixture.source_file),
            catalog=JsonProductCatalog(fixture.catalog_file),
            writer=CsvGmcOutputWriter(store),
            repository=repository,
        ),
    )


__all__ = ["GmcRuntime", "GmcRuntimeResult", "build_fixture_runtime"]
