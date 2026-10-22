"""In-memory repository and queue adapters for unit/scenario tests."""

from __future__ import annotations

from typing import Any

from ..domain.entities import (
    ApprovalCard,
    AssetVersion,
    CreativeJob,
    CreativeJobId,
    VersionId,
)


class InMemoryCreativeRepository:
    """Non-persistent ICreativeRepository implementation."""

    def __init__(self) -> None:
        self._jobs: dict[str, CreativeJob] = {}
        self._versions: dict[str, AssetVersion] = {}

    async def save_job(self, job: CreativeJob) -> None:
        self._jobs[job.job_id.value] = job

    async def get_job(self, job_id: CreativeJobId) -> CreativeJob | None:
        return self._jobs.get(job_id.value)

    async def get_job_by_source_run_id(self, source_run_id: str) -> CreativeJob | None:
        for job in self._jobs.values():
            if job.source_run_id == source_run_id:
                return job
        return None

    async def list_jobs(self) -> list[CreativeJob]:
        return list(self._jobs.values())

    async def save_version(self, version: AssetVersion) -> None:
        self._versions[version.version_id.value] = version

    async def get_version(self, version_id: VersionId) -> AssetVersion | None:
        return self._versions.get(version_id.value)

    async def get_versions_for_job(self, job_id: CreativeJobId) -> list[AssetVersion]:
        versions = [v for v in self._versions.values() if v.version_id.job_id == job_id]
        return sorted(versions, key=lambda v: v.attempt_number)


class FakeApprovalQueue:
    """In-memory approval queue recording submitted cards and decisions."""

    def __init__(self) -> None:
        self.cards: list[ApprovalCard] = []
        self.decisions: list[dict[str, Any]] = []

    async def submit(self, card: ApprovalCard) -> None:
        self.cards.append(card)

    async def process_decision(
        self,
        job_id: CreativeJobId,
        version_id: VersionId,
        decision: str,
        reviewer: str,
        reason: str | None,
    ) -> None:
        self.decisions.append(
            {
                "job_id": job_id.value,
                "version_id": version_id.value,
                "decision": decision,
                "reviewer": reviewer,
                "reason": reason,
            }
        )


class FakeExceptionQueue:
    """In-memory exception queue recording escalation entries."""

    def __init__(self) -> None:
        self.exceptions: list[dict[str, Any]] = []

    async def create(
        self,
        job_id: CreativeJobId,
        exception_type: str,
        error_message: str,
        suggested_action: str | None,
    ) -> None:
        self.exceptions.append(
            {
                "job_id": job_id.value,
                "exception_type": exception_type,
                "error_message": error_message,
                "suggested_action": suggested_action,
            }
        )
