"""PostgreSQL persistence for Performance decision runs."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import performance_decision_runs

from ..domain.models import PerformanceDecisionRun
from .serialization import run_from_dict, run_to_dict


class PostgresPerformanceDecisionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, performance_decision_runs, run_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, run: PerformanceDecisionRun) -> None:
        await self._store.upsert(
            {
                "run_id": run.run_id,
                "source_run_id": run.source_run_id,
                "source_checksum": run.source_checksum_sha256,
                "subject_type": run.snapshot.subject.subject_type.value,
                "subject_id": run.snapshot.subject.subject_id,
                "payload": run_to_dict(run),
            },
            ("payload",),
        )

    async def get(self, run_id: str) -> PerformanceDecisionRun | None:
        return await self._store.get(performance_decision_runs.c.run_id, run_id)

    async def get_by_source_run_id(self, source_run_id: str) -> PerformanceDecisionRun | None:
        return await self._store.get(performance_decision_runs.c.source_run_id, source_run_id)

    async def list(self) -> list[PerformanceDecisionRun]:
        return await self._store.list()


__all__ = ["PostgresPerformanceDecisionRepository"]
