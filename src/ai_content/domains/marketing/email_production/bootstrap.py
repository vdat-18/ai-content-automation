"""Composition root for the synthetic Email production workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_content.domains.marketing.email_health.adapters.sqlite_repository import (
    SqliteEmailHealthRepository,
)
from ai_content.domains.marketing.email_health.ports.interfaces import IEmailHealthRepository
from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_email_production_artifacts
from .adapters.fakes import FixtureEmailGenerator, FixtureSemanticReviewer
from .adapters.preflight import EmailHealthPreflightGateway
from .adapters.sqlite_repository import SqliteEmailProductionRepository
from .application.production import RunEmailProduction
from .config.fixtures import EmailProductionCaseFixture, EmailProductionFixture
from .domain.models import EmailProductionJob, HumanDecision
from .ports.interfaces import IEmailProductionRepository


@dataclass(frozen=True)
class EmailProductionRuntimeResult:
    jobs: tuple[EmailProductionJob, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]


class EmailProductionRuntime:
    def __init__(
        self,
        repository: IEmailProductionRepository,
        health_repository: IEmailHealthRepository,
        artifact_store: ArtifactStore,
    ) -> None:
        self.repository = repository
        self.health_repository = health_repository
        self.artifact_store = artifact_store

    async def run(self, fixture: EmailProductionFixture) -> EmailProductionRuntimeResult:
        rule_sets = {item.rule_set_id: item.domain() for item in fixture.preflight_rule_sets}
        jobs: list[EmailProductionJob] = []
        manifests: list[Path] = []
        duplicates = 0
        for case in fixture.cases:
            use_case = self._use_case(case, rule_sets[case.preflight.rule_set_ref])
            result = await use_case.execute(case.request())
            jobs.append(result.job)
            path = self._manifest_path(result.job)
            if result.duplicate:
                duplicates += 1
                if path.exists():
                    manifests.append(path)
            else:
                manifests.append(write_email_production_artifacts(self.artifact_store, result.job))
        return EmailProductionRuntimeResult(tuple(jobs), duplicates, tuple(manifests))

    def _use_case(self, case: EmailProductionCaseFixture, rule_set) -> RunEmailProduction:
        preflight = case.preflight
        observations = tuple(
            item.domain(case.account_id, preflight.source_system, preflight.integration_id)
            for item in preflight.observations
        )
        gateway = EmailHealthPreflightGateway(
            self.health_repository,
            self.artifact_store,
            rule_set,
            observations,
            preflight.observed_at,
            preflight.source_version,
            preflight.source_system,
            preflight.integration_id,
        )
        return RunEmailProduction(
            self.repository,
            FixtureEmailGenerator(
                tuple(item.domain() for item in case.packages), case.generator_version
            ),
            FixtureSemanticReviewer(tuple(item.domain() for item in case.reviews)),
            gateway,
        )

    async def decide(
        self,
        job_id: str,
        email_version_id: str,
        preflight_evaluation_id: str,
        decision: HumanDecision,
        reviewer_alias: str,
        reason: str,
    ) -> EmailProductionJob:
        job = await self.repository.get(job_id)
        if job is None:
            raise ValueError("Email production job not found")
        updated = job.decide(
            decision,
            email_version_id,
            preflight_evaluation_id,
            reviewer_alias,
            reason,
            datetime.now(UTC),
        )
        await self.repository.save(updated)
        write_email_production_artifacts(self.artifact_store, updated)
        return updated

    def _manifest_path(self, job: EmailProductionJob) -> Path:
        return self.artifact_store.path("email-production", job.source_run_id, "manifest.json")

    def close(self) -> None:
        self.repository.close()
        self.health_repository.close()


def build_fixture_runtime(db_path: Path, artifacts_root: Path) -> EmailProductionRuntime:
    return EmailProductionRuntime(
        SqliteEmailProductionRepository(db_path),
        SqliteEmailHealthRepository(db_path),
        ArtifactStore(artifacts_root),
    )


def build_read_runtime(db_path: Path, artifacts_root: Path) -> EmailProductionRuntime:
    return build_fixture_runtime(db_path, artifacts_root)


__all__ = [
    "EmailProductionRuntime",
    "EmailProductionRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
