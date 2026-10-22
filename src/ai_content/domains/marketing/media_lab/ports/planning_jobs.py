"""Persistence boundary for durable Media Lab planning jobs."""

from __future__ import annotations

from typing import Protocol

from ..domain.planning_jobs import PlanningJob


class MediaLabPlanningJobError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int = 400, code: str = "invalid_request"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class IPlanningJobRepository(Protocol):
    async def save(self, job: PlanningJob) -> None: ...

    async def get(self, job_id: str) -> PlanningJob | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> PlanningJob | None: ...

    async def list_active(self) -> list[PlanningJob]: ...

    def close(self) -> None: ...


__all__ = ["IPlanningJobRepository", "MediaLabPlanningJobError"]
