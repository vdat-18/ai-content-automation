"""Composition root for the synthetic Creator outreach workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_content.domains.marketing.creator_operations.adapters.artifacts import (
    write_creator_artifacts,
)
from ai_content.domains.marketing.creator_operations.adapters.sqlite_repository import (
    SqliteCreatorRunRepository,
)
from ai_content.domains.marketing.creator_operations.application.evaluation import (
    RunCreatorEvaluation,
)
from ai_content.domains.marketing.creator_operations.ports.interfaces import (
    ICreatorRunRepository,
)
from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.artifacts import write_creator_outreach_artifacts
from .adapters.creator_evidence import CreatorOperationsEvidenceAppender
from .adapters.fakes import (
    FixtureOutboundChannel,
    FixtureOutreachGenerator,
    FixtureOutreachReviewer,
)
from .adapters.projections import project_creator_contact
from .adapters.sqlite_repository import SqliteCreatorOutreachRepository
from .application.workflow import (
    DecideCreatorDeal,
    DecideCreatorOutreach,
    ProcessDueCreatorFollowups,
    RecordCreatorReply,
    RunCreatorOutreach,
)
from .config.fixtures import CreatorOutreachFixture, OutreachCaseFixture, ReplyFixture
from .domain.models import (
    CreatorOutreachRun,
    DealDecision,
    OutreachDecision,
    ReplyRecord,
)
from .ports.interfaces import ICreatorOutreachRepository


@dataclass(frozen=True)
class CreatorOutreachRuntimeResult:
    runs: tuple[CreatorOutreachRun, ...]
    duplicate_count: int
    manifest_paths: tuple[Path, ...]


class CreatorOutreachRuntime:
    def __init__(
        self,
        db_path: Path | None,
        artifacts_root: Path,
        *,
        repository: ICreatorOutreachRepository | None = None,
        creator_repository: ICreatorRunRepository | None = None,
    ) -> None:
        if repository is None or creator_repository is None:
            if db_path is None:
                raise ValueError("db_path is required when repositories are not provided")
            repository = repository or SqliteCreatorOutreachRepository(db_path)
            creator_repository = creator_repository or SqliteCreatorRunRepository(db_path)
        self.repository = repository
        self.creator_repository = creator_repository
        self.artifact_store = ArtifactStore(artifacts_root)
        self.channel = FixtureOutboundChannel()

    async def run(self, fixture: CreatorOutreachFixture) -> CreatorOutreachRuntimeResult:
        source_runs = {}
        source_use_case = RunCreatorEvaluation(self.creator_repository)
        for source in fixture.sources:
            prepared = source.prepared_evaluation()
            result = await source_use_case.execute(prepared.request())
            creator_run = result.run
            if creator_run.decision is None:
                creator_run = creator_run.decide(
                    source.decision,
                    creator_run.latest_evaluation.evaluation_id,
                    source.reviewer_alias,
                    source.reason,
                    datetime.now(UTC),
                )
                await self.creator_repository.save(creator_run)
                write_creator_artifacts(self.artifact_store, creator_run)
            source_runs[prepared.source_run_id] = creator_run

        runs: list[CreatorOutreachRun] = []
        manifests: list[Path] = []
        duplicates = 0
        for case in fixture.cases:
            source = source_runs[case.source_creator_run_id]
            trigger = project_creator_contact(source)
            use_case = self._run_use_case(case)
            result = await use_case.execute(case.request(trigger))
            runs.append(result.run)
            path = self._manifest_path(result.run)
            if result.duplicate:
                duplicates += 1
                if path.exists():
                    manifests.append(path)
            else:
                manifests.append(write_creator_outreach_artifacts(self.artifact_store, result.run))
        return CreatorOutreachRuntimeResult(tuple(runs), duplicates, tuple(manifests))

    def _run_use_case(self, case: OutreachCaseFixture) -> RunCreatorOutreach:
        return RunCreatorOutreach(
            self.repository,
            FixtureOutreachGenerator(
                tuple(item.domain() for item in case.plans), case.generator_version
            ),
            FixtureOutreachReviewer(tuple(item.domain() for item in case.reviews)),
        )

    async def decide_outreach(
        self,
        run_id: str,
        plan_version_id: str,
        evaluation_id: str,
        decision: OutreachDecision,
        reviewer_alias: str,
        reason: str,
    ) -> CreatorOutreachRun:
        updated = await DecideCreatorOutreach(self.repository, self.channel).execute(
            run_id,
            plan_version_id,
            evaluation_id,
            decision,
            reviewer_alias,
            reason,
            datetime.now(UTC),
        )
        write_creator_outreach_artifacts(self.artifact_store, updated)
        return updated

    async def process_due(
        self, as_of: datetime, run_id: str | None = None
    ) -> tuple[CreatorOutreachRun, ...]:
        updated = await ProcessDueCreatorFollowups(self.repository, self.channel).execute(
            as_of, run_id
        )
        for run in updated:
            write_creator_outreach_artifacts(self.artifact_store, run)
        return updated

    async def record_reply(self, run_id: str, reply: ReplyFixture) -> CreatorOutreachRun:
        return await self.record_reply_record(run_id, reply.domain())

    async def record_reply_record(self, run_id: str, reply: ReplyRecord) -> CreatorOutreachRun:
        appender = CreatorOperationsEvidenceAppender(self.creator_repository, self.artifact_store)
        result = await RecordCreatorReply(self.repository, appender).execute(run_id, reply)
        if not result.duplicate:
            write_creator_outreach_artifacts(self.artifact_store, result.run)
        return result.run

    async def decide_deal(
        self,
        run_id: str,
        reply_event_id: str,
        evaluation_id: str,
        decision: DealDecision,
        reviewer_alias: str,
        reason: str,
    ) -> CreatorOutreachRun:
        updated = await DecideCreatorDeal(self.repository).execute(
            run_id,
            reply_event_id,
            evaluation_id,
            decision,
            reviewer_alias,
            reason,
            datetime.now(UTC),
        )
        write_creator_outreach_artifacts(self.artifact_store, updated)
        return updated

    def _manifest_path(self, run: CreatorOutreachRun) -> Path:
        return self.artifact_store.path("creator-outreach", run.source_run_id, "manifest.json")

    def close(self) -> None:
        self.repository.close()
        self.creator_repository.close()


def build_fixture_runtime(db_path: Path, artifacts_root: Path) -> CreatorOutreachRuntime:
    return CreatorOutreachRuntime(db_path, artifacts_root)


def build_read_runtime(db_path: Path, artifacts_root: Path) -> CreatorOutreachRuntime:
    return CreatorOutreachRuntime(db_path, artifacts_root)


__all__ = [
    "CreatorOutreachRuntime",
    "CreatorOutreachRuntimeResult",
    "build_fixture_runtime",
    "build_read_runtime",
]
