"""PostgreSQL persistence for Creative loop runs."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import creative_loop_runs

from ..domain.models import CreativeLoopRun
from .serialization import run_from_dict, run_to_dict


class PostgresCreativeLoopRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, creative_loop_runs, run_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, run: CreativeLoopRun) -> None:
        await self._store.upsert(
            {
                "run_id": run.run_id,
                "source_run_id": run.source_run_id,
                "source_checksum": run.source_checksum_sha256,
                "state": run.state.value,
                "payload": run_to_dict(run),
            },
            ("state", "payload"),
        )

    async def get(self, run_id: str) -> CreativeLoopRun | None:
        return await self._store.get(creative_loop_runs.c.run_id, run_id)

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeLoopRun | None:
        return await self._store.get(creative_loop_runs.c.source_run_id, source_run_id)

    async def list(self) -> list[CreativeLoopRun]:
        return await self._store.list()


__all__ = ["PostgresCreativeLoopRepository"]
