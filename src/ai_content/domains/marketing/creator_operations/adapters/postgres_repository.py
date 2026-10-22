"""PostgreSQL persistence for Creator evaluation runs."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import creator_evaluation_runs

from ..domain.models import CreatorEvaluationRun
from .serialization import run_from_dict, run_to_dict


class PostgresCreatorRunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, creator_evaluation_runs, run_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, run: CreatorEvaluationRun) -> None:
        await self._store.upsert(
            {
                "run_id": run.run_id,
                "source_run_id": run.source_run_id,
                "candidate_id": run.candidate_id,
                "source_checksum": run.source_checksum_sha256,
                "payload": run_to_dict(run),
            },
            ("payload",),
        )

    async def get(self, run_id: str) -> CreatorEvaluationRun | None:
        return await self._store.get(creator_evaluation_runs.c.run_id, run_id)

    async def get_by_source_run_id(self, source_run_id: str) -> CreatorEvaluationRun | None:
        return await self._store.get(creator_evaluation_runs.c.source_run_id, source_run_id)

    async def list(self) -> list[CreatorEvaluationRun]:
        return await self._store.list()


__all__ = ["PostgresCreatorRunRepository"]
