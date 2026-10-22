"""PostgreSQL persistence for Creator outreach runs."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import creator_outreach_runs

from ..domain.models import CreatorOutreachRun
from .serialization import run_from_dict, run_to_dict


class PostgresCreatorOutreachRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, creator_outreach_runs, run_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, run: CreatorOutreachRun) -> None:
        await self._store.upsert(
            {
                "run_id": run.run_id,
                "source_run_id": run.source_run_id,
                "candidate_id": run.trigger.candidate_id,
                "state": run.state.value,
                "payload": run_to_dict(run),
            },
            ("state", "payload"),
        )

    async def get(self, run_id: str) -> CreatorOutreachRun | None:
        return await self._store.get(creator_outreach_runs.c.run_id, run_id)

    async def get_by_source_run_id(self, source_run_id: str) -> CreatorOutreachRun | None:
        return await self._store.get(creator_outreach_runs.c.source_run_id, source_run_id)

    async def list(self) -> list[CreatorOutreachRun]:
        return await self._store.list(ascending=True)


__all__ = ["PostgresCreatorOutreachRepository"]
